"""
unit tests for the argparse folder actions ReadableDir and WritableDirFolder
(uses temporary folders and files)
"""

import argparse
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from reverse_geolocate.setup.argparse.readable_dir import ReadableDir
from reverse_geolocate.setup.argparse.writeable_dir_folder import WritableDirFolder

# permission checks do not work as root (everything is accessible) or on Windows (no chmod)
needs_permissions = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)


@pytest.fixture
def chmod_restore() -> Iterator[list[Path]]:
    """paths added to the list get their permissions restored, so tmp_path can be cleaned up"""
    paths: list[Path] = []
    yield paths
    for path in paths:
        path.chmod(0o700)


# MARK: ReadableDir
def readable_action() -> ReadableDir:
    return ReadableDir(option_strings=["-l"], dest="lightroom_folder")


def readable_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--lightroom", action=ReadableDir, dest="lightroom_folder")
    return parser


def test_readable_dir_valid(tmp_path: Path) -> None:
    namespace = argparse.Namespace()
    readable_action()(argparse.ArgumentParser(), namespace, str(tmp_path))
    assert namespace.lightroom_folder == str(tmp_path)


def test_readable_dir_cjk_and_spaces(tmp_path: Path) -> None:
    folder = tmp_path / "Lightroom カタログ"
    folder.mkdir()
    namespace = argparse.Namespace()
    readable_action()(argparse.ArgumentParser(), namespace, str(folder))
    assert namespace.lightroom_folder == str(folder)


def test_readable_dir_not_existing(tmp_path: Path) -> None:
    with pytest.raises(argparse.ArgumentError, match="is not an existing directory"):
        readable_action()(argparse.ArgumentParser(), argparse.Namespace(), str(tmp_path / "missing"))


def test_readable_dir_file(tmp_path: Path) -> None:
    file = tmp_path / "catalog.lrcat"
    file.touch()
    with pytest.raises(argparse.ArgumentError, match="is not an existing directory"):
        readable_action()(argparse.ArgumentParser(), argparse.Namespace(), str(file))


@pytest.mark.parametrize("value", [None, [], ["/tmp"]])
def test_readable_dir_not_a_string(value: list[str] | None) -> None:
    with pytest.raises(argparse.ArgumentError, match="is not a readable dir"):
        readable_action()(argparse.ArgumentParser(), argparse.Namespace(), value)


@needs_permissions
def test_readable_dir_not_readable(tmp_path: Path, chmod_restore: list[Path]) -> None:
    folder = tmp_path / "locked"
    folder.mkdir()
    folder.chmod(0o000)
    chmod_restore.append(folder)
    namespace = argparse.Namespace()
    with pytest.raises(argparse.ArgumentError, match="is not a readable dir"):
        readable_action()(argparse.ArgumentParser(), namespace, str(folder))
    assert not hasattr(namespace, "lightroom_folder")


def test_readable_dir_parser(tmp_path: Path) -> None:
    assert readable_parser().parse_args(["-l", str(tmp_path)]).lightroom_folder == str(tmp_path)
    assert readable_parser().parse_args([]).lightroom_folder is None


def test_readable_dir_parser_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        readable_parser().parse_args(["-l", str(tmp_path / "missing")])
    assert "is not an existing directory" in capsys.readouterr().err


# MARK: WritableDirFolder
def writable_action() -> WritableDirFolder:
    return WritableDirFolder(option_strings=["-i"], dest="xmp_sources", nargs="+")


def writable_parser(nargs: str = "+") -> argparse.ArgumentParser:
    # same setup as in ArgumentSetup (nargs +)
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", nargs=nargs, action=WritableDirFolder, dest="xmp_sources", required=True)
    parser.add_argument("-x", nargs=nargs, action=WritableDirFolder, dest="exclude_sources")
    return parser


