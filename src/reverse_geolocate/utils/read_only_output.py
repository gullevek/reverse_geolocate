"""
read only output for listing with header and page numbers
"""

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
