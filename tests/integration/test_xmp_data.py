"""
tests for reverse_geolocate.utils.xmp_data: read the data set from XMP files, write them back with backup
needs the Exempi library (in tests/integration, not collected without Exempi, see conftest.py)
"""

import errno
import os
import shutil
import stat
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from integration_helpers import SAMPLE_FILES, TOKYO_LAT, TOKYO_LONG, read_xmp, write_xmp
from libxmp import XMPMeta, consts

from reverse_geolocate.utils import xmp_data
from reverse_geolocate.utils.xmp_data import XMP_FIELDS, XmpReadError, XmpWriteError, read_xmp_file, write_xmp_file

NO_DEBUG = Namespace(debug=False)
FULL = {"Location": "Jingumae", "City": "Shibuya", "State": "Tokyo", "Country": "Japan", "CountryCode": "JP"}
EMPTY = dict.fromkeys(XMP_FIELDS, "")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """own folder for the files (tmp_path also holds the temporary HOME folder)"""
    path = tmp_path / "files"
    path.mkdir()
    return path


# MARK: XMP_FIELDS
def test_xmp_fields() -> None:
    assert XMP_FIELDS == {
        "GPSLatitude": consts.XMP_NS_EXIF,
        "GPSLongitude": consts.XMP_NS_EXIF,
        "Location": consts.XMP_NS_IPTCCore,
        "City": consts.XMP_NS_Photoshop,
        "State": consts.XMP_NS_Photoshop,
        "Country": consts.XMP_NS_Photoshop,
        "CountryCode": consts.XMP_NS_IPTCCore,
    }


