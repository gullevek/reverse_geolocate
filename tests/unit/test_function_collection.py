"""
unit tests for reverse_geolocate.utils.function_collection
(only the parts that need no files and no mocking)
"""

from argparse import Namespace

import pytest

from reverse_geolocate.utils.function_collection import (
    check_overwrite,
    file_sort_number,
    output_list_width_adjust,
)

NO_DEBUG = Namespace(debug=False)


# MARK: file_sort_number
@pytest.mark.parametrize(
    ("file", "expected"),
    [
        ("photo.xmp", 0),
        ("photo.BK.1.xmp", 1),
        ("photo.BK.12.xmp", 12),
        ("/some/path/photo.BK.3.xmp", 3),
        ("photo.BK.xmp", 0),
        ("photo.BK.x.xmp", 0),
        # case sensitive
        ("photo.BK.3.XMP", 0),
        ("photo.bk.3.xmp", 0),
        # number must be directly before the extension
        ("photo.BK.3.xmp.tmp", 0),
    ],
)
def test_file_sort_number(file: str, expected: int) -> None:
    assert file_sort_number(file) == expected


def test_file_sort_number_sorting() -> None:
    files = ["a.BK.10.xmp", "a.xmp", "a.BK.2.xmp", "a.BK.1.xmp"]
    assert sorted(files, key=file_sort_number) == ["a.xmp", "a.BK.1.xmp", "a.BK.2.xmp", "a.BK.10.xmp"]


# MARK: check_overwrite
@pytest.mark.parametrize(
    ("data", "key", "field_controls", "expected"),
    [
        # 1) no field controls: write only if data is not set
        ("", "City", None, True),
        ("Tokyo", "City", None, False),
        ("", "City", [], True),
        ("Tokyo", "City", [], False),
        # 2) only overwrite: always write
        ("", "City", ["overwrite"], True),
        ("Tokyo", "City", ["overwrite"], True),
        # 3) only field keys: only those keys and only if not set
        ("", "City", ["city"], True),
        ("Tokyo", "City", ["city"], False),
        ("", "State", ["city"], False),
        ("", "State", ["city", "state"], True),
        # 4) field keys + overwrite: only those keys, set or not
        ("Tokyo", "City", ["city", "overwrite"], True),
        ("", "City", ["city", "overwrite"], True),
        ("Tokyo", "State", ["city", "overwrite"], False),
        ("", "State", ["city", "overwrite"], False),
        # key is compared case insensitive
        ("", "CountryCode", ["countrycode"], True),
        ("", "countrycode", ["countrycode"], True),
        # duplicate flags do not change the result
        ("Tokyo", "City", ["overwrite", "overwrite"], True),
        ("Tokyo", "City", ["city", "city"], False),
    ],
)
def test_check_overwrite(data: str, key: str, field_controls: list[str] | None, expected: bool) -> None:
    assert check_overwrite(data, key, field_controls, NO_DEBUG) is expected


def test_check_overwrite_no_output_without_debug(capsys: pytest.CaptureFixture[str]) -> None:
    check_overwrite("", "City", None, NO_DEBUG)
    assert capsys.readouterr().out == ""


def test_check_overwrite_debug_output(capsys: pytest.CaptureFixture[str]) -> None:
    check_overwrite("Tokyo", "City", ["state", "overwrite"], Namespace(debug=True))
    out = capsys.readouterr().out
    assert "Data set: YES" in out
    assert "Key: city" in out
    assert "Field Controls: ['state']" in out
    assert "Overwrite: OVERWRITE" in out
    assert "KEY NOT MATCHING" in out
    assert "OVERWRITE: False" in out


# MARK: output_list_width_adjust (compact view only, the others read the terminal size)
def test_output_list_width_adjust_compact() -> None:
    format_length = output_list_width_adjust(Namespace(compact_view=True, no_autoadjust=False))
    # all reduced by 40% (rounded up), code is kept
    assert format_length == {
        "filename": 21,
        "latitude": 11,
        "longitude": 11,
        "code": 4,
        "country": 9,
        "state": 11,
        "city": 12,
        "location": 15,
        "path": 24,
    }


def test_output_list_width_adjust_compact_ignores_no_autoadjust() -> None:
    compact = output_list_width_adjust(Namespace(compact_view=True, no_autoadjust=False))
    compact_no_adjust = output_list_width_adjust(Namespace(compact_view=True, no_autoadjust=True))
    assert compact == compact_no_adjust


# __END__
