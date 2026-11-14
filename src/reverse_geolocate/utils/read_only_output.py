"""
read only output for listing with header and page numbers
"""

from math import ceil
from typing import Any

from reverse_geolocate.utils.long_lat import (
    convert_dms_to_lat,
    convert_dms_to_long,
)
from reverse_geolocate.utils.string_helpers import format_len, shorten_path, shorten_string


# MARK: Read only output
class ReadOnlyOutput:
    """
    for read only listing: prints the header block with page numbers
    at the start and again after every header_print_line data lines
    """

    def __init__(
        self,
        header_template: str,
        line_template: str,
        format_length: dict[str, int],
        max_pages: int,
        header_print_line: int,
    ) -> None:
        """
        Args:
            header_template (str): header block, with {page_no} and {page_all} placeholders
            max_pages (int): total pages, for the page_all placeholder
            header_print_line (int): reprint the header after this many data lines, 0 for never
        """
        self.header_template: str = header_template
        self.line_template: str = line_template
        self.format_length: dict[str, int] = format_length
        self.page_all: int = max(1, max_pages)
        self.header_print: int = header_print_line
        # page currently shown, 0 = no header printed yet
        self.page_no: int = 0
        # data lines printed on the current page
        self.lines: int = 0

    def print_header(self) -> None:
        """
        prints the header block for the next page and starts a new page
        """
        self.page_no += 1
        self.lines = 0
        print(self.header_template.format(page_no=self.page_no, page_all=self.page_all))

    def next_line(self) -> None:
        """
        call before each data line, prints the header if this is the first line
        or the current page is full
        """
        if self.page_no == 0 or (self.header_print > 0 and self.lines >= self.header_print):
            self.print_header()
        self.lines += 1

    def print_line(self, xmp_file: str, data_set: dict[str, Any]) -> None:
        """
        prints a data line, calls next_line() to check if header needs to be printed first

        Args:
            line (str): data line to print
        """
        # missing (empty) or malformed GPS data would raise a ValueError, show it as empty
        try:
            latitude = str(convert_dms_to_lat(data_set["GPSLatitude"]))
        except ValueError:
            latitude = ""
        try:
            longitude = str(convert_dms_to_long(data_set["GPSLongitude"]))
        except ValueError:
            longitude = ""
        print(
            self.line_template.format(
                # for all possible non latin fields we do adjust
                # if it has double byte characters inside
                filenamelen=format_len(
                    shorten_path(xmp_file, self.format_length["filename"], file_only=True),
                    self.format_length["filename"],
                ),
                countrylen=format_len(
                    shorten_string(data_set["Country"], width=self.format_length["country"]),
                    self.format_length["country"],
                ),
                statelen=format_len(
                    shorten_string(data_set["State"], width=self.format_length["state"]),
                    self.format_length["state"],
                ),
                citylen=format_len(
                    shorten_string(data_set["City"], width=self.format_length["city"]),
                    self.format_length["city"],
                ),
                locationlen=format_len(
                    shorten_string(data_set["Location"], width=self.format_length["location"]),
                    self.format_length["location"],
                ),
                pathlen=format_len(
                    shorten_path(xmp_file, self.format_length["path"], path_only=True),
                    self.format_length["path"],
                ),
            ).format(
                # shorten from the left
                filename=shorten_path(xmp_file, self.format_length["filename"], file_only=True),
                # cut off from the right
                latitude=latitude[: self.format_length["latitude"]],
                longitude=longitude[: self.format_length["longitude"]],
                # is only 2 chars
                code=data_set["CountryCode"][:2].center(4),
                # shorten from the right
                country=shorten_string(data_set["Country"], width=self.format_length["country"]),
                state=shorten_string(data_set["State"], width=self.format_length["state"]),
                city=shorten_string(data_set["City"], width=self.format_length["city"]),
                location=shorten_string(data_set["Location"], width=self.format_length["location"]),
                path=shorten_path(xmp_file, self.format_length["path"], path_only=True),
            )
        )


