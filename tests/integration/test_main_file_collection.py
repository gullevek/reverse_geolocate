"""
integration tests for main(): which XMP files are collected from the -i/-x sources
runs in read only mode with --debug, the work file list is taken from the debug output
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from integration_helpers import RunResult, write_xmp

Run = Callable[..., RunResult]


def collect(run_main: Run, *argv: str | Path) -> list[str]:
    result = run_main("-r", "--debug", *argv)
    assert result.exit_code is None, result.out
    work_files = result.work_files()
    assert result.stat("XMP Files found") == len(work_files)
    return work_files


def make_files(folder: Path, *names: str) -> list[str]:
    return [str(write_xmp(folder / name)) for name in names]


# MARK: folders
def test_sample_folder(run_main: Run, sample_folder: Path) -> None:
    assert collect(run_main, "-i", sample_folder) == [str(path) for path in sorted(sample_folder.glob("*.xmp"))]


def test_files_sorted_in_folder(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "src", "c.xmp", "a.xmp", "b.xmp")
    assert collect(run_main, "-i", tmp_path / "src") == sorted(files)


def test_subfolders_searched(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    top = make_files(src, "a.xmp", "b.xmp")
    sub = make_files(src / "sub", "c.xmp")
    deep = make_files(src / "sub" / "deeper", "d.xmp")
    other = make_files(src / "other", "e.xmp")
    # files of a folder first, then the sub folders sorted by name
    assert collect(run_main, "-i", src) == top + other + sub + deep


def test_only_xmp_files(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    files = make_files(src, "a.xmp")
    for name in ("a.jpg", "a.RAF", "notes.txt", "a.xmp.bak", "xmp"):
        (src / name).write_text("not xmp", encoding="UTF-8")
    assert collect(run_main, "-i", src) == files


@pytest.mark.parametrize("extension", [".XMP", ".Xmp", ".xMp"])
def test_extension_any_case(run_main: Run, tmp_path: Path, extension: str) -> None:
    src = tmp_path / "src"
    files = make_files(src, "a.xmp", f"b{extension}")
    assert collect(run_main, "-i", src) == files


def test_extension_any_case_backup_skipped(run_main: Run, tmp_path: Path) -> None:
    # backups of upper case files keep the extension case (a.BK.1.XMP)
    src = tmp_path / "src"
    files = make_files(src, "a.XMP", "a.BK.1.XMP", "b.BK.2.Xmp")
    assert collect(run_main, "-i", src) == files[:1]


def test_extension_any_case_listed(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.XMP")
    result = run_main("-r", "-i", tmp_path / "src")
    assert [row[0] for row in result.table_rows()] == ["a.XMP"]
    assert result.stat("XMP Files listed") == 1


def test_backup_files_skipped(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    files = make_files(src, "a.xmp", "a.BK.1.xmp", "a.BK.2.xmp", "b.BK.x.xmp")
    assert collect(run_main, "-i", src) == files[:1]


def test_empty_folder(run_main: Run, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result = run_main("-r", "--debug", "-i", tmp_path / "empty")
    assert result.work_files() == []
    assert result.stat("XMP Files found") == 0
    assert "[!!!] No files found" in result.out


# MARK: single files
def test_single_file(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path, "a.xmp", "b.xmp")
    assert collect(run_main, "-i", files[1]) == [files[1]]


def test_files_and_folders_mixed(run_main: Run, tmp_path: Path) -> None:
    single = make_files(tmp_path / "single", "x.xmp")
    folder = make_files(tmp_path / "folder", "a.xmp", "b.xmp")
    # in command line order
    assert collect(run_main, "-i", single[0], tmp_path / "folder") == single + folder


def test_single_backup_file_is_used(run_main: Run, tmp_path: Path) -> None:
    # NOTE: the .BK. filter is only used for the folder search, a given file is always used
    files = make_files(tmp_path, "a.BK.1.xmp")
    assert collect(run_main, "-i", files[0]) == files


# MARK: duplicates
def test_same_file_twice(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path, "a.xmp")
    assert collect(run_main, "-i", files[0], "-i", files[0]) == files


def test_same_folder_twice(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "src", "a.xmp", "b.xmp")
    assert collect(run_main, "-i", tmp_path / "src", tmp_path / "src") == files


def test_file_and_its_folder(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "src", "a.xmp", "b.xmp")
    assert collect(run_main, "-i", files[1], tmp_path / "src") == [files[1], files[0]]


def test_folder_and_subfolder(run_main: Run, tmp_path: Path) -> None:
    top = make_files(tmp_path / "src", "a.xmp")
    sub = make_files(tmp_path / "src" / "sub", "b.xmp")
    assert collect(run_main, "-i", tmp_path / "src", tmp_path / "src" / "sub") == top + sub


def test_same_file_different_forms(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = make_files(tmp_path / "src", "a.xmp")
    monkeypatch.chdir(tmp_path)
    # absolute, relative, "./", "//", "../": all the same file, the first form is kept
    work_files = collect(
        run_main, "-i", files[0], "src/a.xmp", "./src/a.xmp", f"{tmp_path}//src/a.xmp", "src/../src/a.xmp"
    )
    assert work_files == files


def test_same_folder_different_forms(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_files(tmp_path / "src", "a.xmp", "b.xmp")
    monkeypatch.chdir(tmp_path)
    work_files = collect(run_main, "-i", "src", f"{tmp_path / 'src'}/", "./src")
    assert work_files == ["src/a.xmp", "src/b.xmp"]


def test_file_given_relative_and_found_in_folder(
    run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = make_files(tmp_path / "src", "a.xmp", "b.xmp")
    monkeypatch.chdir(tmp_path)
    assert collect(run_main, "-i", "src/b.xmp", tmp_path / "src") == ["src/b.xmp", files[0]]


def test_symlinked_file_only_once(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "src", "a.xmp")
    link = tmp_path / "link.xmp"
    link.symlink_to(files[0])
    assert collect(run_main, "-i", files[0], link) == files


def test_symlinked_folder_only_once(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "src", "a.xmp", "b.xmp")
    (tmp_path / "link").symlink_to(tmp_path / "src")
    assert collect(run_main, "-i", tmp_path / "src", tmp_path / "link") == files


def test_same_name_other_folder_not_duplicate(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "one", "a.xmp") + make_files(tmp_path / "two", "a.xmp")
    assert collect(run_main, "-i", tmp_path / "one", tmp_path / "two") == files


# MARK: exclude
def test_exclude_file(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path / "src", "a.xmp", "b.xmp", "c.xmp")
    assert collect(run_main, "-i", tmp_path / "src", "-x", files[1]) == [files[0], files[2]]


def test_exclude_given_file(run_main: Run, tmp_path: Path) -> None:
    files = make_files(tmp_path, "a.xmp", "b.xmp")
    result = run_main("-r", "--debug", "-i", *files, "-x", files[0])
    assert result.work_files() == [files[1]]


@pytest.mark.parametrize("trailing_slash", [False, True])
def test_exclude_subfolder(run_main: Run, tmp_path: Path, trailing_slash: bool) -> None:
    src = tmp_path / "src"
    top = make_files(src, "a.xmp")
    make_files(src / "excluded", "b.xmp")
    other = make_files(src / "other", "c.xmp")
    exclude = f"{src / 'excluded'}/" if trailing_slash else str(src / "excluded")
    assert sorted(collect(run_main, "-i", src, "-x", exclude)) == sorted(top + other)


def test_exclude_source_folder(run_main: Run, tmp_path: Path) -> None:
    make_files(tmp_path / "src", "a.xmp")
    result = run_main("-r", "--debug", "-i", tmp_path / "src", "-x", tmp_path / "src")
    assert result.work_files() == []
    assert "[!!!] No files found" in result.out


def test_exclude_multiple(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    files = make_files(src, "a.xmp", "b.xmp")
    make_files(src / "x1", "c.xmp")
    make_files(src / "x2", "d.xmp")
    assert collect(run_main, "-i", src, "-x", src / "x1", files[0], "-x", src / "x2") == files[1:]


def test_exclude_folder_includes_its_subfolders(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    top = make_files(src, "a.xmp")
    make_files(src / "excluded", "b.xmp")
    make_files(src / "excluded" / "deeper", "c.xmp")
    make_files(src / "excluded" / "deeper" / "deepest", "d.xmp")
    assert collect(run_main, "-i", src, "-x", src / "excluded") == top


def test_exclude_only_whole_folder_names(run_main: Run, tmp_path: Path) -> None:
    # "ex" must not exclude "ex2" or "ex.old"
    src = tmp_path / "src"
    make_files(src / "ex", "a.xmp")
    others = make_files(src / "ex.old", "b.xmp") + make_files(src / "ex2", "c.xmp")
    assert collect(run_main, "-i", src, "-x", src / "ex") == others


@pytest.mark.parametrize("source_suffix", ["", "/"])
@pytest.mark.parametrize("exclude_suffix", ["", "/"])
def test_exclude_source_folder_any_trailing_slash(
    run_main: Run, tmp_path: Path, source_suffix: str, exclude_suffix: str
) -> None:
    make_files(tmp_path / "src", "a.xmp")
    result = run_main(
        "-r", "--debug", "-i", f"{tmp_path / 'src'}{source_suffix}", "-x", f"{tmp_path / 'src'}{exclude_suffix}"
    )
    assert result.exit_code is None
    assert result.work_files() == []
    assert "[!!!] No files found" in result.out


def test_exclude_given_file_inside_excluded_folder(run_main: Run, tmp_path: Path) -> None:
    excluded = make_files(tmp_path / "src" / "ex", "a.xmp")
    other = make_files(tmp_path / "other", "b.xmp")
    assert collect(run_main, "-i", excluded[0], other[0], "-x", tmp_path / "src") == other


def test_exclude_given_sub_folder_of_excluded_folder(run_main: Run, tmp_path: Path) -> None:
    make_files(tmp_path / "src" / "sub", "a.xmp")
    result = run_main("-r", "--debug", "-i", tmp_path / "src" / "sub", "-x", tmp_path / "src")
    assert result.work_files() == []


def test_exclude_not_normalized_path(run_main: Run, tmp_path: Path) -> None:
    src = tmp_path / "src"
    top = make_files(src, "a.xmp")
    make_files(src, "b.xmp")
    make_files(src / "ex", "c.xmp")
    # the paths must exist for the -x argument check, also for the ".." step
    (src / "other").mkdir()
    # "//", "./" and "../" in the exclude paths
    exclude_folder = f"{src}//other/../ex"
    exclude_file = f"{src}/./b.xmp"
    assert collect(run_main, "-i", src, "-x", exclude_folder, exclude_file) == top


def test_exclude_relative_and_absolute(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # absolute source, relative exclude (and the other way around)
    src = tmp_path / "src"
    top = make_files(src, "a.xmp")
    make_files(src / "ex", "b.xmp")
    monkeypatch.chdir(tmp_path)
    assert collect(run_main, "-i", src, "-x", "src/ex") == top
    assert collect(run_main, "-i", "src", "-x", src / "ex") == ["src/a.xmp"]


# __END__
