"""
backup files of the XMP files: <name>.BK.<number>.<ext>
all names are matched case insensitive ("BK" and the extension): on a case insensitive file system
(macOS default) "a.bk.1.xmp" and "a.BK.1.xmp" are the same file, a backup must never be overwritten
"""

import contextlib
import os
import re
import shutil
import unicodedata

# a backup file name of an XMP file: <name>.BK.<number>.xmp in any case
BACKUP_FILE_RE = re.compile(r"^.+\.BK\.(?P<number>\d+)\.xmp$", re.IGNORECASE)


def is_backup_file(file_name: str) -> bool:
    """
    checks if a file name is a backup of an XMP file: <name>.BK.<number>.xmp, in any case

    Args:
        file_name (str): file name without folder

    Returns:
        bool: True for a backup file name
    """
    return BACKUP_FILE_RE.match(file_name) is not None


def backup_number(file_name: str) -> int:
    """
    the number of a backup file name (for sorting)

    Args:
        file_name (str): file name, with or without folder

    Returns:
        int: number of the backup, 0 if it is not a backup file name
    """
    match = BACKUP_FILE_RE.match(os.path.basename(file_name))
    return int(match.group("number")) if match is not None else 0


def backup_file_name(xmp_file: str, number: int) -> str:
    """
    backup file path for an XMP file: <name>.BK.<number>.<ext>, the extension as in the XMP file name

    Args:
        xmp_file (str): XMP file path
        number (int): backup number

    Returns:
        str: backup file path
    """
    name, extension = os.path.splitext(xmp_file)
    return f"{name}.BK.{number}{extension}"


def existing_backup_numbers(xmp_file: str) -> list[int]:
    """
    the numbers of the existing backups of an XMP file, sorted
    name, "BK" and extension are compared case insensitive and in Unicode NFC form,
    so on a case insensitive file system no existing backup is missed

    Args:
        xmp_file (str): XMP file path

    Returns:
        list[int]: backup numbers
    """
    folder, file_name = os.path.split(xmp_file)
    stem, extension = os.path.splitext(unicodedata.normalize("NFC", file_name))
    backup_re = re.compile(rf"^{re.escape(stem)}\.BK\.(\d+){re.escape(extension)}$", re.IGNORECASE)
    try:
        entries = os.listdir(folder or ".")
    except FileNotFoundError:
        return []
    numbers = [
        int(match.group(1))
        for entry in entries
        if (match := backup_re.match(unicodedata.normalize("NFC", entry))) is not None
    ]
    return sorted(numbers)


def get_backup_file_counter(xmp_file: str, debug: bool = False) -> int:
    """
    the next backup number for <name>.BK.<n>.<ext>: highest existing + 1, or 1 if there is none

    Args:
        xmp_file (str): XMP file path
        debug (bool, optional): print the existing backups. Defaults to False.

    Returns:
        int: next backup number
    """
    numbers = existing_backup_numbers(xmp_file)
    counter = max(numbers, default=0) + 1
    if debug:
        print(f"#### **** File: {xmp_file}, Backups: {numbers}, Counter: {counter}")
    return counter


def create_backup(xmp_file: str, debug: bool = False) -> str:
    """
    copies the XMP file to the next free backup file
    an existing file is never overwritten: if the backup name exists (in any case on a case insensitive
    file system, or created in the meantime) the next number is used
    on an error a partly written backup file is removed

    Args:
        xmp_file (str): XMP file path
        debug (bool, optional): print the existing backups. Defaults to False.

    Raises:
        OSError: the backup could not be written (no write permission, disk full, ...)

    Returns:
        str: backup file path
    """
    number = get_backup_file_counter(xmp_file, debug=debug)
    while True:
        backup_file = backup_file_name(xmp_file, number)
        try:
            # "x": create, fails if the file exists
            target = open(backup_file, "xb")  # noqa: SIM115 - closed below, removed on error
        except FileExistsError:
            number += 1
            continue
        try:
            with target, open(xmp_file, "rb") as source:
                shutil.copyfileobj(source, target)
        except OSError:
            # (a failing clean up must not hide the write error)
            with contextlib.suppress(OSError):
                os.remove(backup_file)
            raise
        return backup_file


# __END__