# MARK: read_xmp_data_set
def test_read_all_fields(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp", **FULL)
    assert read_xmp_file(str(file))[1] == {"GPSLatitude": TOKYO_LAT, "GPSLongitude": TOKYO_LONG, **FULL}


def test_read_missing_fields(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp", GPSLatitude="", GPSLongitude="", City="Osaka")
    assert read_xmp_file(str(file))[1] == {**EMPTY, "City": "Osaka"}


def test_read_cjk(folder: Path) -> None:
    file = write_xmp(folder / "写真" / "東京.xmp", City="渋谷区", Country="日本")
    data_set = read_xmp_file(str(file))[1]
    assert data_set["City"] == "渋谷区"
    assert data_set["Country"] == "日本"


def test_read_sample_files() -> None:
    for file in SAMPLE_FILES:
        assert read_xmp_file(str(file))[1] == {**EMPTY, "GPSLatitude": TOKYO_LAT, "GPSLongitude": TOKYO_LONG}


def test_read_new_object_for_each_file(folder: Path) -> None:
    full = write_xmp(folder / "full.xmp", **FULL)
    nothing = write_xmp(folder / "nothing.xmp", GPSLatitude="", GPSLongitude="")
    first, _ = read_xmp_file(str(full))
    second, data_set = read_xmp_file(str(nothing))
    assert first is not second
    # no data of the previous file
    assert data_set == EMPTY
    assert not second.does_property_exist(consts.XMP_NS_Photoshop, "City")


def test_read_empty_file(folder: Path) -> None:
    file = folder / "empty.xmp"
    file.write_text("", encoding="UTF-8")
    assert read_xmp_file(str(file))[1] == EMPTY


def test_read_keeps_data_in_object(folder: Path) -> None:
    # the XMP object holds the file data after reading, for writing it back
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp, _ = read_xmp_file(str(file))
    assert xmp.get_property(consts.XMP_NS_Photoshop, "City") == "Osaka"


@pytest.mark.parametrize("content", ["just text", '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF'])
def test_read_invalid_xmp(folder: Path, content: str) -> None:
    file = folder / "broken.xmp"
    file.write_text(content, encoding="UTF-8")
    with pytest.raises(XmpReadError, match="no valid XMP"):
        read_xmp_file(str(file))


def test_read_after_damaged_file(folder: Path) -> None:
    # an XMP object can not be used after a parse error, each file gets a new one
    damaged = folder / "damaged.xmp"
    damaged.write_text("just text", encoding="UTF-8")
    file = write_xmp(folder / "a.xmp", City="Osaka")
    with pytest.raises(XmpReadError):
        read_xmp_file(str(damaged))
    assert read_xmp_file(str(file))[1]["City"] == "Osaka"


def test_read_binary_file(folder: Path) -> None:
    file = folder / "binary.xmp"
    file.write_bytes(bytes(range(256)))
    with pytest.raises(XmpReadError, match="not a text file"):
        read_xmp_file(str(file))


def test_read_missing_file(folder: Path) -> None:
    with pytest.raises(XmpReadError, match="file not readable: No such file or directory"):
        read_xmp_file(str(folder / "missing.xmp"))


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
def test_read_not_readable(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp")
    file.chmod(0o000)
    try:
        with pytest.raises(XmpReadError, match="file not readable: Permission denied"):
            read_xmp_file(str(file))
    finally:
        file.chmod(0o644)


def test_read_debug_output(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    read_xmp_file(str(file), debug=True)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(XMP_FIELDS)
    assert f"### [{file}] => XMP: {consts.XMP_NS_Photoshop}:City => Osaka" in lines
    assert f"### [{file}] => XMP: {consts.XMP_NS_Photoshop}:State => " in lines


def test_read_no_output_without_debug(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    read_xmp_file(str(write_xmp(folder / "a.xmp")))
    assert capsys.readouterr().out == ""


# MARK: write_xmp_file
def change_city(file: Path, city: str) -> XMPMeta:
    """read a file and change the City in the XMP object"""
    xmp, _ = read_xmp_file(str(file))
    xmp.set_property(consts.XMP_NS_Photoshop, "City", city)
    return xmp


def test_write_without_backup(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=False, args=NO_DEBUG)
    assert read_xmp(file)["City"] == "Kyoto"
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


def test_write_with_backup(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    original = file.read_bytes()
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    assert (folder / "a.BK.1.xmp").read_bytes() == original
    assert read_xmp(file)["City"] == "Kyoto"


def test_write_backup_counter(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp", City="One")
    for city in ("Two", "Three", "Four"):
        xmp = change_city(file, city)
        write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    assert sorted(path.name for path in folder.iterdir()) == ["a.BK.1.xmp", "a.BK.2.xmp", "a.BK.3.xmp", "a.xmp"]
    assert read_xmp(folder / "a.BK.1.xmp")["City"] == "One"
    assert read_xmp(folder / "a.BK.3.xmp")["City"] == "Three"
    assert read_xmp(file)["City"] == "Four"


def test_write_backup_upper_case_extension(folder: Path) -> None:
    file = write_xmp(folder / "a.XMP")
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    assert sorted(path.name for path in folder.iterdir()) == ["a.BK.1.XMP", "a.XMP"]


def test_write_backup_name_with_dots(folder: Path) -> None:
    file = write_xmp(folder / "2026.11.10_photo.xmp")
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    assert (folder / "2026.11.10_photo.BK.1.xmp").is_file()


def test_write_keeps_other_data(folder: Path) -> None:
    file = folder / SAMPLE_FILES[0].name
    shutil.copy(SAMPLE_FILES[0], file)
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=False, args=NO_DEBUG)
    check = XMPMeta()
    check.parse_from_str(file.read_text(encoding="UTF-8"))
    assert check.get_property(consts.XMP_NS_Photoshop, "City") == "Kyoto"
    assert check.get_property(consts.XMP_NS_TIFF, "Model") == "X-T3"
    assert check.get_property(consts.XMP_NS_EXIF, "GPSLatitude") == TOKYO_LAT


def test_write_no_packet_wrapper(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp")
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=False, args=NO_DEBUG)
    content = file.read_text(encoding="UTF-8")
    assert content.startswith("<x:xmpmeta")
    assert "<?xpacket" not in content


def test_write_cjk(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp")
    xmp = change_city(file, "渋谷区")
    write_xmp_file(xmp, str(file), backup=False, args=NO_DEBUG)
    assert read_xmp(file)["City"] == "渋谷区"


def test_write_debug_backup_output(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = write_xmp(folder / "a.xmp")
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=True, args=Namespace(debug=True))
    assert f"#### **** File: {file}, Backups: [], Counter: 1" in capsys.readouterr().out


# MARK: write errors
needs_permissions = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)


def disk_full(*args: object, **kwargs: object) -> None:
    raise OSError(errno.ENOSPC, "No space left on device")


def test_write_no_temporary_files_left(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp")
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    assert sorted(path.name for path in folder.iterdir()) == ["a.BK.1.xmp", "a.xmp"]


def test_write_keeps_file_mode(folder: Path) -> None:
    file = write_xmp(folder / "a.xmp")
    file.chmod(0o640)
    xmp = change_city(file, "Kyoto")
    write_xmp_file(xmp, str(file), backup=False, args=NO_DEBUG)
    assert stat.S_IMODE(file.stat().st_mode) == 0o640


def test_write_symlink(folder: Path) -> None:
    # the file the symlink points to is written, the symlink stays
    target = write_xmp(folder / "target" / "a.xmp")
    link = folder / "link.xmp"
    link.symlink_to(target)
    xmp = change_city(link, "Kyoto")
    write_xmp_file(xmp, str(link), backup=False, args=NO_DEBUG)
    assert link.is_symlink()
    assert read_xmp(target)["City"] == "Kyoto"


@needs_permissions
@pytest.mark.parametrize("backup", [True, False])
def test_write_protected_file(folder: Path, backup: bool) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp = change_city(file, "Kyoto")
    before = file.read_bytes()
    file.chmod(0o444)
    try:
        with pytest.raises(XmpWriteError, match="no write permission") as exc_info:
            write_xmp_file(xmp, str(file), backup=backup, args=NO_DEBUG)
    finally:
        file.chmod(0o644)
    assert exc_info.value.xmp_file == str(file)
    assert exc_info.value.reason == "no write permission"
    # unchanged, no backup, no temporary file (also not replaced via the folder)
    assert file.read_bytes() == before
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


@needs_permissions
@pytest.mark.parametrize("backup", [True, False])
def test_write_protected_folder(folder: Path, backup: bool) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp = change_city(file, "Kyoto")
    before = file.read_bytes()
    folder.chmod(0o555)
    try:
        with pytest.raises(XmpWriteError, match="Permission denied"):
            write_xmp_file(xmp, str(file), backup=backup, args=NO_DEBUG)
    finally:
        folder.chmod(0o755)
    assert file.read_bytes() == before
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


@pytest.mark.parametrize("backup", [True, False])
def test_write_disk_full(folder: Path, monkeypatch: pytest.MonkeyPatch, backup: bool) -> None:
    # the temporary file is written, replacing the file fails
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp = change_city(file, "Kyoto")
    before = file.read_bytes()
    monkeypatch.setattr(xmp_data.os, "replace", disk_full)
    with pytest.raises(XmpWriteError, match="No space left on device"):
        write_xmp_file(xmp, str(file), backup=backup, args=NO_DEBUG)
    # the original is complete, the temporary file and the backup are removed
    assert file.read_bytes() == before
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


def test_write_disk_full_while_writing(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp = change_city(file, "Kyoto")
    before = file.read_bytes()
    real_fdopen = os.fdopen

    def fdopen_disk_full(fd: int, *args: object, **kwargs: object) -> object:
        # the temporary file exists, writing to it fails
        real_fdopen(fd).close()
        disk_full()
        return None

    monkeypatch.setattr(xmp_data.os, "fdopen", fdopen_disk_full)
    with pytest.raises(XmpWriteError, match="No space left on device"):
        write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    assert file.read_bytes() == before
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


def test_write_disk_full_backup(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = write_xmp(folder / "a.xmp", City="Osaka")
    xmp = change_city(file, "Kyoto")
    before = file.read_bytes()

    def partial_copy(source: str, destination: str) -> None:
        # a partial backup is written, then the disk is full
        Path(destination).write_text("partial", encoding="UTF-8")
        disk_full()

    monkeypatch.setattr(xmp_data, "copyfile", partial_copy)
    with pytest.raises(XmpWriteError, match="No space left on device"):
        write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    # the partial backup is removed, the file is unchanged
    assert file.read_bytes() == before
    assert [path.name for path in folder.iterdir()] == ["a.xmp"]


def test_write_existing_backups_kept_on_error(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = write_xmp(folder / "a.xmp")
    (folder / "a.BK.1.xmp").write_text("old backup", encoding="UTF-8")
    xmp = change_city(file, "Kyoto")
    monkeypatch.setattr(xmp_data.os, "replace", disk_full)
    with pytest.raises(XmpWriteError):
        write_xmp_file(xmp, str(file), backup=True, args=NO_DEBUG)
    # only the new backup (BK.2) is removed
    assert sorted(path.name for path in folder.iterdir()) == ["a.BK.1.xmp", "a.xmp"]
    assert (folder / "a.BK.1.xmp").read_text(encoding="UTF-8") == "old backup"


def test_write_error_message() -> None:
    error = XmpWriteError("/a/b.xmp", "no write permission")
    assert str(error) == "/a/b.xmp: no write permission"


# __END__
