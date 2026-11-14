"""
XMP sidecar file data: read the GPS and location fields into a data set, write the file back (with backup)
NOTE: needs the Exempi library (python-xmp-toolkit)
"""

import os
from argparse import Namespace
from shutil import copyfile

# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import XMPError, XMPMeta, consts

from reverse_geolocate.utils.function_collection import get_backup_file_counter

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


def write_xmp_file(xmp: XMPMeta, xmp_file: str, backup: bool, args: Namespace) -> None:
    """
    writes the XMP object back to the file, optional with a backup copy before

    Args:
        xmp (XMPMeta): XMP object with the changed data
        xmp_file (str): XMP file path
        backup (bool): create a backup copy <name>.BK.<n>.<ext> before writing
        args (Namespace): command line arguments (for the debug flag)
    """
    if backup:
        # next free backup number, highest existing + 1
        bk_file_counter = get_backup_file_counter(xmp_file, args)
        name, extension = os.path.splitext(xmp_file)
        copyfile(xmp_file, f"{name}.BK.{bk_file_counter}{extension}")
    with open(xmp_file, "w", encoding="UTF-8") as fptr:
        fptr.write(xmp.serialize_to_str(omit_packet_wrapper=True))


# __END__
