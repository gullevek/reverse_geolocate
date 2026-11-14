"""
unit tests for reverse_geolocate.utils.backup
(uses temporary files)
"""

import errno
import os
import sys
from pathlib import Path

import pytest

from reverse_geolocate.utils import backup
from reverse_geolocate.utils.backup import (
    backup_file_name,
    backup_number,
    create_backup,
    existing_backup_numbers,
    get_backup_file_counter,
    is_backup_file,
)


def touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).touch()


def test_no_backups(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 1


def test_xmp_file_does_not_need_to_exist(tmp_path: Path) -> None:
    assert get_backup_file_counter(str(tmp_path / "missing.xmp")) == 1


def test_one_backup(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.BK.1.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 2


def test_highest_plus_one_with_gaps(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.BK.1.xmp", "a.BK.3.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 4


def test_numeric_not_string_order(tmp_path: Path) -> None:
    # "9" > "10" as string, the counter must use the numbers
    touch(tmp_path, "a.xmp", "a.BK.9.xmp", "a.BK.10.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 11


def test_non_numeric_backup_ignored(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.BK.x.xmp", "a.BK..xmp", "a.BK.2.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 3


def test_other_files_not_counted(tmp_path: Path) -> None:
    # similar names: other stem, stem prefix, other extension
    touch(tmp_path, "a.xmp", "b.BK.5.xmp", "ab.BK.6.xmp", "a.BK.7.jpg", "a.BK.8.xmp.tmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 1


def test_other_folder_not_counted(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    touch(other, "a.BK.5.xmp")
    touch(tmp_path, "a.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 1


def test_upper_case_extension(tmp_path: Path) -> None:
    touch(tmp_path, "a.XMP", "a.BK.1.XMP", "a.BK.2.XMP")
    assert get_backup_file_counter(str(tmp_path / "a.XMP")) == 3


def test_stem_with_dots(tmp_path: Path) -> None:
    touch(tmp_path, "2026.11.10_photo.xmp", "2026.11.10_photo.BK.4.xmp")
    assert get_backup_file_counter(str(tmp_path / "2026.11.10_photo.xmp")) == 5


def test_glob_characters_in_file_name(tmp_path: Path) -> None:
    # without escaping, "[a]" would match the file "a" and "*" any file
    touch(tmp_path, "[a].xmp", "[a].BK.2.xmp", "a.BK.9.xmp", "*.xmp", "*.BK.1.xmp", "x.BK.8.xmp")
    assert get_backup_file_counter(str(tmp_path / "[a].xmp")) == 3
    assert get_backup_file_counter(str(tmp_path / "*.xmp")) == 2


def test_glob_characters_in_folder(tmp_path: Path) -> None:
    folder = tmp_path / "photos [2026]?"
    folder.mkdir()
    touch(folder, "a.xmp", "a.BK.1.xmp")
    assert get_backup_file_counter(str(folder / "a.xmp")) == 2


def test_cjk_and_spaces(tmp_path: Path) -> None:
    folder = tmp_path / "東京 フォルダ"
    folder.mkdir()
    touch(folder, "写真 1.xmp", "写真 1.BK.1.xmp")
    assert get_backup_file_counter(str(folder / "写真 1.xmp")) == 2


def test_debug_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    touch(tmp_path, "a.xmp", "a.BK.3.xmp", "a.BK.1.xmp")
    get_backup_file_counter(str(tmp_path / "a.xmp"), debug=True)
    out = capsys.readouterr().out
    assert "Backups: [1, 3], Counter: 4" in out


def test_no_output_without_debug(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    get_backup_file_counter(str(tmp_path / "a.xmp"))
    assert capsys.readouterr().out == ""


# MARK: is_backup_file / backup_number
@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("a.BK.1.xmp", True),
        ("a.BK.12.xmp", True),
        # any case
        ("a.bk.1.xmp", True),
        ("a.Bk.3.Xmp", True),
        ("a.BK.4.XMP", True),
        ("2026.11.10_a.BK.1.xmp", True),
        # not a backup name
        ("a.xmp", False),
        ("a.BK.xmp", False),
        ("a.BK.x.xmp", False),
        ("Trip.BK.Paris.xmp", False),
        ("a.BK.1.2026.xmp", False),
        ("a.BK.1.jpg", False),
        ("a.BK.1.xmp.tmp", False),
        (".BK.1.xmp", False),
    ],
)
def test_is_backup_file(file_name: str, expected: bool) -> None:
    assert is_backup_file(file_name) is expected


@pytest.mark.parametrize(
    ("file", "expected"),
    [
        ("photo.xmp", 0),
        ("photo.BK.1.xmp", 1),
        ("photo.BK.12.xmp", 12),
        ("/some/path/photo.BK.3.xmp", 3),
        ("photo.BK.xmp", 0),
        ("photo.BK.x.xmp", 0),
        ("photo.BK.3.XMP", 3),
        ("photo.bk.5.xmp", 5),
        ("photo.Bk.6.XMP", 6),
        ("photo.BK.3.xmp.tmp", 0),
    ],
)
def test_backup_number(file: str, expected: int) -> None:
    assert backup_number(file) == expected


def test_backup_number_sorting() -> None:
    files = ["a.BK.10.xmp", "a.XMP", "a.bk.2.xmp", "a.BK.1.Xmp"]
    assert sorted(files, key=backup_number) == ["a.XMP", "a.BK.1.Xmp", "a.bk.2.xmp", "a.BK.10.xmp"]


# MARK: backup_file_name
@pytest.mark.parametrize(
    ("xmp_file", "expected"),
    [
        ("/photos/a.xmp", "/photos/a.BK.3.xmp"),
        ("/photos/a.XMP", "/photos/a.BK.3.XMP"),
        ("/photos/2026.11.10_a.xmp", "/photos/2026.11.10_a.BK.3.xmp"),
        ("a.xmp", "a.BK.3.xmp"),
    ],
)
def test_backup_file_name(xmp_file: str, expected: str) -> None:
    assert backup_file_name(xmp_file, 3) == expected


# MARK: existing backups in any case
def test_counter_backups_any_case(tmp_path: Path) -> None:
    touch(tmp_path, "a.xmp", "a.bk.1.xmp", "a.Bk.4.Xmp", "a.BK.2.XMP")
    assert existing_backup_numbers(str(tmp_path / "a.xmp")) == [1, 2, 4]
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 5


def test_counter_upper_case_file_lower_case_backups(tmp_path: Path) -> None:
    # a.XMP with existing a.BK.1.xmp: the backup must not overwrite it (case insensitive file system)
    touch(tmp_path, "b.XMP", "b.BK.1.xmp")
    assert get_backup_file_counter(str(tmp_path / "b.XMP")) == 2


def test_counter_name_any_case(tmp_path: Path) -> None:
    # NOTE: the name is compared case insensitive too: on a case sensitive file system "A.xmp" and "a.xmp"
    # share the numbers (a number can be skipped, a backup is never overwritten)
    touch(tmp_path, "A.BK.3.xmp")
    assert get_backup_file_counter(str(tmp_path / "a.xmp")) == 4


def test_counter_unicode_form(tmp_path: Path) -> None:
    # backups stored decomposed (NFD), the XMP file given composed (NFC)
    import unicodedata

    touch(tmp_path, unicodedata.normalize("NFD", "Zürich.BK.2.xmp"))
    assert get_backup_file_counter(str(tmp_path / unicodedata.normalize("NFC", "Zürich.xmp"))) == 3


def test_counter_missing_folder(tmp_path: Path) -> None:
    assert get_backup_file_counter(str(tmp_path / "missing" / "a.xmp")) == 1


def test_counter_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    touch(tmp_path, "a.BK.1.xmp")
    monkeypatch.chdir(tmp_path)
    assert get_backup_file_counter("a.xmp") == 2


# MARK: create_backup
def counter_always_one(xmp_file: str, debug: bool = False) -> int:
    """a wrong counter, as if the backups were created in the meantime"""
    return 1


def test_create_backup(tmp_path: Path) -> None:
    (tmp_path / "a.xmp").write_text("original", encoding="UTF-8")
    backup_file = create_backup(str(tmp_path / "a.xmp"))
    assert backup_file == str(tmp_path / "a.BK.1.xmp")
    assert (tmp_path / "a.BK.1.xmp").read_text(encoding="UTF-8") == "original"


def test_create_backup_after_existing_any_case(tmp_path: Path) -> None:
    (tmp_path / "a.xmp").write_text("new", encoding="UTF-8")
    (tmp_path / "a.bk.1.xmp").write_text("old backup", encoding="UTF-8")
    assert create_backup(str(tmp_path / "a.xmp")) == str(tmp_path / "a.BK.2.xmp")
    assert (tmp_path / "a.bk.1.xmp").read_text(encoding="UTF-8") == "old backup"
    assert (tmp_path / "a.BK.2.xmp").read_text(encoding="UTF-8") == "new"


def test_create_backup_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # the counter is wrong (eg the backup was created in the meantime): the next free number is used
    (tmp_path / "a.xmp").write_text("new", encoding="UTF-8")
    (tmp_path / "a.BK.1.xmp").write_text("old 1", encoding="UTF-8")
    (tmp_path / "a.BK.2.xmp").write_text("old 2", encoding="UTF-8")
    monkeypatch.setattr(backup, "get_backup_file_counter", counter_always_one)
    assert create_backup(str(tmp_path / "a.xmp")) == str(tmp_path / "a.BK.3.xmp")
    assert (tmp_path / "a.BK.1.xmp").read_text(encoding="UTF-8") == "old 1"
    assert (tmp_path / "a.BK.2.xmp").read_text(encoding="UTF-8") == "old 2"


def test_create_backup_existing_other_case_on_case_insensitive_file_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # on a case insensitive file system "a.BK.1.xmp" is the existing "a.bk.1.xmp": not overwritten
    (tmp_path / "a.xmp").write_text("new", encoding="UTF-8")
    (tmp_path / "a.bk.1.xmp").write_text("old backup", encoding="UTF-8")
    if not (tmp_path / "a.BK.1.xmp").exists():
        pytest.skip("case sensitive file system")
    monkeypatch.setattr(backup, "get_backup_file_counter", counter_always_one)
    create_backup(str(tmp_path / "a.xmp"))
    assert (tmp_path / "a.bk.1.xmp").read_text(encoding="UTF-8") == "old backup"


def test_create_backup_error_removes_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.xmp").write_text("original", encoding="UTF-8")

    def disk_full(source: object, target: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(backup.shutil, "copyfileobj", disk_full)
    with pytest.raises(OSError, match="No space left on device"):
        create_backup(str(tmp_path / "a.xmp"))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.xmp"]


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
def test_create_backup_folder_not_writable(tmp_path: Path) -> None:
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "a.xmp").write_text("original", encoding="UTF-8")
    folder.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            create_backup(str(folder / "a.xmp"))
    finally:
        folder.chmod(0o755)
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


def test_create_backup_keeps_content_bytes(tmp_path: Path) -> None:
    content = "東京 Zürich\r\n".encode() + bytes(range(10))
    (tmp_path / "a.xmp").write_bytes(content)
    create_backup(str(tmp_path / "a.xmp"))
    assert (tmp_path / "a.BK.1.xmp").read_bytes() == content


def test_create_backup_debug_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "a.xmp").write_text("x", encoding="UTF-8")
    (tmp_path / "a.bk.2.xmp").write_text("x", encoding="UTF-8")
    create_backup(str(tmp_path / "a.xmp"), debug=True)
    assert f"#### **** File: {tmp_path / 'a.xmp'}, Backups: [2], Counter: 3" in capsys.readouterr().out


# __END__