def call_writable(values: object, namespace: argparse.Namespace | None = None) -> argparse.Namespace:
    # argparse always sets the dest to its default (None) before calling the action
    if namespace is None:
        namespace = argparse.Namespace(xmp_sources=None)
    writable_action()(argparse.ArgumentParser(), namespace, values)  # type: ignore
    return namespace


def test_writable_folder_and_file(tmp_path: Path) -> None:
    file = tmp_path / "a.xmp"
    file.touch()
    namespace = call_writable([str(tmp_path), str(file)])
    assert namespace.xmp_sources == [str(tmp_path), str(file)]


def test_writable_extends_existing_list(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    namespace = call_writable([str(first)])
    call_writable([str(second)], namespace)
    assert namespace.xmp_sources == [str(first), str(second)]


@pytest.mark.parametrize("value", [None, "/tmp", [], ()])
def test_writable_not_a_list(value: str | list[str] | tuple[str, ...] | None) -> None:
    namespace = argparse.Namespace(xmp_sources=None)
    with pytest.raises(argparse.ArgumentError, match="is not a list of writable dirs or files"):
        call_writable(value, namespace)
    assert namespace.xmp_sources is None


def test_writable_not_existing(tmp_path: Path) -> None:
    with pytest.raises(argparse.ArgumentError, match="is not a writable dir or file"):
        call_writable([str(tmp_path / "missing")])


def test_writable_one_invalid_raises(tmp_path: Path) -> None:
    namespace = argparse.Namespace(xmp_sources=None)
    with pytest.raises(argparse.ArgumentError, match="missing"):
        call_writable([str(tmp_path), str(tmp_path / "missing")], namespace)
    # entries before the invalid one are already stored
    assert namespace.xmp_sources == [str(tmp_path)]


@needs_permissions
def test_writable_read_only_folder(tmp_path: Path, chmod_restore: list[Path]) -> None:
    folder = tmp_path / "read_only"
    folder.mkdir()
    folder.chmod(0o500)
    chmod_restore.append(folder)
    with pytest.raises(argparse.ArgumentError, match="is not a writable dir or file"):
        call_writable([str(folder)])


@needs_permissions
def test_writable_read_only_file(tmp_path: Path, chmod_restore: list[Path]) -> None:
    file = tmp_path / "a.xmp"
    file.touch()
    file.chmod(0o400)
    chmod_restore.append(file)
    with pytest.raises(argparse.ArgumentError, match="is not a writable dir or file"):
        call_writable([str(file)])


def test_writable_parser(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    args = writable_parser().parse_args(["-i", str(first), str(second), "-x", str(second)])
    assert args.xmp_sources == [str(first), str(second)]
    assert args.exclude_sources == [str(second)]


def test_writable_parser_repeated_flag(tmp_path: Path) -> None:
    args = writable_parser().parse_args(["-i", str(tmp_path), "-i", str(tmp_path)])
    # duplicates are kept here, main() removes them from the work files
    assert args.xmp_sources == [str(tmp_path), str(tmp_path)]


def test_writable_parser_missing_required() -> None:
    with pytest.raises(SystemExit):
        writable_parser().parse_args([])


def test_writable_parser_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        writable_parser().parse_args(["-i", str(tmp_path / "missing")])
    assert "is not a writable dir or file" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [["-i"], ["-i", "{tmp}", "-x"], ["-x", "-i", "{tmp}"]])
def test_writable_parser_flag_without_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    # nargs + : argparse rejects the flag without a value itself
    with pytest.raises(SystemExit):
        writable_parser().parse_args([flag.format(tmp=tmp_path) for flag in flags])
    assert "expected at least one argument" in capsys.readouterr().err


def test_writable_parser_flag_without_value_nargs_star(capsys: pytest.CaptureFixture[str]) -> None:
    # nargs * passes an empty list, the action itself must reject it
    with pytest.raises(SystemExit):
        writable_parser(nargs="*").parse_args(["-i"])
    assert "is not a list of writable dirs or files" in capsys.readouterr().err


# __END__
