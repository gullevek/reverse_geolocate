"""
integration tests for main() in read only mode (-r): list output, filters, paging
nothing must be written and no lookup must be done
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from integration_helpers import TERMINAL_COLUMNS, FakeLookup, RunResult, write_xmp

from reverse_geolocate.utils.string_helpers import string_len_cjk

Run = Callable[..., RunResult]
Snapshot = Callable[[Path], dict[Path, bytes]]

FULL = {"Location": "Jingumae", "City": "Shibuya", "State": "Tokyo", "Country": "Japan", "CountryCode": "JP"}


def page_headers(result: RunResult) -> list[str]:
    return [line for line in result.lines if line.startswith("> Page ")]


def table_lines(result: RunResult) -> list[str]:
    """title, separator and data lines of the list"""
    return [line for line in result.lines if " | " in line or (line.startswith("---") and "+" in line)]


# MARK: basic list
def test_sample_list(run_main: Run, sample_folder: Path) -> None:
    result = run_main("-r", "-i", sample_folder)
    assert result.exit_code is None
    assert page_headers(result) == ["> Page 1/1"]
    rows = result.table_rows()
    assert [row[0] for row in rows] == [path.name for path in sorted(sample_folder.glob("*.xmp"))]
    for row in rows:
        # filename | latitude | longitude | code | country | state | city | location | path
        assert len(row) == 9
        assert row[1].startswith("35.674362")
        assert row[2].startswith("139.73997")
        assert row[3:8] == ["", "", "", "", ""]
        assert row[8].endswith("samples")
    assert result.stat("XMP Files found") == 3
    assert result.stat("XMP Files listed") == 3


def test_location_data_shown(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **FULL)
    rows = run_main("-r", "-i", tmp_path / "src").table_rows()
    assert rows[0][3:8] == ["JP", "Japan", "Tokyo", "Shibuya", "Jingumae"]


def test_southern_western_coordinates(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", GPSLatitude="33,51.0S", GPSLongitude="151,12.6E")
    write_xmp(tmp_path / "src" / "b.xmp", GPSLatitude="40,42.8N", GPSLongitude="74,0.4W")
    rows = run_main("-r", "-i", tmp_path / "src").table_rows()
    assert rows[0][1:3] == ["-33.85", "151.21"]
    assert rows[1][1:3] == ["40.71333333333", "-74.0066666666"]


def test_values_not_carried_over_between_files(run_main: Run, tmp_path: Path) -> None:
    # the XMP object is reused for all files, data of one file must not show up in the next
    write_xmp(tmp_path / "src" / "a.xmp", **FULL)
    write_xmp(tmp_path / "src" / "b.xmp")
    rows = run_main("-r", "-i", tmp_path / "src").table_rows()
    assert rows[1][3:8] == ["", "", "", "", ""]


def test_missing_gps_shown_empty(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", GPSLatitude="", GPSLongitude="")
    result = run_main("-r", "-i", tmp_path / "src")
    assert result.exit_code is None
    assert result.table_rows()[0][1:3] == ["", ""]


def test_damaged_file_not_listed_and_continues(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    write_xmp(src / "1.xmp")
    (src / "2_broken.xmp").write_text("just text", encoding="UTF-8")
    (src / "3_binary.xmp").write_bytes(bytes(range(256)))
    write_xmp(src / "4.xmp")
    result = run_main("-r", "-i", src)
    assert result.exit_code is None
    # the damaged files get a message line, the other files are listed
    assert [row[0] for row in result.table_rows()] == ["1.xmp", "4.xmp"]
    messages = [line for line in result.lines if line.startswith("(!) Could not read XMP data")]
    assert len(messages) == 2
    assert messages[0].startswith("(!) Could not read XMP data (no valid XMP")
    assert messages[0].endswith(str(src / "2_broken.xmp"))
    assert messages[1].startswith("(!) Could not read XMP data (not a text file (UTF-8)):")
    assert result.stat("XMP Files found") == 4
    assert result.stat("XMP Files listed") == 2
    assert result.stat("XMP Files not readable") == 2
    assert result.lines[result.lines.index("Files that could not be read:") + 1] == (
        f"{src / '2_broken.xmp'}, {src / '3_binary.xmp'}"
    )


def test_no_unreadable_statistics_without_errors(run_main: Run, sample_folder: Path) -> None:
    result = run_main("-r", "-i", sample_folder)
    assert "XMP Files not readable" not in result.out
    assert "Files that could not be read:" not in result.out


def test_empty_folder(run_main: Run, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result = run_main("-r", "-i", tmp_path / "empty")
    assert page_headers(result) == ["> Page 1/1"]
    assert "[!!!] No files found" in result.out
    assert result.table_rows() == []
    assert result.stat("XMP Files found") == 0
    assert result.stat("XMP Files listed") == 0


def test_only_read_only_statistics(run_main: Run, sample_folder: Path) -> None:
    result = run_main("-r", "-i", sample_folder)
    assert "XMP Files listed" in result.out
    for name in ("Updated", "Skipped", "New GeoLocation from Map", "Failed reverse GeoLocate"):
        assert name not in result.out


# MARK: nothing written
def test_nothing_written(
    run_main: Run, tmp_path: Path, snapshot: Snapshot, lookup: FakeLookup, sample_folder: Path
) -> None:
    write_xmp(sample_folder / "no_gps.xmp", GPSLatitude="", GPSLongitude="")
    before = snapshot(sample_folder)
    run_main("-r", "-i", sample_folder)
    # same files (no backups added), same content
    assert snapshot(sample_folder) == before
    assert lookup.calls == []


# MARK: filters
@pytest.fixture
def mixed_folder(tmp_path: Path) -> Path:
    """complete, location missing, GPS missing, nothing set"""
    src = tmp_path / "src"
    write_xmp(src / "1_complete.xmp", **FULL)
    write_xmp(src / "2_no_city.xmp", **{**FULL, "City": ""})
    write_xmp(src / "3_no_gps.xmp", GPSLatitude="", GPSLongitude="", **FULL)
    write_xmp(src / "4_empty.xmp", GPSLatitude="", GPSLongitude="")
    return src


def listed(result: RunResult) -> list[str]:
    return [row[0] for row in result.table_rows()]


def test_no_filter(run_main: Run, mixed_folder: Path) -> None:
    result = run_main("-r", "-i", mixed_folder)
    assert listed(result) == ["1_complete.xmp", "2_no_city.xmp", "3_no_gps.xmp", "4_empty.xmp"]
    assert page_headers(result) == ["> Page 1/1"]


@pytest.mark.parametrize("flag", ["-u", "--unset-only"])
def test_unset_only(run_main: Run, mixed_folder: Path, flag: str) -> None:
    result = run_main("-r", flag, "-i", mixed_folder)
    # any empty field, GPS included
    assert listed(result) == ["2_no_city.xmp", "3_no_gps.xmp", "4_empty.xmp"]
    assert result.stat("XMP Files found") == 4
    assert result.stat("XMP Files listed") == 3
    # the page count is only a maximum with a filter
    assert page_headers(result) == ["> Page 1/1?"]


@pytest.mark.parametrize("flag", ["-p", "--unset-gps-only"])
def test_unset_gps_only(run_main: Run, mixed_folder: Path, flag: str) -> None:
    result = run_main("-r", flag, "-i", mixed_folder)
    assert listed(result) == ["3_no_gps.xmp", "4_empty.xmp"]
    assert result.stat("XMP Files listed") == 2
    assert page_headers(result) == ["> Page 1/1?"]


def test_unset_and_unset_gps_combined(run_main: Run, tmp_path: Path) -> None:
    # either filter matches
    src = tmp_path / "src"
    write_xmp(src / "1_complete.xmp", **FULL)
    write_xmp(src / "2_no_city.xmp", **{**FULL, "City": ""})
    write_xmp(src / "3_no_gps.xmp", GPSLatitude="", GPSLongitude="", **FULL)
    result = run_main("-r", "-u", "-p", "-i", src)
    assert listed(result) == ["2_no_city.xmp", "3_no_gps.xmp"]


def test_filter_nothing_found(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **FULL)
    result = run_main("-r", "-u", "-i", tmp_path / "src")
    assert result.table_rows() == []
    assert result.stat("XMP Files found") == 1
    assert result.stat("XMP Files listed") == 0


# MARK: layout
def test_compact_view(run_main: Run, sample_folder: Path) -> None:
    normal = run_main("-r", "-i", sample_folder)
    compact = run_main("-r", "-c", "-i", sample_folder)
    # compact latitude column is 11 wide
    assert compact.table_rows()[0][1] == "35.67436237"
    assert len(table_lines(compact)[0]) < len(table_lines(normal)[0])


@pytest.mark.parametrize("argv", [[], ["-c"], ["-a"]])
def test_columns_aligned(run_main: Run, tmp_path: Path, argv: list[str]) -> None:
    src = tmp_path / "写真フォルダ"
    write_xmp(src / "a.xmp", **FULL)
    write_xmp(
        src / "東京の写真.xmp", Location="神宮前", City="渋谷区", State="東京都", Country="日本", CountryCode="JP"
    )
    write_xmp(src / "c.xmp", Location="A very long location name that will not fit", Country="United Kingdom")
    result = run_main("-r", *argv, "-i", src)
    lines = table_lines(result)
    # title, separator, 3 data lines
    assert len(lines) == 5
    # all title/data lines have the same display width (the last column is padded)
    assert len({string_len_cjk(line) for line in [lines[0], *lines[2:]]}) == 1
    # separator positions match the column borders of the title line
    separator = lines[1]
    title = lines[0]
    assert [i for i, char in enumerate(separator) if char == "+"] == [
        i + 1 for i in range(len(title)) if title.startswith(" | ", i)
    ]


def test_fits_terminal_width(run_main: Run, sample_folder: Path) -> None:
    result = run_main("-r", "-i", sample_folder)
    for line in table_lines(result):
        assert string_len_cjk(line) < TERMINAL_COLUMNS


# MARK: paging
def test_pages(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    for index in range(51):
        write_xmp(src / f"{index:03}.xmp")
    result = run_main("-r", "-i", src)
    assert page_headers(result) == ["> Page 1/2", "> Page 2/2"]
    assert len(result.table_rows()) == 51
    # header block before the first and the 51st data line
    page_two = result.lines.index("> Page 2/2")
    assert result.lines[page_two + 3].lstrip().startswith("050.xmp")


def test_exactly_one_page(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    for index in range(50):
        write_xmp(src / f"{index:03}.xmp")
    assert page_headers(run_main("-r", "-i", src)) == ["> Page 1/1"]


def test_pages_with_filter(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    for index in range(60):
        # only every second file is unset
        write_xmp(src / f"{index:03}.xmp", **(FULL if index % 2 else {}))
    result = run_main("-r", "-u", "-i", src)
    # 30 listed, fits on one page, but the maximum is calculated from all files
    assert page_headers(result) == ["> Page 1/2?"]
    assert result.stat("XMP Files listed") == 30


# __END__
