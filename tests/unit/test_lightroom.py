"""
unit tests for reverse_geolocate.utils.lightroom
uses a minimal Lightroom catalog in a temporary folder (see LightroomCatalogBuilder)
"""

import os
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from helpers.lightroom_catalog_builder import LightroomCatalogBuilder

from reverse_geolocate.utils.lightroom import (
    LightroomCatalog,
    LightroomError,
    find_catalog_file,
    lightroom_gps,
    merge_lightroom_data,
)

needs_permissions = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
EMPTY_DATA_SET: dict[str, str] = dict.fromkeys(
    ("GPSLatitude", "GPSLongitude", "Location", "City", "State", "Country", "CountryCode"), ""
)


@pytest.fixture
def builder(tmp_path: Path) -> LightroomCatalogBuilder:
    return LightroomCatalogBuilder(tmp_path / "lightroom")


def make_row(**values: Any) -> sqlite3.Row:
    """a sqlite3.Row with the Lightroom columns, missing columns are NULL"""
    columns = {
        "gpsLatitude": None,
        "gpsLongitude": None,
        "Location": None,
        "City": None,
        "State": None,
        "Country": None,
        "CountryCode": None,
        **values,
    }
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    select = ", ".join(f":{name} AS {name}" for name in columns)
    row = cast(sqlite3.Row, connection.execute(f"SELECT {select}", columns).fetchone())
    connection.close()
    return row


