"""
integration tests for main() with decomposed (NFD) file and folder names
names with accents can be stored decomposed (NFD, "u" + combining "¨") or composed (NFC, "ü"),
macOS opens a file with both forms, as strings they are different
"""

import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from helpers.lightroom_catalog_builder import LightroomCatalogBuilder
from integration_helpers import FakeLookup, RunResult, read_xmp, write_xmp

from reverse_geolocate.utils.string_helpers import string_len_cjk

Run = Callable[..., RunResult]
UnicodeForm = Literal["NFC", "NFD"]

NAME = "Zürich Café"
NFC_NAME = unicodedata.normalize("NFC", NAME)
NFD_NAME = unicodedata.normalize("NFD", NAME)
LIGHTROOM_FIELDS = {"Location": "Namba", "City": "Osaka", "State": "Osaka", "Country": "Japan", "CountryCode": "JP"}


def form(name: str, unicode_form: UnicodeForm) -> str:
    return unicodedata.normalize(unicode_form, name)


@pytest.fixture
def nfd_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """src folder with a sub folder and a file stored decomposed (NFD), working folder is tmp_path"""
    write_xmp(tmp_path / "src" / NFD_NAME / f"{NFD_NAME}.xmp")
    write_xmp(tmp_path / "src" / "other" / "b.xmp")
    monkeypatch.chdir(tmp_path)
    return tmp_path / "src"


# MARK: file collection
def test_nfd_names_stored(nfd_folder: Path) -> None:
    # the test setup: the names on disk are decomposed
    assert next(path.name for path in nfd_folder.iterdir() if "rich" in path.name) == NFD_NAME


@pytest.mark.parametrize("exclude", [f"src/{NFC_NAME}", f"src/{NFD_NAME}", f"src/{NFC_NAME}/{NFC_NAME}.xmp"])
def test_exclude_any_form(run_main: Run, nfd_folder: Path, exclude: str) -> None:
    result = run_main("-r", "--debug", "-i", "src", "-x", exclude)
    assert result.work_files() == ["src/other/b.xmp"]


def test_duplicate_any_form(run_main: Run, nfd_folder: Path) -> None:
    # given composed, found decomposed in the folder: processed only once
    result = run_main("-r", "--debug", "-i", f"src/{NFC_NAME}/{NFC_NAME}.xmp", "src")
    assert len(result.work_files()) == 2
    assert result.work_files()[0] == f"src/{NFC_NAME}/{NFC_NAME}.xmp"


# MARK: Lightroom
@pytest.mark.parametrize(("catalog_form", "argument_form"), [("NFC", "NFD"), ("NFD", "NFC"), ("NFC", "NFC")])
@pytest.mark.parametrize("strict", [False, True])
def test_lightroom_any_form(
    run_main: Run,
    tmp_path: Path,
    lookup: FakeLookup,
    monkeypatch: pytest.MonkeyPatch,
    catalog_form: UnicodeForm,
    argument_form: UnicodeForm,
    strict: bool,
) -> None:
    # file stored decomposed, catalog and command line argument in either form
    file = write_xmp(tmp_path / "src" / NFD_NAME / f"{NFD_NAME}.xmp", GPSLatitude="", GPSLongitude="")
    catalog = LightroomCatalogBuilder(tmp_path / "lightroom")
    catalog.add_image(
        tmp_path / "src" / form(NAME, catalog_form) / f"{form(NAME, catalog_form)}.xmp",
        gps_latitude=35.5,
        gps_longitude=139.5,
        **LIGHTROOM_FIELDS,
    )
    monkeypatch.chdir(tmp_path)
    result = run_main("-i", f"src/{form(NAME, argument_form)}", "-l", catalog.folder, *(["-s"] if strict else []))
    assert result.stat("GeoLocation from Lightroom") == 1
    assert result.stat("No Lightroom data found") == 0
    assert lookup.calls == []
    assert read_xmp(file) == {"GPSLatitude": "35,30.0N", "GPSLongitude": "139,30.0E", **LIGHTROOM_FIELDS}


# MARK: output
def test_read_only_columns_aligned(run_main: Run, nfd_folder: Path) -> None:
    write_xmp(nfd_folder / "c.xmp", City=NFD_NAME, Location=form("Ångström Straße", "NFD"))
    result = run_main("-r", "-i", "src")
    lines = [line for line in result.lines if " | " in line]
    # title and data lines have the same visible width: measured independent of string_len_cjk,
    # all characters here have a composed form, so after NFC each visible character is one code point
    assert len({len(unicodedata.normalize("NFC", line)) for line in lines}) == 1
    assert len({string_len_cjk(line) for line in lines}) == 1
    # the name is shown complete (not cut because of the combining characters)
    assert any(NFD_NAME in line for line in lines)


def test_display_path_relative(run_main: Run, nfd_folder: Path) -> None:
    # decomposed path inside the call folder: shown relative (in NFC)
    result = run_main("-i", "src", "--test")
    statuses = [line for line in result.lines if line.endswith(": [UPDATED]")]
    assert f"src/{NFC_NAME}/{NFC_NAME}.xmp: [UPDATED]" in statuses


# __END__
