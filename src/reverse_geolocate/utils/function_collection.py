"""
Collection of various functions
"""

import glob
import os
import re
from argparse import Namespace
from math import ceil
from shutil import get_terminal_size


# MARK: check overwrite
def check_overwrite(data: str, key: str, field_controls: list[str] | None, args: Namespace) -> bool:
    """
    checks with field control flags if given data for key should be written
        1) no field controls: write only if data is not set
        2) only "overwrite": write always (data set or not)
        3) only field keys: write only those keys and only if data is not set
        4) field keys + "overwrite": write only those keys, data set or not

    Args:
        data (str): current value of the field
        key (str): xmp key, eg "City", compared case insensitive to the field controls
        field_controls (list[str] | None): -f/--field values from args (None if not set)
        args (Namespace): command line arguments (for debug flag)

    Returns:
        bool: True if the data for the key can be written
    """
    # set, so duplicate -f flags (eg -f overwrite -f overwrite) do not change the result
    controls = set(field_controls or [])
    overwrite = "overwrite" in controls
    # selected fields without the overwrite flag
    field_keys = controls - {"overwrite"}
    key_lower = key.lower()
    # key is selected if no fields are restricted or the key is one of them
    key_selected = not field_keys or key_lower in field_keys
    status = key_selected and (not data or overwrite)
    if args.debug:
        print(
            f"Data set: {'YES' if data else 'NO'}, "
            f"Key: {key_lower}, "
            f"Field Controls: {sorted(field_keys)}, "
            f"Overwrite: {'OVERWRITE' if overwrite else 'NOT OVERWRITE'}, "
            f"Key in Field Controls: {'KEY OK' if key_selected else 'KEY NOT MATCHING'}, "
            f"OVERWRITE: {status}"
        )
    return status


# def print_header(header, lines=0, header_line=0):
#     """
#     prints header line and header seperator line

#     Args:
#         header (str): header string
#         lines (int, optional): line counter. Defaults to 0.
#         header_line (int, optional): print header counter grigger. Defaults to 0.

#     Returns:
#         int: line counter +1
#     """
#     global page_no
#     if lines == header_line:
#         # add one to the pages shown and reset the lines to start new page
#         page_no += 1
#         lines = 0
#         # print header
#         print(f"{header}")
#     lines += 1
#     return lines


# MARK: file sort number
def file_sort_number(file: str) -> int:
    """
    gets the BK number for sorting in the file list
    the match is case insensitive (.BK.1.xmp, .BK.1.XMP, .bk.1.xmp, ...)

    Args:
        file (str): file name

    Returns:
        int: number found in the BK string or 0 for none
    """
    match = re.match(r".*\.BK\.(\d+)\.xmp$", file, flags=re.IGNORECASE)
    return int(match.group(1)) if match is not None else 0


# MARK: output list width adjust
def output_list_width_adjust(args: Namespace) -> dict[str, int]:
    """
    adjusts the size for the format length for the list output

    Args:
        args (Namespace): arguments

    Returns:
        dict[str, int]: format_length dictionary
    """
    # various string lengths
    format_length: dict[str, int] = {
        "filename": 35,
        "latitude": 18,
        "longitude": 18,
        "code": 4,
        "country": 15,
        "state": 18,
        "city": 20,
        "location": 25,
        "path": 40,
    }
    if args.compact_view:
        reduce_percent = 40
        # all formats are reduced to a mininum, we cut % off
        for format_key in [
            "filename",
            "latitude",
            "longitude",
            "country",
            "state",
            "city",
            "location",
            "path",
        ]:
            format_length[format_key] = ceil(
                format_length[format_key] - ((format_length[format_key] / 100) * reduce_percent)
            )
    else:
        # minimum resize size for a column
        resize_width_min = 4
        # the resize percent
        # start with 10, then increase until we reach max
        resize_percent_min = 10
        resize_percent_max = 50
        # abort flag so we can break out of the second loop too
        abort = False
        # formay key order, in which order the elements will be resized
        format_key_order = []
        # resize flag: 0 no, 1: make bigger, -1: make smaller
        # change sizes for print based on terminal size
        # NOTE: in screen or term this data might NOT be correct
        # Current size needs the in between and left/right space data
        current_columns = sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2
        if current_columns < get_terminal_size().columns:
            resize = 1
            format_key_order = ["path", "location", "state", "city", "country", "filename"]
        else:
            resize = -1
            format_key_order = [
                "latitude",
                "longitude",
                "path",
                "country",
                "state",
                "city",
                "location",
                "filename",
            ]
        # if we have no auto adjust
        if args.no_autoadjust:
            # warningn if screen is too small
            if resize == -1:
                print("[!!!] Screen layout might be skewed. Increase Terminal width")
        else:
            for resize_percent in range(resize_percent_min, resize_percent_max, 10):
                for format_key in format_key_order:
                    resize_width = (format_length[format_key] / 100) * resize_percent
                    # if we down size, make it negative
                    if resize == -1:
                        resize_width *= -1
                    resize_width = ceil(format_length[format_key] + resize_width)
                    # in case too small, keep old one
                    format_length[format_key] = (
                        resize_width if resize_width > resize_width_min else format_length[format_key]
                    )
                    # calc new width for check if we can abort
                    current_columns = sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2
                    if (resize == 1 and current_columns >= get_terminal_size().columns) or (
                        resize == -1 and current_columns < get_terminal_size().columns
                    ):
                        # check that we are not OVER but one under
                        # growing: always cut the path back, so we end one under the terminal width
                        # shrinking: widen the path to one under, if it stays above the minimum width
                        width_up = get_terminal_size().columns - current_columns - 1
                        if (resize == 1 and width_up < 0) or (
                            (resize == -1 and width_up != 0) and format_length["path"] + width_up >= resize_width_min
                        ):
                            format_length["path"] += width_up
                        abort = True
                        break
                if abort:
                    break
            # warn if not at least one under the terminal width (same target as above)
            if sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2 >= get_terminal_size().columns:
                print("[!!!] Screen layout might be skewed. Increase Terminal width")
    return format_length


# MARK: get backup file counter
def get_backup_file_counter(xmp_file: str, args: Namespace) -> int:
    """
    get the next free backup file counter for <name>.BK.<n>.<ext>

    Args:
        xmp_file (str): xmp file name (with path)
        args (Namespace): command line arguments (for debug flag)

    Returns:
        int: next counter to be used for backup, highest existing + 1, or 1 if none exist
    """
    path, file_name = os.path.split(xmp_file)
    stem, extension = os.path.splitext(file_name)
    # escape the file name, so glob special characters (eg "[", "*", "?") in it are matched literally
    # use the extension of the file itself, glob is case sensitive (.xmp vs .XMP)
    bk_pattern = os.path.join(glob.escape(path), f"{glob.escape(stem)}.BK.*{glob.escape(extension)}")
    # BK.1, etc -> get the number
    bk_number_re = re.compile(rf"\.BK\.(\d+){re.escape(extension)}$")
    bk_numbers = [
        int(match.group(1)) for bk_file in glob.glob(bk_pattern) if (match := bk_number_re.search(bk_file)) is not None
    ]
    bk_file_counter = max(bk_numbers, default=0) + 1
    if args.debug:
        print(f"#### **** File: {xmp_file}, Backups: {sorted(bk_numbers)}, Counter: {bk_file_counter}")
    # return the next correct number for backup
    return bk_file_counter


# __END__
