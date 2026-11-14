"""
integration tests for main() with a Lightroom catalog (-l / -s)
the catalog is a minimal SQLite file with only the tables used by the script (see LightroomCatalogBuilder)
"""

import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from helpers.lightroom_catalog_builder import LightroomCatalogBuilder
from integration_helpers import TOKYO_LAT, TOKYO_LONG, FakeLookup, RunResult, read_xmp, write_xmp

Run = Callable[..., RunResult]
Snapshot = Callable[[Path], dict[Path, bytes]]

LOOKUP_FIELDS = {"Location": "Jingumae", "City": "Shibuya", "State": "Tokyo", "Country": "Japan", "CountryCode": "JP"}
LIGHTROOM_FIELDS = {"Location": "Namba", "City": "Osaka", "State": "Osaka", "Country": "Japan", "CountryCode": "JP"}
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


# __END__
