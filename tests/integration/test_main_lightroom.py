"""
integration tests for main() with a Lightroom catalog (-l / -s)
the catalog is a minimal SQLite file with only the tables used by the script (see LightroomCatalogBuilder)
"""

import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from helpers.lightroom_catalog_builder import LightroomCatalogBuilder, LocationFields
from integration_helpers import TOKYO_LAT, TOKYO_LONG, FakeLookup, RunResult, read_xmp, write_xmp

Run = Callable[..., RunResult]
Snapshot = Callable[[Path], dict[Path, bytes]]

LOOKUP_FIELDS = {"Location": "Jingumae", "City": "Shibuya", "State": "Tokyo", "Country": "Japan", "CountryCode": "JP"}
LIGHTROOM_FIELDS: LocationFields = {
    "Location": "Namba",
    "City": "Osaka",
    "State": "Osaka",
    "Country": "Japan",
    "CountryCode": "JP",
}
# the same values for the XMP files (write_xmp takes str keyword arguments)
LIGHTROOM_XMP_FIELDS = cast(dict[str, str], LIGHTROOM_FIELDS)
NO_GPS = {"GPSLatitude": "", "GPSLongitude": ""}


@pytest.fixture
def catalog(tmp_path: Path) -> LightroomCatalogBuilder:
    return LightroomCatalogBuilder(tmp_path / "lightroom")


def location(path: Path) -> dict[str, str]:
    data = read_xmp(path)
    return {key: data[key] for key in LOOKUP_FIELDS}


# MARK: Lightroom data combined with the map lookup
def test_lightroom_partial_data_kept_with_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # Lightroom has City and Country, the rest comes from the lookup
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka", Country="Nippon")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert len(lookup.calls) == 1
    # Lightroom values have priority over the lookup
    assert location(file) == {**LOOKUP_FIELDS, "City": "Osaka", "Country": "Nippon"}
    assert result.statuses() == {"a.xmp": "UPDATED"}


def test_lightroom_gps_written_with_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # no GPS in the XMP, GPS from Lightroom, no location data: lookup with the Lightroom GPS
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=-33.85, gps_longitude=151.21)
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == [{"longitude": "151,12.6E", "latitude": "33,51.0S", "map_type": "google"}]
    # the Lightroom GPS is written to the XMP too
    assert read_xmp(file) == {"GPSLatitude": "33,51.0S", "GPSLongitude": "151,12.6E", **LOOKUP_FIELDS}


