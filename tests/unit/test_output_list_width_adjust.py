"""
unit tests for reverse_geolocate.utils.function_collection.output_list_width_adjust
the terminal size is replaced by a fixed size (the compact view is tested in test_function_collection.py)
"""

import os
from argparse import Namespace
from collections.abc import Callable

import pytest

from reverse_geolocate.utils import function_collection
from reverse_geolocate.utils.function_collection import output_list_width_adjust

DEFAULT_LENGTH = {
    "filename": 35,
    "latitude": 18,
    "longitude": 18,
    "code": 4,
    "country": 15,
    "state": 18,
    "city": 20,
    "location": 25,
    "path": 40,
}
# columns are only resized if they stay above this width
RESIZE_WIDTH_MIN = 4
WARNING = "[!!!] Screen layout might be skewed. Increase Terminal width"
# width of the smallest possible layout
SMALLEST_LAYOUT = 95
# smallest terminal the layout fits into (one under the terminal width)
MIN_FIT_COLUMNS = SMALLEST_LAYOUT + 1
# largest terminal the layout can grow to
MAX_FILL_COLUMNS = 450


def total_width(format_length: dict[str, int]) -> int:
    """same width calculation as in output_list_width_adjust (matches the header separator line)"""
    return sum(format_length.values()) + (len(format_length) - 1) * 3 + 2


DEFAULT_TOTAL = total_width(DEFAULT_LENGTH)


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """returns a setter for the terminal width"""

    def set_columns(columns: int) -> None:
        monkeypatch.setattr(function_collection, "get_terminal_size", lambda: os.terminal_size((columns, 24)))

    return set_columns


def adjust(no_autoadjust: bool = False) -> dict[str, int]:
    return output_list_width_adjust(Namespace(compact_view=False, no_autoadjust=no_autoadjust))


def test_default_total() -> None:
    assert DEFAULT_TOTAL == 219


# MARK: auto adjust
def test_default_fits_unchanged(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str]) -> None:
    # default layout is 219 wide, with 220 columns it is already one under
    terminal(DEFAULT_TOTAL + 1)
    assert adjust() == DEFAULT_LENGTH
    assert capsys.readouterr().out == ""


def test_grow(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str]) -> None:
    terminal(300)
    format_length = adjust()
    assert total_width(format_length) == 299
    for key, length in DEFAULT_LENGTH.items():
        assert format_length[key] >= length, key
    # only the text columns grow
    for key in ("latitude", "longitude", "code"):
        assert format_length[key] == DEFAULT_LENGTH[key], key
    assert format_length["path"] > DEFAULT_LENGTH["path"]
    assert capsys.readouterr().out == ""


def test_shrink(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str]) -> None:
    terminal(150)
    format_length = adjust()
    assert total_width(format_length) == 149
    for key, length in DEFAULT_LENGTH.items():
        assert format_length[key] <= length, key
    # the code column is never resized
    assert format_length["code"] == DEFAULT_LENGTH["code"]
    # latitude/longitude are shrunk first
    assert format_length["latitude"] < DEFAULT_LENGTH["latitude"]
    assert capsys.readouterr().out == ""


def test_exact_default_width_shrinks(terminal: Callable[[int], None]) -> None:
    # 219 columns: the layout would touch the edge, it is shrunk to one under
    terminal(DEFAULT_TOTAL)
    assert total_width(adjust()) == DEFAULT_TOTAL - 1


def test_common_width_120(terminal: Callable[[int], None]) -> None:
    terminal(120)
    assert adjust() == {
        "filename": 19,
        "latitude": 6,
        "longitude": 6,
        "code": 4,
        "country": 9,
        "state": 10,
        "city": 11,
        "location": 14,
        "path": 14,
    }


@pytest.mark.parametrize("columns", range(MIN_FIT_COLUMNS, MAX_FILL_COLUMNS + 1))
def test_fills_terminal_one_under(
    terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str], columns: int
) -> None:
    terminal(columns)
    assert total_width(adjust()) == columns - 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("columns", [40, 60, 80, SMALLEST_LAYOUT - 1])
def test_too_small_warns(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str], columns: int) -> None:
    terminal(columns)
    format_length = adjust()
    assert total_width(format_length) > columns
    assert capsys.readouterr().out == f"{WARNING}\n"


def test_smallest_layout_touching_edge_warns(
    terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str]
) -> None:
    # the smallest layout is exactly as wide as the terminal, not one under: warn
    terminal(SMALLEST_LAYOUT)
    assert total_width(adjust()) == SMALLEST_LAYOUT
    assert capsys.readouterr().out == f"{WARNING}\n"


def test_too_small_same_result(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str]) -> None:
    # below the smallest layout all terminal sizes give the same, smallest, layout
    terminal(40)
    smallest = adjust()
    terminal(SMALLEST_LAYOUT)
    assert adjust() == smallest
    assert total_width(smallest) == SMALLEST_LAYOUT
    capsys.readouterr()


@pytest.mark.parametrize("columns", [MAX_FILL_COLUMNS + 1, 600, 1000])
def test_very_wide_stops_growing(
    terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str], columns: int
) -> None:
    terminal(columns)
    format_length = adjust()
    assert total_width(format_length) < columns - 1
    terminal(MAX_FILL_COLUMNS + 1)
    # growing stops at the same maximum layout
    assert adjust() == format_length
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("columns", range(20, 701, 7))
def test_invariants(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str], columns: int) -> None:
    terminal(columns)
    format_length = adjust()
    assert format_length.keys() == DEFAULT_LENGTH.keys()
    assert format_length["code"] == DEFAULT_LENGTH["code"]
    # resized columns never go to or below the minimum width
    for key, length in format_length.items():
        if key != "code":
            assert length > RESIZE_WIDTH_MIN, key
    # always at least one under the terminal width, unless the warning is printed
    if total_width(format_length) >= columns:
        assert WARNING in capsys.readouterr().out
    else:
        assert capsys.readouterr().out == ""


def test_returns_new_dict_each_call(terminal: Callable[[int], None]) -> None:
    terminal(150)
    first = adjust()
    first["path"] = 1
    assert adjust()["path"] != 1


# MARK: no auto adjust
@pytest.mark.parametrize("columns", [DEFAULT_TOTAL + 1, 300, 1000])
def test_no_autoadjust_wide(terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str], columns: int) -> None:
    terminal(columns)
    assert adjust(no_autoadjust=True) == DEFAULT_LENGTH
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("columns", [40, 120, DEFAULT_TOTAL])
def test_no_autoadjust_narrow(
    terminal: Callable[[int], None], capsys: pytest.CaptureFixture[str], columns: int
) -> None:
    # default layout is kept, only the warning is printed (also if it would touch the edge)
    terminal(columns)
    assert adjust(no_autoadjust=True) == DEFAULT_LENGTH
    assert capsys.readouterr().out == f"{WARNING}\n"


# MARK: compact view
def test_compact_does_not_read_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> os.terminal_size:
        raise AssertionError("terminal size must not be read in compact view")

    monkeypatch.setattr(function_collection, "get_terminal_size", fail)
    output_list_width_adjust(Namespace(compact_view=True, no_autoadjust=False))


# __END__
