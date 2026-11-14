"""
unit tests for reverse_geolocate.utils.function_collection
(only the parts that need no files and no mocking)
"""

from argparse import Namespace
from pathlib import Path

import pytest

from reverse_geolocate.utils.function_collection import (
    check_overwrite,
    file_sort_number,
    get_display_path,
    is_path_excluded,
    normalize_exclude_paths,
    normalize_path,
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
        # case insensitive
        ("photo.BK.3.XMP", 3),
        ("photo.BK.4.Xmp", 4),
        ("photo.bk.5.xmp", 5),
        ("photo.Bk.6.XMP", 6),
        ("photo.XMP", 0),
        # number must be directly before the extension
        ("photo.BK.3.xmp.tmp", 0),
    ],
)
def test_file_sort_number(file: str, expected: int) -> None:
    assert file_sort_number(file) == expected


def test_file_sort_number_sorting() -> None:
    files = ["a.BK.10.xmp", "a.xmp", "a.BK.2.xmp", "a.BK.1.xmp"]
    assert sorted(files, key=file_sort_number) == ["a.xmp", "a.BK.1.xmp", "a.BK.2.xmp", "a.BK.10.xmp"]


def test_file_sort_number_sorting_mixed_case() -> None:
    files = ["a.BK.3.XMP", "a.XMP", "a.bk.2.xmp", "a.BK.1.Xmp"]
    assert sorted(files, key=file_sort_number) == ["a.XMP", "a.BK.1.Xmp", "a.bk.2.xmp", "a.BK.3.XMP"]


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


# MARK: normalize_path
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/a/b", "/a/b"),
        ("/a/b/", "/a/b"),
        ("/a//b", "/a/b"),
        ("/a/./b", "/a/b"),
        ("/a/x/../b", "/a/b"),
        ("/", "/"),
        (Path("/a/b/"), "/a/b"),
    ],
)
def test_normalize_path(path: str | Path, expected: str) -> None:
    # the paths do not need to exist
    assert normalize_path(path) == Path(expected)


def test_normalize_path_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    assert normalize_path("a/b") == Path("/a/b")
    assert normalize_path("./a/../c") == Path("/c")


def test_normalize_path_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "link").symlink_to(target)
    assert normalize_path(tmp_path / "link" / "a.xmp") == normalize_path(target / "a.xmp")


# MARK: normalize_exclude_paths
def test_normalize_exclude_paths() -> None:
    assert normalize_exclude_paths(["/a/b/", "/a//c", "/a/./d", "/a/x/../e", "/a/b"]) == {
        Path("/a/b"),
        Path("/a/c"),
        Path("/a/d"),
        Path("/a/e"),
    }


def test_normalize_exclude_paths_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    assert normalize_exclude_paths(["a/b", "./c"]) == {Path("/a/b"), Path("/c")}


def test_normalize_exclude_paths_empty() -> None:
    assert normalize_exclude_paths([]) == set()


# MARK: is_path_excluded
EXCLUDES = normalize_exclude_paths(["/photos/excluded", "/photos/single.xmp"])


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # the excluded folder itself, with any trailing separator
        ("/photos/excluded", True),
        ("/photos/excluded/", True),
        # everything inside, any depth
        ("/photos/excluded/a.xmp", True),
        ("/photos/excluded/sub", True),
        ("/photos/excluded/sub/deeper/b.xmp", True),
        # excluded file
        ("/photos/single.xmp", True),
        # not normalized paths
        ("/photos//excluded/a.xmp", True),
        ("/photos/other/../excluded/a.xmp", True),
        ("/photos/./single.xmp", True),
        # only whole names match
        ("/photos/excluded2", False),
        ("/photos/excluded.old/a.xmp", False),
        ("/photos/single.xmp.bak", False),
        ("/photos/single", False),
        # parent and siblings
        ("/photos", False),
        ("/photos/other/a.xmp", False),
        ("/", False),
    ],
)
def test_is_path_excluded(path: str, expected: bool) -> None:
    assert is_path_excluded(path, EXCLUDES) is expected


def test_is_path_excluded_no_excludes() -> None:
    assert is_path_excluded("/photos/a.xmp", set()) is False


def test_is_path_excluded_root() -> None:
    # excluding the root folder excludes everything
    excludes = normalize_exclude_paths(["/"])
    assert is_path_excluded("/", excludes) is True
    assert is_path_excluded("/photos/a.xmp", excludes) is True


def test_is_path_excluded_path_object() -> None:
    assert is_path_excluded(Path("/photos/excluded/a.xmp"), EXCLUDES) is True


def test_is_path_excluded_symlink(tmp_path: Path) -> None:
    # a symlink into an excluded folder is excluded, the link target counts
    excluded = tmp_path / "excluded"
    excluded.mkdir()
    (tmp_path / "link").symlink_to(excluded)
    excludes = normalize_exclude_paths([str(excluded)])
    assert is_path_excluded(tmp_path / "link" / "a.xmp", excludes) is True


def test_is_path_excluded_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    assert is_path_excluded("photos/excluded/a.xmp", EXCLUDES) is True
    assert is_path_excluded("photos/a.xmp", EXCLUDES) is False


# MARK: get_display_path
# a path that does not exist and has no symlinks (on macOS /home and /tmp are symlinks)
BASE = normalize_path("/display_base/user/photos")


@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        # inside the base folder: relative
        ("/display_base/user/photos/a.xmp", "a.xmp"),
        ("/display_base/user/photos/2026/11/a.xmp", "2026/11/a.xmp"),
        ("/display_base/user/photos//2026/./a.xmp", "2026/a.xmp"),
        ("/display_base/user/other/../photos/a.xmp", "a.xmp"),
        # outside: unchanged as given
        ("/display_base/user/a.xmp", "/display_base/user/a.xmp"),
        ("/display_base/user/photos2/a.xmp", "/display_base/user/photos2/a.xmp"),
        ("/other/a.xmp", "/other/a.xmp"),
        ("/display_base/user/./a.xmp", "/display_base/user/./a.xmp"),
    ],
)
def test_get_display_path(file_path: str, expected: str) -> None:
    assert get_display_path(file_path, BASE) == expected


def test_get_display_path_relative_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir("/")
    assert get_display_path("display_base/user/photos/a.xmp", BASE) == "a.xmp"
    assert get_display_path("display_base/user/a.xmp", BASE) == "display_base/user/a.xmp"


def test_get_display_path_root_base() -> None:
    assert get_display_path("/display_base/user/a.xmp", Path("/")) == "display_base/user/a.xmp"


def test_get_display_path_symlink(tmp_path: Path) -> None:
    # the base is normalized (symlinks resolved), the file is normalized for the check
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    base = normalize_path(tmp_path / "real")
    assert get_display_path(str(tmp_path / "link" / "a.xmp"), base) == "a.xmp"


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