# MARK: create read only output
def create_read_only_output(format_length: dict[str, int], file_count: int, filtered: bool) -> ReadOnlyOutput:
    """
    builds the line template and the header block for the read only list

    Args:
        format_length (dict[str, int]): column widths (see output_list_width_adjust)
        file_count (int): number of files, for the page count
        filtered (bool): unset filters are used, fewer files may be listed,
            the page count is only a maximum (marked with "?")

    Returns:
        ReadOnlyOutput: output with the header and line templates
    """
    # after how many lines do we reprint the header
    header_repeat = 50
    # how many pages will we have
    page_all = ceil(file_count / header_repeat)
    # current page number
    # page_no = 1
    # the formatted line for the output, formatted in two passes:
    # 1st .format(): fills in the {...len} column widths
    #   ({{ }} => { } so the data placeholders survive this pass)
    # 2nd .format(): fills in the data (filename, latitude, ...)
    # NOTE: only the f-string parts below are evaluated at build time,
    # the plain string parts must not be double escaped
    format_line = (
        " {{filename:<{filenamelen}}} | "
        "{{latitude:>"
        f"{format_length['latitude']}"
        "}} | "
        "{{longitude:>"
        f"{format_length['longitude']}"
        "}} | "
        "{{code:<"
        f"{format_length['code']}"
        "}} | "
        "{{country:<{countrylen}}} | "
        "{{state:<{statelen}}} | "
        "{{city:<{citylen}}} | "
        "{{location:<{locationlen}}} | "
        "{{path:<{pathlen}}}"
    )
    # header line format:
    # blank line
    # header title
    # seperator line
    # pre replace path length before we add the header titles
    header_line_2 = format_line.format(
        filenamelen=format_length["filename"],
        countrylen=format_length["country"],
        statelen=format_length["state"],
        citylen=format_length["city"],
        locationlen=format_length["location"],
        pathlen=format_length["path"],
    ).format(  # the header title line
        filename="File"[: format_length["filename"]],
        latitude="Latitude"[: format_length["latitude"]],
        longitude="Longitude"[: format_length["longitude"]],
        code="Code",
        country="Country"[: format_length["country"]],
        state="State"[: format_length["state"]],
        city="City"[: format_length["city"]],
        location="Location"[: format_length["location"]],
        path="Path"[: format_length["path"]],
    )
    header_line_3 = (
        f"{'-' * (format_length['filename'] + 2)}+"
        f"{'-' * (format_length['latitude'] + 2)}+"
        f"{'-' * (format_length['longitude'] + 2)}+"
        f"{'-' * (format_length['code'] + 2)}+"
        f"{'-' * (format_length['country'] + 2)}+"
        f"{'-' * (format_length['state'] + 2)}+"
        f"{'-' * (format_length['city'] + 2)}+"
        f"{'-' * (format_length['location'] + 2)}+"
        f"{'-' * (format_length['path'] + 2)}"
    )
    # header block: page line, title line, separator line
    # title and separator are already formatted, escape any braces for the page format call
    # with the unset filters fewer files than found may be listed,
    # so the total page count is only a maximum, mark it with "?"
    page_all_marker = "?" if filtered else ""
    header_line = (
        # can later be set to something else, eg page numbers
        "> Page {page_no:,}/{page_all:,}"
        + page_all_marker
        + "\n"
        + header_line_2.replace("{", "{{").replace("}", "}}")
        + "\n"
        + header_line_3
    )
    return ReadOnlyOutput(
        header_line,
        format_line,
        format_length,
        page_all,
        header_repeat,
    )


# MARK: read only filter
def matches_read_only_filter(data_set: dict[str, str], unset_only: bool, unset_gps_only: bool) -> bool:
    """
    checks if a data set is listed with the unset filters (both set: either one matches)

    Args:
        data_set (dict[str, str]): XMP data set
        unset_only (bool): only list if any field (GPS included) is empty
        unset_gps_only (bool): only list if GPS latitude or longitude is empty

    Returns:
        bool: True if the data set is listed
    """
    if not unset_only and not unset_gps_only:
        return True
    return (unset_only and "" in data_set.values()) or (
        unset_gps_only and (not data_set["GPSLatitude"] or not data_set["GPSLongitude"])
    )