def test_lightroom_data_written_if_lookup_fails(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    lookup.result = {**lookup.result, "Country": ""}
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    # the lookup failed, but the Lightroom data is still written
    assert location(file) == {"Location": "", "City": "Osaka", "State": "", "Country": "", "CountryCode": ""}
    assert result.statuses() == {"a.xmp": "UPDATED"}
    assert result.stat("GeoLocation from Lightroom") == 1


def test_lightroom_data_written_without_gps(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # no GPS anywhere: no lookup possible, the Lightroom data is still written
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert location(file)["City"] == "Osaka"
    assert result.statuses() == {"a.xmp": "UPDATED"}


def test_lightroom_and_lookup_counted(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("New GeoLocation from Map") == 1
    assert result.stat("Updated") == 1


def test_lightroom_complete_no_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # all data from Lightroom: no lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert read_xmp(file) == {"GPSLatitude": "35,30.0N", "GPSLongitude": "139,30.0E", **LIGHTROOM_FIELDS}
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("New GeoLocation from Map") == 0


def test_lightroom_does_not_replace_xmp_values(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto")
    catalog.add_image(file, gps_latitude=1.0, gps_longitude=1.0, City="Osaka", State="Osaka")
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    data = read_xmp(file)
    # existing XMP values (GPS and City) are kept
    assert data["GPSLatitude"] == TOKYO_LAT
    assert data["GPSLongitude"] == TOKYO_LONG
    assert data["City"] == "Kyoto"
    assert data["State"] == "Osaka"


# MARK: catalog file
def test_catalog_opened_read_only(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # record the connect arguments, the real connect is still used
    connect_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_connect = sqlite3.connect

    def spy_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connect_calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    from reverse_geolocate.utils import lightroom as lightroom_module

    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    # after the catalog is filled, the test helper uses sqlite3.connect too
    monkeypatch.setattr(lightroom_module.sqlite3, "connect", spy_connect)
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert len(connect_calls) == 1
    args, kwargs = connect_calls[0]
    assert args[0] == f"{catalog.path.resolve().as_uri()}?mode=ro"
    assert kwargs == {"uri": True}


def test_catalog_not_changed(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, snapshot: Snapshot
) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    before = snapshot(catalog.folder)
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    # same content, no journal or other files added
    assert snapshot(catalog.folder) == before


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
def test_catalog_read_only_file(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    # a catalog without write permission can be used
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    catalog.path.chmod(0o444)
    try:
        result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    finally:
        catalog.path.chmod(0o644)
    assert result.exit_code is None
    assert location(file)["City"] == "Osaka"


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
def test_catalog_not_readable(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    catalog.path.chmod(0o000)
    try:
        result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    finally:
        catalog.path.chmod(0o644)
    assert result.exit_code == 1
    assert "(!) Could not open the Lightroom catalog" in result.out


def test_catalog_path_special_characters(run_main: Run, tmp_path: Path) -> None:
    # spaces, "?", "#" and "%" must be escaped in the read only URI
    catalog = LightroomCatalogBuilder(tmp_path / "Light room #1?", name="My Catalog 100%.lrcat")
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert result.exit_code is None
    assert location(file)["City"] == "Osaka"


@pytest.mark.parametrize("name", ["Catalog.LRCAT", "Catalog.LrCat", "catalog.lrcat"])
def test_catalog_extension_any_case(run_main: Run, tmp_path: Path, name: str) -> None:
    catalog = LightroomCatalogBuilder(tmp_path / "lightroom", name=name)
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert result.exit_code is None
    assert location(file)["City"] == "Osaka"


def test_catalog_first_by_name(run_main: Run, tmp_path: Path) -> None:
    first = LightroomCatalogBuilder(tmp_path / "lightroom", name="a.lrcat")
    second = LightroomCatalogBuilder(tmp_path / "lightroom", name="b.LRCAT")
    file = write_xmp(tmp_path / "src" / "a.xmp")
    first.add_image(file, City="First")
    second.add_image(file, City="Second")
    run_main("-i", tmp_path / "src", "-l", tmp_path / "lightroom")
    assert location(file)["City"] == "First"


def test_catalog_folders_and_other_files_ignored(run_main: Run, tmp_path: Path) -> None:
    folder = tmp_path / "lightroom"
    # Lightroom side folders/files, and a folder named like a catalog
    for name in ("a Catalog Previews.lrdata", "a Catalog.lrcat-data", "a.lrcat"):
        (folder / name).mkdir(parents=True)
    (folder / "a.lrcat-wal").write_text("", encoding="UTF-8")
    (folder / "a.lrcat.lock").write_text("", encoding="UTF-8")
    catalog = LightroomCatalogBuilder(folder, name="z.lrcat")
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", folder)
    assert result.exit_code is None
    assert location(file)["City"] == "Osaka"


def test_no_catalog_in_folder(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    (tmp_path / "lightroom").mkdir()
    (tmp_path / "lightroom" / "notes.txt").write_text("", encoding="UTF-8")
    file = write_xmp(tmp_path / "src" / "a.xmp")
    before = file.read_bytes()
    result = run_main("-i", tmp_path / "src", "-l", tmp_path / "lightroom")
    assert result.exit_code == 1
    assert "(!) We could not find a lrcat file in the given lightroom folder" in result.out
    # nothing done
    assert lookup.calls == []
    assert file.read_bytes() == before


# MARK: not found / more than one
def test_not_found(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup) -> None:
    # the XMP file is not in the catalog: lookup as without Lightroom
    catalog.add_image(tmp_path / "src" / "other.xmp", **LIGHTROOM_FIELDS)
    file = write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert "(!) Could not get data from Lightroom DB" in result.out
    assert len(lookup.calls) == 1
    assert location(file) == LOOKUP_FIELDS
    assert result.statuses() == {"a.xmp": "UPDATED"}
    assert result.stat("No Lightroom data found") == 1
    assert result.stat("GeoLocation from Lightroom") == 0
    assert result.stat("More than one found in Lightroom") == 0


def test_not_found_complete_file(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert result.stat("No Lightroom data found") == 1
    assert result.stat("Skipped") == 1


def test_many_found_not_used(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # same base name in two catalog folders: the Lightroom data is not used, lookup instead
    catalog.add_image(tmp_path / "one" / "a.xmp", gps_latitude=1.0, gps_longitude=1.0, City="One")
    catalog.add_image(tmp_path / "two" / "a.xmp", gps_latitude=2.0, gps_longitude=2.0, City="Two")
    file = write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert "(!) Lightroom DB returned more than one row" in result.out
    assert lookup.calls == [{"longitude": TOKYO_LONG, "latitude": TOKYO_LAT, "map_type": "google"}]
    assert read_xmp(file) == {"GPSLatitude": TOKYO_LAT, "GPSLongitude": TOKYO_LONG, **LOOKUP_FIELDS}
    assert result.stat("More than one found in Lightroom") == 1
    assert result.stat("GeoLocation from Lightroom") == 0
    assert result.stat("No Lightroom data found") == 0


def test_many_found_no_gps_fails(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # the Lightroom GPS is not used either: no GPS, no lookup
    catalog.add_image(tmp_path / "one" / "a.xmp", gps_latitude=1.0, gps_longitude=1.0)
    catalog.add_image(tmp_path / "two" / "a.xmp", gps_latitude=2.0, gps_longitude=2.0)
    write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert result.statuses() == {"a.xmp": "FAILED"}


def test_counts_over_several_files(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    src = tmp_path / "src"
    catalog.add_image(
        write_xmp(src / "1_found.xmp", **NO_GPS), gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS
    )
    write_xmp(src / "2_not_found.xmp")
    write_xmp(src / "3_not_found.xmp", **LOOKUP_FIELDS)
    catalog.add_image(tmp_path / "x" / "4_many.xmp")
    catalog.add_image(tmp_path / "y" / "4_many.xmp")
    write_xmp(src / "4_many.xmp")
    result = run_main("-i", src, "-l", catalog.folder, "-v")
    assert result.statuses() == {
        "1_found.xmp": "UPDATED",
        "2_not_found.xmp": "UPDATED",
        "3_not_found.xmp": "SKIP",
        "4_many.xmp": "UPDATED FROM CACHE",
    }
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("No Lightroom data found") == 2
    assert result.stat("More than one found in Lightroom") == 1
    assert result.stat("Updated") == 3


# MARK: strict
def test_strict_uses_matching_folder(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # not strict: more than one, strict: the image in the folder of the XMP file
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(tmp_path / "other" / "a.xmp", gps_latitude=1.0, gps_longitude=1.0, City="Other")
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    not_strict = run_main("-i", tmp_path / "src", "-l", catalog.folder, "--test")
    assert not_strict.stat("More than one found in Lightroom") == 1
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "-s")
    assert lookup.calls == []
    assert read_xmp(file) == {"GPSLatitude": "35,30.0N", "GPSLongitude": "139,30.0E", **LIGHTROOM_FIELDS}
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("More than one found in Lightroom") == 0


def test_strict_other_folder_not_found(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    catalog.add_image(tmp_path / "other" / "a.xmp", **LIGHTROOM_FIELDS)
    file = write_xmp(tmp_path / "src" / "a.xmp")
    # not strict: found by name
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "--test")
    assert lookup.calls == []
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "--strict")
    assert result.stat("No Lightroom data found") == 1
    assert location(file) == LOOKUP_FIELDS


@pytest.mark.parametrize("source", ["src", "./src/", "link", "other/../src"])
def test_strict_path_forms(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    # relative paths, "./", "../" and symlinks match the real folder in the catalog
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, **LIGHTROOM_FIELDS)
    (tmp_path / "link").symlink_to(tmp_path / "src")
    (tmp_path / "other").mkdir()
    monkeypatch.chdir(tmp_path)
    result = run_main("-i", source, "-l", catalog.folder, "-s")
    assert result.stat("GeoLocation from Lightroom") == 1
    assert location(file) == LIGHTROOM_FIELDS


# MARK: field controls
def test_selected_field_limits_lightroom(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, **LIGHTROOM_FIELDS)
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "city")
    # only City is written, from Lightroom, no lookup needed
    assert location(file) == {"Location": "", "City": "Osaka", "State": "", "Country": "", "CountryCode": ""}
    assert lookup.calls == []


@pytest.mark.parametrize("argv", [["-f", "city"], ["-f", "country"], ["-f", "city", "-f", "overwrite"], []])
def test_lightroom_gps_written_with_any_field_controls(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, argv: list[str]
) -> None:
    # GPS is not selectable with -f: missing GPS from Lightroom is always written,
    # the location data is not written without the coordinates it is based on
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    run_main("-i", tmp_path / "src", "-l", catalog.folder, *argv)
    data = read_xmp(file)
    assert data["GPSLatitude"] == "35,30.0N"
    assert data["GPSLongitude"] == "139,30.0E"


def test_selected_field_gps_and_city_written(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "city")
    # GPS and the selected field, not the other location fields
    assert read_xmp(file) == {
        "GPSLatitude": "35,30.0N",
        "GPSLongitude": "139,30.0E",
        "Location": "",
        "City": "Osaka",
        "State": "",
        "Country": "",
        "CountryCode": "",
    }


def test_selected_field_lookup_with_lightroom_gps(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # only GPS in Lightroom: lookup with the Lightroom GPS, the GPS and the selected field are written
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5)
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "city")
    assert lookup.calls == [{"longitude": "139,30.0E", "latitude": "35,30.0N", "map_type": "google"}]
    data = read_xmp(file)
    assert data["GPSLatitude"] == "35,30.0N"
    assert data["City"] == "Shibuya"
    assert data["State"] == ""


def test_selected_field_already_set_only_gps_written(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # the selected field is set: no lookup, only the missing GPS is filled
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "city")
    assert lookup.calls == []
    data = read_xmp(file)
    assert data["GPSLatitude"] == "35,30.0N"
    assert data["City"] == "Kyoto"
    assert data["State"] == ""
    assert result.statuses() == {"a.xmp": "UPDATED"}
    assert result.stat("GeoLocation from Lightroom") == 1


@pytest.mark.parametrize("argv", [[], ["-f", "overwrite"], ["-f", "city", "-f", "overwrite"]])
def test_existing_gps_never_replaced_by_lightroom(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, argv: list[str]
) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, gps_latitude=1.0, gps_longitude=2.0, **LIGHTROOM_FIELDS)
    run_main("-i", tmp_path / "src", "-l", catalog.folder, *argv)
    data = read_xmp(file)
    assert data["GPSLatitude"] == TOKYO_LAT
    assert data["GPSLongitude"] == TOKYO_LONG


def test_overwrite_lightroom_first_no_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # overwrite: Lightroom replaces the set XMP values, complete Lightroom data: no lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto", State="Kyoto")
    catalog.add_image(file, **LIGHTROOM_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "overwrite")
    assert lookup.calls == []
    assert location(file) == LIGHTROOM_FIELDS
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("New GeoLocation from Map") == 0


def test_overwrite_lightroom_first_lookup_for_the_rest(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # Lightroom has City and Location: from Lightroom, the other set fields are replaced by the lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto", State="Kyoto", Country="Nippon")
    catalog.add_image(file, City="Osaka", Location="Namba")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "overwrite")
    assert len(lookup.calls) == 1
    assert location(file) == {**LOOKUP_FIELDS, "City": "Osaka", "Location": "Namba"}
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("New GeoLocation from Map") == 1


def test_overwrite_lightroom_same_value_not_replaced_by_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup, snapshot: Snapshot
) -> None:
    # Lightroom has the same values as the XMP: they stay, nothing to write
    write_xmp(tmp_path / "src" / "a.xmp", **LIGHTROOM_XMP_FIELDS)
    catalog.add_image(tmp_path / "src" / "a.xmp", **LIGHTROOM_FIELDS)
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "overwrite", "-v")
    assert lookup.calls == []
    assert snapshot(tmp_path / "src") == before
    assert result.statuses() == {"a.xmp": "SKIP"}


def test_overwrite_lightroom_partial_same_value_kept(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # City is the same in XMP and Lightroom: kept, the other fields come from the lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", **LIGHTROOM_XMP_FIELDS)
    catalog.add_image(file, City="Osaka")
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "overwrite")
    assert len(lookup.calls) == 1
    assert location(file) == {**LOOKUP_FIELDS, "City": "Osaka"}


def test_overwrite_lightroom_empty_value_not_cleared(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # Lightroom has no State: the lookup replaces it (an empty Lightroom value never clears)
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto", State="Kyoto")
    catalog.add_image(file, City="Osaka")
    lookup.result = {**lookup.result, "State": ""}
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "overwrite")
    data = location(file)
    assert data["City"] == "Osaka"
    # no State from Lightroom and the lookup: the XMP value stays
    assert data["State"] == "Kyoto"


def test_overwrite_selected_field_from_lightroom(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # -f city -f overwrite: only City is replaced, from Lightroom, no lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto", State="Kyoto")
    catalog.add_image(file, **LIGHTROOM_FIELDS)
    run_main("-i", tmp_path / "src", "-l", catalog.folder, "-f", "city", "-f", "overwrite")
    assert lookup.calls == []
    assert location(file) == {"Location": "", "City": "Osaka", "State": "Kyoto", "Country": "", "CountryCode": ""}


def test_no_overwrite_lightroom_keeps_xmp_values(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, lookup: FakeLookup
) -> None:
    # without overwrite: Lightroom only fills empty fields
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto")
    catalog.add_image(file, **LIGHTROOM_FIELDS)
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert location(file) == {**LIGHTROOM_FIELDS, "City": "Kyoto"}


def test_overwrite_without_lightroom_unchanged(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    # without Lightroom overwrite uses the lookup as before
    file = write_xmp(tmp_path / "src" / "a.xmp", **LIGHTROOM_XMP_FIELDS)
    run_main("-i", tmp_path / "src", "-f", "overwrite")
    assert len(lookup.calls) == 1
    assert location(file) == LOOKUP_FIELDS


# MARK: output
def test_debug_output(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "--debug")
    assert f"### USE Lightroom {catalog.path}" in result.lines
    assert any("### LightroomDB: (" in line and "'Osaka'" in line for line in result.lines)
    assert "### -> LR: City => Osaka" in result.lines
    # complete after the Lightroom data: no lookup
    assert "Lightroom data use: True, Lightroom data ok: True" in result.out


def test_debug_output_not_found(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "--debug")
    assert "Lightroom data use: True, Lightroom data ok: False" in result.out
    assert "### LightroomDB:" not in result.out


def test_debug_output_many_found(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    # the first image is shown in the debug output, but not used
    catalog.add_image(tmp_path / "one" / "a.xmp", City="One")
    catalog.add_image(tmp_path / "two" / "a.xmp", City="Two")
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder, "--debug")
    assert "### LightroomDB: (" in result.out
    assert "### -> LR:" not in result.out
    assert "Lightroom data use: True, Lightroom data ok: False" in result.out


def test_debug_without_lightroom(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    result = run_main("-i", tmp_path / "src", "--debug")
    assert "Lightroom data use: False, Lightroom data ok: False" in result.out
    assert "### USE Lightroom" not in result.out


def test_statistics_only_with_lightroom(run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    without = run_main("-i", tmp_path / "src")
    with_lightroom = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    for name in ("GeoLocation from Lightroom", "No Lightroom data found", "More than one found in Lightroom"):
        assert name not in without.out
        assert name in with_lightroom.out


def test_read_only_with_lightroom(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, snapshot: Snapshot
) -> None:
    # read only: the catalog is opened (must exist) but not used, no Lightroom statistics
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    before = snapshot(tmp_path / "src")
    result = run_main("-r", "-i", tmp_path / "src", "-l", catalog.folder)
    assert result.exit_code is None
    assert result.table_rows()[0][1:8] == ["", "", "", "", "", "", ""]
    assert "Lightroom" not in result.out
    assert snapshot(tmp_path / "src") == before


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
def test_catalog_closed_after_critical_error(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalogBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reverse_geolocate.utils.lightroom import LightroomCatalog

    closed: list[str] = []
    real_close = LightroomCatalog.close

    def spy_close(self: LightroomCatalog) -> None:
        closed.append(self.database)
        real_close(self)

    monkeypatch.setattr(LightroomCatalog, "close", spy_close)
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    file.chmod(0o444)
    try:
        result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    finally:
        file.chmod(0o644)
    assert result.exit_code == 1
    assert closed == [str(catalog.path)]


# __END__
