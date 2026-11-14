"""
integration tests for main() with a Lightroom catalog (-l / -s)
the catalog is a minimal SQLite file with only the tables used by the script (see LightroomCatalog)
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from integration_helpers import TOKYO_LAT, TOKYO_LONG, FakeLookup, LightroomCatalog, RunResult, read_xmp, write_xmp

Run = Callable[..., RunResult]
Snapshot = Callable[[Path], dict[Path, bytes]]

LOOKUP_FIELDS = {"Location": "Jingumae", "City": "Shibuya", "State": "Tokyo", "Country": "Japan", "CountryCode": "JP"}
LIGHTROOM_FIELDS = {"Location": "Namba", "City": "Osaka", "State": "Osaka", "Country": "Japan", "CountryCode": "JP"}
NO_GPS = {"GPSLatitude": "", "GPSLongitude": ""}


@pytest.fixture
def catalog(tmp_path: Path) -> LightroomCatalog:
    return LightroomCatalog(tmp_path / "lightroom")


def location(path: Path) -> dict[str, str]:
    data = read_xmp(path)
    return {key: data[key] for key in LOOKUP_FIELDS}


# MARK: Lightroom data combined with the map lookup
def test_lightroom_partial_data_kept_with_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalog, lookup: FakeLookup
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
    run_main: Run, tmp_path: Path, catalog: LightroomCatalog, lookup: FakeLookup
) -> None:
    # no GPS in the XMP, GPS from Lightroom, no location data: lookup with the Lightroom GPS
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=-33.85, gps_longitude=151.21)
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == [{"longitude": "151,12.6E", "latitude": "33,51.0S", "map_type": "google"}]
    # the Lightroom GPS is written to the XMP too
    assert read_xmp(file) == {"GPSLatitude": "33,51.0S", "GPSLongitude": "151,12.6E", **LOOKUP_FIELDS}


def test_lightroom_data_written_if_lookup_fails(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalog, lookup: FakeLookup
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
    run_main: Run, tmp_path: Path, catalog: LightroomCatalog, lookup: FakeLookup
) -> None:
    # no GPS anywhere: no lookup possible, the Lightroom data is still written
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert location(file)["City"] == "Osaka"
    assert result.statuses() == {"a.xmp": "UPDATED"}


def test_lightroom_and_lookup_counted(run_main: Run, tmp_path: Path, catalog: LightroomCatalog) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    catalog.add_image(file, City="Osaka")
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("New GeoLocation from Map") == 1
    assert result.stat("Updated") == 1


def test_lightroom_complete_no_lookup(
    run_main: Run, tmp_path: Path, catalog: LightroomCatalog, lookup: FakeLookup
) -> None:
    # all data from Lightroom: no lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", **NO_GPS)
    catalog.add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LIGHTROOM_FIELDS)
    result = run_main("-i", tmp_path / "src", "-l", catalog.folder)
    assert lookup.calls == []
    assert read_xmp(file) == {"GPSLatitude": "35,30.0N", "GPSLongitude": "139,30.0E", **LIGHTROOM_FIELDS}
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("New GeoLocation from Map") == 0


def test_lightroom_does_not_replace_xmp_values(run_main: Run, tmp_path: Path, catalog: LightroomCatalog) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Kyoto")
    catalog.add_image(file, gps_latitude=1.0, gps_longitude=1.0, City="Osaka", State="Osaka")
    run_main("-i", tmp_path / "src", "-l", catalog.folder)
    data = read_xmp(file)
    # existing XMP values (GPS and City) are kept
    assert data["GPSLatitude"] == TOKYO_LAT
    assert data["GPSLongitude"] == TOKYO_LONG
    assert data["City"] == "Kyoto"
    assert data["State"] == "Osaka"


# __END__
