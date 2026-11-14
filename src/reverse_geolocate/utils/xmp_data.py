"""
XMP sidecar file data: read the GPS and location fields into a data set, write the file back (with backup)
NOTE: needs the Exempi library (python-xmp-toolkit)
"""

import contextlib
import os
import shutil
import tempfile
from argparse import Namespace

# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import XMPError, XMPMeta, consts

from reverse_geolocate.utils.backup import create_backup

# The XMP fields const lookup values
# exif:GPSLatitude, exif:GPSLongitude: stored in Degree,Min.Sec[NESW] format
# Iptc4xmpCore:Location, photoshop:City, photoshop:State, photoshop:Country, Iptc4xmpCore:CountryCode
XMP_FIELDS = {
    "GPSLatitude": consts.XMP_NS_EXIF,
    "GPSLongitude": consts.XMP_NS_EXIF,
    "Location": consts.XMP_NS_IPTCCore,
    "City": consts.XMP_NS_Photoshop,
    "State": consts.XMP_NS_Photoshop,
    "Country": consts.XMP_NS_Photoshop,
    "CountryCode": consts.XMP_NS_IPTCCore,
}


class XmpReadError(Exception):
    """an XMP file could not be read: not readable, not UTF-8 or no valid XMP (damaged)"""


def read_xmp_file(xmp_file: str, debug: bool = False) -> tuple[XMPMeta, dict[str, str]]:
    """
    reads an XMP file into a new XMP object and returns it with the GPS and location fields
    (the XMP object keeps the file data, for writing it back)
    a new object for each file: after a parse error (damaged file) an XMP object can not be used anymore,
    also no data of a previous file can be carried over

    Args:
        xmp_file (str): XMP file path
        debug (bool, optional): print the read fields. Defaults to False.

    Raises:
        XmpReadError: the file can not be read or is no valid XMP

    Returns:
        tuple[XMPMeta, dict[str, str]]: XMP object with the file data,
            data set with all XMP_FIELDS keys, missing fields are empty
    """
    xmp = XMPMeta()
    try:
        with open(xmp_file, "r", encoding="UTF-8") as fptr:
            xmp.parse_from_str(fptr.read())
    except OSError as e:
        raise XmpReadError(f"file not readable: {e.strerror}") from e
    except UnicodeDecodeError as e:
        raise XmpReadError("not a text file (UTF-8)") from e
    except XMPError as e:
        raise XmpReadError(f"no valid XMP: {e}") from e
    data_set: dict[str, str] = {}
    for key, namespace in XMP_FIELDS.items():
        # need to check if the property exists or the exempi routine will fail
        data_set[key] = xmp.get_property(namespace, key) if xmp.does_property_exist(namespace, key) else ""
        if debug:
            print(f"### [{xmp_file}] => XMP: {namespace}:{key} => {data_set[key]}")
    return xmp, data_set


class XmpWriteError(Exception):
    """an XMP file (or its backup) could not be written: no write permission, disk full, ..."""

    def __init__(self, xmp_file: str, reason: str) -> None:
        super().__init__(f"{xmp_file}: {reason}")
        self.xmp_file = xmp_file
        self.reason = reason


def write_xmp_file(xmp: XMPMeta, xmp_file: str, backup: bool, args: Namespace) -> None:
    """
    writes the XMP object back to the file, optional with a backup copy before

    the file is written safely: first to a temporary file in the same folder, then it replaces the file,
    so the XMP file is never left half written (eg disk full)
    on any error the XMP file is unchanged and no new backup or temporary file is left

    Args:
        xmp (XMPMeta): XMP object with the changed data
        xmp_file (str): XMP file path (a symlink: the file it points to is written)
        backup (bool): create a backup copy <name>.BK.<n>.<ext> before writing
        args (Namespace): command line arguments (for the debug flag)

    Raises:
        XmpWriteError: the file or the backup could not be written
    """
    # write the file a symlink points to, the symlink stays
    target_file = os.path.realpath(xmp_file)
    # a write protected file must not be replaced (replacing only needs folder write permission)
    if not os.access(target_file, os.W_OK):
        raise XmpWriteError(xmp_file, "no write permission")
    content = xmp.serialize_to_str(omit_packet_wrapper=True)
    backup_file = ""
    temp_file = ""
    try:
        if backup:
            # next free backup number, an existing backup is never overwritten
            backup_file = create_backup(xmp_file, debug=bool(args.debug))
        # temporary file in the same folder (same file system), hidden name
        folder, file_name = os.path.split(target_file)
        fd, temp_file = tempfile.mkstemp(dir=folder, prefix=f".{file_name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="UTF-8") as fptr:
            fptr.write(content)
        # keep the file permissions of the original file
        shutil.copymode(target_file, temp_file)
        os.replace(temp_file, target_file)
    except OSError as e:
        # the XMP file is unchanged: remove the temporary file and the new (maybe partial) backup
        # (a failing clean up must not hide the write error)
        for file in (temp_file, backup_file):
            if file:
                with contextlib.suppress(OSError):
                    os.remove(file)
        raise XmpWriteError(xmp_file, e.strerror or str(e)) from e


# __END__
