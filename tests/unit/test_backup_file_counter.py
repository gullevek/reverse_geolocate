"""
unit tests for reverse_geolocate.utils.function_collection.get_backup_file_counter
(uses temporary files)
"""

from argparse import Namespace
from pathlib import Path

import pytest

from reverse_geolocate.utils.function_collection import get_backup_file_counter

NO_DEBUG = Namespace(debug=False)


def touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).touch()


def test_no_backups(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 1


def test_xmp_file_does_not_need_to_exist(tmp_path: Path) -> None:
    assert get_backup_file_counter(str(tmp_path / "missing.xmp"), NO_DEBUG) == 1


def test_one_backup(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.BK.1.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 2


def test_highest_plus_one_with_gaps(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.BK.1.xmp", "a.BK.3.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 4


def test_numeric_not_string_order(tmp_path: Path) -> None:
    # "9" > "10" as string, the counter must use the numbers
    touch(tmp_path, "a.xmp", "a.BK.9.xmp", "a.BK.10.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 11


def test_non_numeric_backup_ignored(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.BK.x.xmp", "a.BK..xmp", "a.BK.2.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 3


def test_other_files_not_counted(tmp_path: Path) -> None:
    # similar names: other stem, stem prefix, other extension
    touch(tmp_path, "a.xmp", "b.BK.5.xmp", "ab.BK.6.xmp", "a.BK.7.jpg", "a.BK.8.xmp.tmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 1


def test_other_folder_not_counted(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    touch(other, "a.BK.5.xmp")
    touch(tmp_path, "a.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG) == 1


def test_upper_case_extension(tmp_path: Path) -> None:
    touch(tmp_path, "a.XMP", "a.BK.1.XMP", "a.BK.2.XMP")
    assert get_backup_file_counter(str(tmp_path / "a.XMP"), NO_DEBUG) == 3


def test_stem_with_dots(tmp_path: Path) -> None:
    touch(tmp_path, "2026.11.10_photo.xmp", "2026.11.10_photo.BK.4.xmp")
    assert get_backup_file_counter(str(tmp_path / "2026.11.10_photo.xmp"), NO_DEBUG) == 5


def test_glob_characters_in_file_name(tmp_path: Path) -> None:
    # without escaping, "[a]" would match the file "a" and "*" any file
    touch(tmp_path, "[a].xmp", "[a].BK.2.xmp", "a.BK.9.xmp", "*.xmp", "*.BK.1.xmp", "x.BK.8.xmp")
    assert get_backup_file_counter(str(tmp_path / "[a].xmp"), NO_DEBUG) == 3
    assert get_backup_file_counter(str(tmp_path / "*.xmp"), NO_DEBUG) == 2


def test_glob_characters_in_folder(tmp_path: Path) -> None:
    folder = tmp_path / "photos [2026]?"
    folder.mkdir()
    touch(folder, "a.xmp", "a.BK.1.xmp")
    assert get_backup_file_counter(str(folder / "a.xmp"), NO_DEBUG) == 2


def test_cjk_and_spaces(tmp_path: Path) -> None:
    folder = tmp_path / "東京 フォルダ"
    folder.mkdir()
    touch(folder, "写真 1.xmp", "写真 1.BK.1.xmp")
    assert get_backup_file_counter(str(folder / "写真 1.xmp"), NO_DEBUG) == 2


def test_debug_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    touch(tmp_path, "a.xmp", "a.BK.3.xmp", "a.BK.1.xmp")
    get_backup_file_counter(str(tmp_path / "a.xmp"), Namespace(debug=True))
    out = capsys.readouterr().out
    assert "Backups: [1, 3], Counter: 4" in out


def test_no_output_without_debug(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    get_backup_file_counter(str(tmp_path / "a.xmp"), NO_DEBUG)
    assert capsys.readouterr().out == ""


# __END__
