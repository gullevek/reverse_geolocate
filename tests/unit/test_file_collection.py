"""
unit tests for reverse_geolocate.utils.file_collection
(more cases through main() in tests/integration/test_main_file_collection.py)
"""

from pathlib import Path

import pytest

from reverse_geolocate.utils.file_collection import collect_work_files, is_xmp_work_file


def touch(folder: Path, *names: str) -> list[str]:
    paths: list[str] = []
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        paths.append(str(path))
    return paths


# MARK: is_xmp_work_file
@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("a.xmp", True),
        ("a.XMP", True),
        ("a.Xmp", True),
        ("2026.11.10_a.xmp", True),
        ("a.BK.1.xmp", False),
        ("a.BK.1.XMP", False),
        # the backup marker is upper case only
        ("a.bk.1.xmp", True),
        ("a.jpg", False),
        ("a.xmp.bak", False),
        ("xmp", False),
        (".xmp", True),
    ],
)
def test_is_xmp_work_file(file_name: str, expected: bool) -> None:
    assert is_xmp_work_file(file_name) is expected


# MARK: collect_work_files
def test_collect_folder(tmp_path: Path) -> None:
    files = touch(tmp_path, "b.xmp", "a.xmp", "a.BK.1.xmp", "a.jpg")
    assert collect_work_files([str(tmp_path)], []) == [files[1], files[0]]


def test_collect_sub_folders_sorted(tmp_path: Path) -> None:
    files = touch(tmp_path, "z.xmp", "b/2.xmp", "a/1.xmp", "a/x/3.xmp")
    # files of the folder first, then the sub folders by name (depth first)
    assert collect_work_files([str(tmp_path)], []) == [files[0], files[2], files[3], files[1]]


def test_collect_single_file_any_name(tmp_path: Path) -> None:
    # a file given directly is always used
    files = touch(tmp_path, "a.BK.1.xmp", "notes.txt")
    assert collect_work_files(files, []) == files


def test_collect_excludes(tmp_path: Path) -> None:
    files = touch(tmp_path, "a.xmp", "b.xmp", "ex/c.xmp", "ex/deep/d.xmp", "ex2/e.xmp")
    work_files = collect_work_files([str(tmp_path)], [files[1], str(tmp_path / "ex")])
    assert work_files == [files[0], files[4]]


def test_collect_excluded_source(tmp_path: Path) -> None:
    touch(tmp_path, "src/a.xmp")
    assert collect_work_files([f"{tmp_path / 'src'}/"], [str(tmp_path / "src")]) == []


def test_collect_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = touch(tmp_path, "src/a.xmp")
    (tmp_path / "link").symlink_to(tmp_path / "src")
    monkeypatch.chdir(tmp_path)
    work_files = collect_work_files(["src/a.xmp", files[0], "src", "./src/", "link"], [])
    # first form is kept
    assert work_files == ["src/a.xmp"]


def test_collect_nothing(tmp_path: Path) -> None:
    assert collect_work_files([str(tmp_path)], []) == []
    assert collect_work_files([], []) == []


# __END__
