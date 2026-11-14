"""
unit tests for reverse_geolocate.utils.read_only_output
"""

from typing import Any

import pytest

from reverse_geolocate.utils.read_only_output import ReadOnlyOutput
from reverse_geolocate.utils.string_helpers import string_len_cjk

FORMAT_LENGTH: dict[str, int] = {
    "filename": 12,
    "latitude": 8,
    "longitude": 9,
    "code": 4,
    "country": 8,
    "state": 8,
    "city": 8,
    "location": 8,
    "path": 12,
}
# same two pass layout as in main(): 1st format the {...len} widths, 2nd the data
LINE_TEMPLATE = (
    "{{filename:<{filenamelen}}}|"
    "{{latitude:>" + str(FORMAT_LENGTH["latitude"]) + "}}|"
    "{{longitude:>" + str(FORMAT_LENGTH["longitude"]) + "}}|"
    "{{code:<" + str(FORMAT_LENGTH["code"]) + "}}|"
    "{{country:<{countrylen}}}|"
    "{{state:<{statelen}}}|"
    "{{city:<{citylen}}}|"
    "{{location:<{locationlen}}}|"
    "{{path:<{pathlen}}}"
)
HEADER_TEMPLATE = "> Page {page_no}/{page_all}"


def make_output(max_pages: int = 3, header_print_line: int = 2) -> ReadOnlyOutput:
    return ReadOnlyOutput(HEADER_TEMPLATE, LINE_TEMPLATE, FORMAT_LENGTH, max_pages, header_print_line)


def make_data_set(**overrides: str) -> dict[str, Any]:
    data_set = {
        "GPSLatitude": "35,30.0N",
        "GPSLongitude": "139,30.0E",
        "Location": "Shibuya",
        "City": "Tokyo",
        "State": "Tokyo",
        "Country": "Japan",
        "CountryCode": "JP",
    }
    data_set.update(overrides)
    return data_set


def columns(line: str) -> list[str]:
    return line.rstrip("\n").split("|")


# MARK: init
def test_init() -> None:
    output = make_output(max_pages=5, header_print_line=10)
    assert output.page_all == 5
    assert output.header_print == 10
    assert output.page_no == 0
    assert output.lines == 0


@pytest.mark.parametrize("max_pages", [0, -1])
def test_init_page_all_at_least_one(max_pages: int) -> None:
    assert make_output(max_pages=max_pages).page_all == 1


# MARK: print_header
def test_print_header(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output(max_pages=3)
    output.lines = 5
    output.print_header()
    assert capsys.readouterr().out == "> Page 1/3\n"
    assert output.page_no == 1
    assert output.lines == 0
    output.print_header()
    assert capsys.readouterr().out == "> Page 2/3\n"


# MARK: next_line
def test_next_line_first_line_prints_header(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output()
    output.next_line()
    assert capsys.readouterr().out == "> Page 1/3\n"
    assert output.lines == 1


def test_next_line_repeats_header(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output(header_print_line=2)
    for _ in range(5):
        output.next_line()
    # header before line 1, 3 and 5
    assert capsys.readouterr().out == "> Page 1/3\n> Page 2/3\n> Page 3/3\n"
    assert output.page_no == 3
    assert output.lines == 1


def test_next_line_no_repeat(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output(header_print_line=0)
    for _ in range(100):
        output.next_line()
    assert capsys.readouterr().out == "> Page 1/3\n"
    assert output.lines == 100


def test_next_line_after_manual_header(capsys: pytest.CaptureFixture[str]) -> None:
    # main() prints the header first, then next_line must not print it again
    output = make_output(header_print_line=2)
    output.print_header()
    output.next_line()
    output.next_line()
    assert capsys.readouterr().out == "> Page 1/3\n"


# MARK: print_line
def test_print_line(capsys: pytest.CaptureFixture[str]) -> None:
    make_output().print_line("/photos/2026/a.xmp", make_data_set())
    cols = columns(capsys.readouterr().out)
    assert cols == [
        "a.xmp       ",
        "    35.5",
        "    139.5",
        " JP ",
        "Japan   ",
        "Tokyo   ",
        "Tokyo   ",
        "Shibuya ",
        "/photos/2026",
    ]


def test_print_line_negative_coordinates(capsys: pytest.CaptureFixture[str]) -> None:
    make_output().print_line("/a.xmp", make_data_set(GPSLatitude="35,30.0S", GPSLongitude="139,30.0W"))
    cols = columns(capsys.readouterr().out)
    assert cols[1] == "   -35.5"
    assert cols[2] == "   -139.5"


def test_print_line_coordinates_cut_from_right(capsys: pytest.CaptureFixture[str]) -> None:
    make_output().print_line("/a.xmp", make_data_set(GPSLatitude="35,40.4617426011N"))
    cols = columns(capsys.readouterr().out)
    assert cols[1] == "35.67436"
    assert len(cols[1]) == FORMAT_LENGTH["latitude"]


@pytest.mark.parametrize(("latitude", "longitude"), [("", ""), ("", "139,30.0E"), ("invalid", "")])
def test_print_line_missing_gps(capsys: pytest.CaptureFixture[str], latitude: str, longitude: str) -> None:
    make_output().print_line("/a.xmp", make_data_set(GPSLatitude=latitude, GPSLongitude=longitude))
    cols = columns(capsys.readouterr().out)
    if not longitude:
        assert cols[2] == " " * FORMAT_LENGTH["longitude"]
    assert cols[1] == " " * FORMAT_LENGTH["latitude"]


def test_print_line_empty_location_data(capsys: pytest.CaptureFixture[str]) -> None:
    data_set = make_data_set(Location="", City="", State="", Country="", CountryCode="")
    make_output().print_line("/a.xmp", data_set)
    cols = columns(capsys.readouterr().out)
    assert cols[3] == " " * 4
    for index, key in ((4, "country"), (5, "state"), (6, "city"), (7, "location")):
        assert cols[index] == " " * FORMAT_LENGTH[key]


def test_print_line_country_code_only_two_chars(capsys: pytest.CaptureFixture[str]) -> None:
    make_output().print_line("/a.xmp", make_data_set(CountryCode="JPN"))
    assert columns(capsys.readouterr().out)[3] == " JP "


def test_print_line_long_values_shortened(capsys: pytest.CaptureFixture[str]) -> None:
    make_output().print_line(
        "/very/long/folder/name/a_very_long_file_name.xmp",
        make_data_set(Country="United Kingdom", Location="Westminster Abbey"),
    )
    cols = columns(capsys.readouterr().out)
    # file name and path are shortened from the left
    assert cols[0] == ".. _name.xmp"
    assert cols[8] == ".. lder/name"
    # strings are shortened from the right
    assert cols[4] == "United.."
    assert cols[7] == "Westmi.."


def test_print_line_cjk_columns_aligned(capsys: pytest.CaptureFixture[str]) -> None:
    make_output().print_line(
        "/写真/東京フォルダ/写真.xmp",
        make_data_set(Country="日本", State="東京都", City="渋谷区神南一丁目", Location="渋谷"),
    )
    cols = columns(capsys.readouterr().out)
    # every column has the exact display width, also with double width characters
    for col, key in zip(
        cols,
        ["filename", "latitude", "longitude", "code", "country", "state", "city", "location", "path"],
        strict=True,
    ):
        assert string_len_cjk(col) == FORMAT_LENGTH[key], f"{key}: '{col}'"


def test_print_line_does_not_change_counters(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output()
    output.print_line("/a.xmp", make_data_set())
    capsys.readouterr()
    assert output.page_no == 0
    assert output.lines == 0


# __END__
