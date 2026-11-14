"""
collect the XMP files to work on from the -i sources, without the -x excludes
"""

import os
from pathlib import Path

from reverse_geolocate.utils.function_collection import is_path_excluded, normalize_exclude_paths, normalize_path


def is_xmp_work_file(file_name: str) -> bool:
    """
    checks if a file found in a folder is an XMP file to work on:
    .xmp extension in any case (.xmp, .XMP, .Xmp, ...), but not a backup file (.BK.)

    Args:
        file_name (str): file name without folder

    Returns:
        bool: True if the file should be used
    """
    return file_name.lower().endswith(".xmp") and ".BK." not in file_name


def collect_work_files(xmp_sources: list[str], exclude_sources: list[str]) -> list[str]:
    """
    collects the XMP files from the sources (folders are searched with all sub folders)

    - excluded folders (and all their sub folders) and files are skipped
    - in folders only XMP files are used (see is_xmp_work_file), files given directly are always used
    - each file is only added once, also if given in a different form
      (relative/absolute, "./", "//", symlink, ...)
    - the files of a folder are sorted, then the sub folders sorted by name

    Args:
        xmp_sources (list[str]): -i folders and files
        exclude_sources (list[str]): -x folders and files

    Returns:
        list[str]: work files, the paths as given or found (for the output)
    """
    # normalized absolute exclude paths, build once and not for every file
    exclude_paths = normalize_exclude_paths(exclude_sources)
    work_files: list[str] = []
    # normalized paths of the work files, so the same file is only added once
    work_files_normalized: set[Path] = set()

    def add_work_file(file_path: str) -> None:
        """add a file to the work files, if it is not already in there"""
        normalized = normalize_path(file_path)
        if normalized in work_files_normalized:
            return
        work_files_normalized.add(normalized)
        work_files.append(file_path)

    for xmp_file_source in xmp_sources:
        # skip excluded sources (folder or file), also if inside an excluded folder
        if is_path_excluded(xmp_file_source, exclude_paths):
            continue
        if not os.path.isdir(xmp_file_source):
            add_work_file(xmp_file_source)
            continue
        # folder: search it and all sub folders
        for root, folders, files in os.walk(xmp_file_source):
            # do not walk into excluded sub folders, sorted for a stable order
            folders[:] = sorted(
                folder for folder in folders if not is_path_excluded(os.path.join(root, folder), exclude_paths)
            )
            for file in sorted(files):
                file_path = os.path.join(root, file)
                if is_xmp_work_file(file) and not is_path_excluded(file_path, exclude_paths):
                    add_work_file(file_path)
    return work_files


# __END__