# MARK: find_catalog_file
def test_find_catalog_file_none(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("", encoding="UTF-8")
    assert find_catalog_file(str(tmp_path)) is None


def test_find_catalog_file_first_by_name(tmp_path: Path) -> None:
    for name in ("c.lrcat", "a.LRCAT", "b.lrcat"):
        (tmp_path / name).write_text("", encoding="UTF-8")
    assert find_catalog_file(str(tmp_path)) == str(tmp_path / "a.LRCAT")


@pytest.mark.parametrize("name", ["a.lrcat", "a.LRCAT", "a.LrCat"])
def test_find_catalog_file_any_case(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("", encoding="UTF-8")
    assert find_catalog_file(str(tmp_path)) == str(tmp_path / name)


def test_find_catalog_file_only_files(tmp_path: Path) -> None:
    (tmp_path / "a.lrcat").mkdir()
    (tmp_path / "b Previews.lrdata").mkdir()
    (tmp_path / "c.lrcat-wal").write_text("", encoding="UTF-8")
    (tmp_path / "d.lrcat.lock").write_text("", encoding="UTF-8")
    assert find_catalog_file(str(tmp_path)) is None
    (tmp_path / "z.lrcat").write_text("", encoding="UTF-8")
    assert find_catalog_file(str(tmp_path)) == str(tmp_path / "z.lrcat")


# MARK: open / close
def test_open(builder: LightroomCatalogBuilder) -> None:
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        assert catalog.database == str(builder.path)
        assert catalog.strict is False


def test_open_strict(builder: LightroomCatalogBuilder) -> None:
    with LightroomCatalog.open(str(builder.folder), strict=True) as catalog:
        assert catalog.strict is True


def test_open_no_catalog(tmp_path: Path) -> None:
    with pytest.raises(LightroomError, match="We could not find a lrcat file in the given lightroom folder"):
        LightroomCatalog.open(str(tmp_path))


def test_open_read_only(builder: LightroomCatalogBuilder) -> None:
    with (
        LightroomCatalog.open(str(builder.folder)) as catalog,
        pytest.raises(sqlite3.OperationalError, match="readonly"),
    ):
        catalog.connection.execute("DELETE FROM Adobe_images")


@needs_permissions
def test_open_not_readable(builder: LightroomCatalogBuilder) -> None:
    builder.path.chmod(0o000)
    try:
        with pytest.raises(LightroomError, match="Could not open the Lightroom catalog"):
            LightroomCatalog.open(str(builder.folder))
    finally:
        builder.path.chmod(0o644)


def test_open_special_characters(tmp_path: Path) -> None:
    builder = LightroomCatalogBuilder(tmp_path / "Light room #1?", name="My Catalog 100%.lrcat")
    builder.add_image(tmp_path / "src" / "a.xmp", City="Osaka")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        assert catalog.find(str(tmp_path / "src" / "a.xmp")).status == "found"


def test_close(builder: LightroomCatalogBuilder) -> None:
    catalog = LightroomCatalog.open(str(builder.folder))
    catalog.close()
    with pytest.raises(sqlite3.ProgrammingError):
        catalog.connection.execute("SELECT 1")


def test_context_manager_closes(builder: LightroomCatalogBuilder) -> None:
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        catalog.connection.execute("SELECT 1")


def test_context_manager_closes_on_error(builder: LightroomCatalogBuilder) -> None:
    catalog = LightroomCatalog.open(str(builder.folder))
    with pytest.raises(RuntimeError), catalog:
        raise RuntimeError("stop")
    with pytest.raises(sqlite3.ProgrammingError):
        catalog.connection.execute("SELECT 1")


# MARK: find
def test_find_found(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    xmp_file = tmp_path / "photos" / "a.xmp"
    builder.add_image(xmp_file, gps_latitude=35.5, gps_longitude=139.5, City="Osaka", CountryCode="JP")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        result = catalog.find(str(xmp_file))
    assert result.status == "found"
    assert result.row is not None
    assert result.row["gpsLatitude"] == 35.5
    assert result.row["gpsLongitude"] == 139.5
    assert result.row["City"] == "Osaka"
    assert result.row["CountryCode"] == "JP"
    assert result.row["Location"] is None
    assert result.row["baseName"] == "a"


def test_find_not_found(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    builder.add_image(tmp_path / "photos" / "a.xmp")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        result = catalog.find(str(tmp_path / "photos" / "b.xmp"))
    assert result.status == "not_found"
    assert result.row is None


def test_find_many_found(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    builder.add_image(tmp_path / "one" / "a.xmp", City="One")
    builder.add_image(tmp_path / "two" / "a.xmp", City="Two")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        result = catalog.find(str(tmp_path / "three" / "a.xmp"))
    assert result.status == "many_found"
    # the first image is kept (debug output), it must not be used
    assert result.row is not None


@pytest.mark.parametrize("file_name", ["a.xmp", "a.XMP", "a.Xmp"])
def test_find_base_name_any_extension_case(builder: LightroomCatalogBuilder, tmp_path: Path, file_name: str) -> None:
    builder.add_image(tmp_path / "photos" / "a.xmp")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        assert catalog.find(str(tmp_path / "photos" / file_name)).status == "found"


def test_find_base_name_with_dots(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    builder.add_image(tmp_path / "photos" / "2026.11.10_photo.xmp")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        assert catalog.find(str(tmp_path / "photos" / "2026.11.10_photo.xmp")).status == "found"
        assert catalog.find(str(tmp_path / "photos" / "2026.xmp")).status == "not_found"


def test_find_not_strict_ignores_folder(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    builder.add_image(tmp_path / "photos" / "a.xmp")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        assert catalog.find(str(tmp_path / "elsewhere" / "a.xmp")).status == "found"


def test_find_strict(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    builder.add_image(tmp_path / "photos" / "a.xmp")
    with LightroomCatalog.open(str(builder.folder), strict=True) as catalog:
        assert catalog.find(str(tmp_path / "photos" / "a.xmp")).status == "found"
        assert catalog.find(str(tmp_path / "elsewhere" / "a.xmp")).status == "not_found"


def test_find_strict_picks_matching_folder(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    # not strict: two images with the same name, strict: only the one in the folder
    builder.add_image(tmp_path / "one" / "a.xmp", City="One")
    builder.add_image(tmp_path / "two" / "a.xmp", City="Two")
    with LightroomCatalog.open(str(builder.folder), strict=True) as catalog:
        result = catalog.find(str(tmp_path / "two" / "a.xmp"))
    assert result.status == "found"
    assert result.row is not None
    assert result.row["City"] == "Two"


def test_find_strict_path_forms(
    builder: LightroomCatalogBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # relative, "//", "./", "../" and symlinks are resolved to the real folder
    builder.add_image(tmp_path / "photos" / "a.xmp")
    (tmp_path / "link").symlink_to(tmp_path / "photos")
    (tmp_path / "other").mkdir()
    monkeypatch.chdir(tmp_path)
    with LightroomCatalog.open(str(builder.folder), strict=True) as catalog:
        for path in ("photos/a.xmp", "./photos//a.xmp", "other/../photos/a.xmp", "link/a.xmp"):
            assert catalog.find(path).status == "found", path


# MARK: find, decomposed (NFD) names
UnicodeForm = Literal["NFC", "NFD"]
NFC: UnicodeForm = "NFC"
NFD: UnicodeForm = "NFD"


@pytest.mark.parametrize(("catalog_form", "file_form"), [(NFC, NFD), (NFD, NFC), (NFC, NFC), (NFD, NFD)])
def test_find_name_any_unicode_form(
    builder: LightroomCatalogBuilder, tmp_path: Path, catalog_form: UnicodeForm, file_form: UnicodeForm
) -> None:
    builder.add_image(tmp_path / "photos" / unicodedata.normalize(catalog_form, "Zürich Café.xmp"), City="Osaka")
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        result = catalog.find(str(tmp_path / "photos" / unicodedata.normalize(file_form, "Zürich Café.xmp")))
    assert result.status == "found"


@pytest.mark.parametrize(("catalog_form", "file_form"), [(NFC, NFD), (NFD, NFC)])
def test_find_strict_folder_any_unicode_form(
    builder: LightroomCatalogBuilder, tmp_path: Path, catalog_form: UnicodeForm, file_form: UnicodeForm
) -> None:
    builder.add_image(tmp_path / unicodedata.normalize(catalog_form, "Zürich") / "a.xmp", City="Osaka")
    with LightroomCatalog.open(str(builder.folder), strict=True) as catalog:
        assert catalog.find(str(tmp_path / unicodedata.normalize(file_form, "Zürich") / "a.xmp")).status == "found"
        assert catalog.find(str(tmp_path / "Zurich" / "a.xmp")).status == "not_found"


def test_find_both_forms_in_catalog(builder: LightroomCatalogBuilder, tmp_path: Path) -> None:
    # the same visible name twice in the catalog (in two folders), once NFC, once NFD
    builder.add_image(tmp_path / "one" / unicodedata.normalize(NFC, "ü.xmp"))
    builder.add_image(tmp_path / "two" / unicodedata.normalize(NFD, "ü.xmp"))
    with LightroomCatalog.open(str(builder.folder)) as catalog:
        assert catalog.find(str(tmp_path / "x" / "ü.xmp")).status == "many_found"
    with LightroomCatalog.open(str(builder.folder), strict=True) as catalog:
        result = catalog.find(str(tmp_path / "two" / unicodedata.normalize(NFC, "ü.xmp")))
    assert result.status == "found"
    assert result.row is not None
    assert result.row["pathFromRoot"] == "two/"


# MARK: merge_lightroom_data
def test_merge_fills_empty_fields() -> None:
    row = make_row(gpsLatitude=-33.85, gpsLongitude=151.21, City="Sydney", Country="Australia", CountryCode="AU")
    merged, location_keys = merge_lightroom_data(EMPTY_DATA_SET, row)
    assert merged == {
        "GPSLatitude": "33,51.0S",
        "GPSLongitude": "151,12.6E",
        "Location": "",
        "City": "Sydney",
        "State": "",
        "Country": "Australia",
        "CountryCode": "AU",
    }
    # only location keys, not GPS
    assert location_keys == {"City", "Country", "CountryCode"}


def test_merge_keeps_existing_values() -> None:
    data_set = {**EMPTY_DATA_SET, "GPSLatitude": "35,30.0N", "City": "Kyoto"}
    row = make_row(gpsLatitude=1.0, gpsLongitude=2.0, City="Osaka", State="Osaka")
    merged, location_keys = merge_lightroom_data(data_set, row)
    assert merged["GPSLatitude"] == "35,30.0N"
    assert merged["GPSLongitude"] == "2,0.0E"
    assert merged["City"] == "Kyoto"
    assert merged["State"] == "Osaka"
    assert location_keys == {"State"}


def test_merge_replace_keys() -> None:
    # overwrite: the set fields in replace_keys are replaced, the others kept
    data_set = {**EMPTY_DATA_SET, "City": "Kyoto", "State": "Kyoto", "Country": "Nippon"}
    row = make_row(City="Osaka", State="Osaka", Country="Japan", Location="Namba")
    merged, location_keys = merge_lightroom_data(data_set, row, replace_keys={"City", "Country"})
    assert merged["City"] == "Osaka"
    assert merged["Country"] == "Japan"
    assert merged["State"] == "Kyoto"
    assert merged["Location"] == "Namba"
    assert location_keys == {"City", "Country", "Location"}


def test_merge_replace_same_value_is_lightroom_key() -> None:
    # the Lightroom value is the same as the XMP value: still set from Lightroom (no lookup for it)
    data_set = {**EMPTY_DATA_SET, "City": "Osaka"}
    merged, location_keys = merge_lightroom_data(data_set, make_row(City="Osaka"), replace_keys={"City"})
    assert merged["City"] == "Osaka"
    assert location_keys == {"City"}


def test_merge_replace_empty_lightroom_value_keeps_xmp() -> None:
    data_set = {**EMPTY_DATA_SET, "City": "Kyoto"}
    merged, location_keys = merge_lightroom_data(data_set, make_row(City=""), replace_keys={"City"})
    assert merged["City"] == "Kyoto"
    assert location_keys == set()


def test_merge_replace_keys_never_gps() -> None:
    data_set = {**EMPTY_DATA_SET, "GPSLatitude": "35,30.0N", "GPSLongitude": "139,30.0E"}
    row = make_row(gpsLatitude=1.0, gpsLongitude=2.0)
    merged, _ = merge_lightroom_data(data_set, row, replace_keys={"GPSLatitude", "GPSLongitude"})
    assert merged["GPSLatitude"] == "35,30.0N"
    assert merged["GPSLongitude"] == "139,30.0E"


def test_merge_empty_row() -> None:
    assert merge_lightroom_data(EMPTY_DATA_SET, make_row()) == (EMPTY_DATA_SET, set())


# MARK: Lightroom GPS
@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        (35.5, 139.5, (35.5, 139.5)),
        (-33.85, 151.21, (-33.85, 151.21)),
        # 0.0 is a valid coordinate: equator, prime meridian
        (0.0, 32.5, (0.0, 32.5)),
        (51.48, 0.0, (51.48, 0.0)),
        (0.0, -78.5, (0.0, -78.5)),
        # integer values from the catalog
        (0, 32, (0.0, 32.0)),
        # not set (NULL), also a half pair
        (None, None, None),
        (None, 139.5, None),
        (35.5, None, None),
        (None, 0.0, None),
        # both 0.0: placeholder for missing GPS data ("Null Island")
        (0.0, 0.0, None),
        (0, 0, None),
    ],
)
def test_lightroom_gps(latitude: float | None, longitude: float | None, expected: tuple[float, float] | None) -> None:
    result = lightroom_gps(make_row(gpsLatitude=latitude, gpsLongitude=longitude))
    assert result == expected
    if result is not None:
        assert all(isinstance(value, float) for value in result)


def test_merge_gps_equator() -> None:
    merged, _ = merge_lightroom_data(EMPTY_DATA_SET, make_row(gpsLatitude=0.0, gpsLongitude=32.5))
    assert merged["GPSLatitude"] == "0,0.0N"
    assert merged["GPSLongitude"] == "32,30.0E"


def test_merge_gps_prime_meridian() -> None:
    merged, _ = merge_lightroom_data(EMPTY_DATA_SET, make_row(gpsLatitude=51.48, gpsLongitude=0.0))
    assert merged["GPSLatitude"] == "51,28.8N"
    assert merged["GPSLongitude"] == "0,0.0E"


def test_merge_gps_null_island_not_used() -> None:
    merged, _ = merge_lightroom_data(EMPTY_DATA_SET, make_row(gpsLatitude=0.0, gpsLongitude=0.0))
    assert merged["GPSLatitude"] == ""
    assert merged["GPSLongitude"] == ""


@pytest.mark.parametrize(("latitude", "longitude"), [(None, 32.5), (35.5, None)])
def test_merge_gps_half_pair_not_used(latitude: float | None, longitude: float | None) -> None:
    # the XMP never gets only half of the coordinates from Lightroom
    merged, _ = merge_lightroom_data(EMPTY_DATA_SET, make_row(gpsLatitude=latitude, gpsLongitude=longitude))
    assert merged["GPSLatitude"] == ""
    assert merged["GPSLongitude"] == ""


def test_merge_gps_fills_missing_xmp_half() -> None:
    # the XMP has only a latitude: the missing longitude is filled, the latitude is kept
    data_set = {**EMPTY_DATA_SET, "GPSLatitude": "35,30.0N"}
    merged, _ = merge_lightroom_data(data_set, make_row(gpsLatitude=1.0, gpsLongitude=139.5))
    assert merged["GPSLatitude"] == "35,30.0N"
    assert merged["GPSLongitude"] == "139,30.0E"


def test_merge_empty_string_not_used() -> None:
    merged, location_keys = merge_lightroom_data(EMPTY_DATA_SET, make_row(City=""))
    assert merged["City"] == ""
    assert location_keys == set()


def test_merge_returns_new_data_set() -> None:
    data_set = dict(EMPTY_DATA_SET)
    merge_lightroom_data(data_set, make_row(City="Osaka"), replace_keys={"City"})
    assert data_set == EMPTY_DATA_SET


def test_merge_debug_output(capsys: pytest.CaptureFixture[str]) -> None:
    merge_lightroom_data(EMPTY_DATA_SET, make_row(City="Osaka", gpsLatitude=1.0), debug=True)
    # only location keys are printed
    assert capsys.readouterr().out == "### -> LR: City => Osaka\n"


def test_merge_no_output_without_debug(capsys: pytest.CaptureFixture[str]) -> None:
    merge_lightroom_data(EMPTY_DATA_SET, make_row(City="Osaka"))
    assert capsys.readouterr().out == ""


# __END__
