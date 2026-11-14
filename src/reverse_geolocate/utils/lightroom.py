"""
Lightroom catalog (.lrcat, SQLite) access: find and open the catalog (read only),
find the data for an XMP file and merge it into the XMP data set
"""

import os
import sqlite3
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, cast

from reverse_geolocate.utils.long_lat import convert_lat_to_dms, convert_long_to_dms

# location keys in the data set, also the column names in the query
LOCATION_KEYS = ("Location", "City", "State", "Country", "CountryCode")

# query for one image by base name (file name without extension)
LIGHTROOM_QUERY = (
    "SELECT Adobe_images.id_local, AgLibraryFile.baseName, "
    "AgLibraryRootFolder.absolutePath, AgLibraryRootFolder.name as realtivePath, "
    "AgLibraryFolder.pathFromRoot, AgLibraryFile.originalFilename, "
    "AgHarvestedExifMetadata.gpsLatitude, AgHarvestedExifMetadata.gpsLongitude, "
    "AgHarvestedIptcMetadata.locationDataOrigination, "
    "AgInternedIptcLocation.value as Location, AgInternedIptcCity.value as City, "
    "AgInternedIptcState.value as State, AgInternedIptcCountry.value as Country, "
    "AgInternedIptcIsoCountryCode.value as CountryCode "
    "FROM AgLibraryFile, AgHarvestedExifMetadata, AgLibraryFolder, "
    "AgLibraryRootFolder, Adobe_images "
    "LEFT JOIN AgHarvestedIptcMetadata "
    "ON Adobe_images.id_local = AgHarvestedIptcMetadata.image "
    "LEFT JOIN AgInternedIptcLocation "
    "ON AgHarvestedIptcMetadata.locationRef = AgInternedIptcLocation.id_local "
    "LEFT JOIN AgInternedIptcCity "
    "ON AgHarvestedIptcMetadata.cityRef = AgInternedIptcCity.id_local "
    "LEFT JOIN AgInternedIptcState "
    "ON AgHarvestedIptcMetadata.stateRef = AgInternedIptcState.id_local "
    "LEFT JOIN AgInternedIptcCountry "
    "ON AgHarvestedIptcMetadata.countryRef = AgInternedIptcCountry.id_local "
    "LEFT JOIN AgInternedIptcIsoCountryCode "
    "ON AgHarvestedIptcMetadata.isoCountryCodeRef = AgInternedIptcIsoCountryCode.id_local "
    "WHERE Adobe_images.rootFile = AgLibraryFile.id_local "
    "AND Adobe_images.id_local = AgHarvestedExifMetadata.image "
    "AND AgLibraryFile.folder = AgLibraryFolder.id_local "
    "AND AgLibraryFolder.rootFolder = AgLibraryRootFolder.id_local "
    # the base name in both Unicode forms (NFC and NFD), see LightroomCatalog.find
    "AND AgLibraryFile.baseName IN (?, ?)"
)

LightroomStatus = Literal["found", "not_found", "many_found"]


class LightroomError(Exception):
    """the Lightroom catalog could not be found or opened"""


@dataclass(frozen=True)
class LightroomResult:
    """result of a catalog search for one XMP file"""

    # found: exactly one image, not_found: none, many_found: more than one (not used)
    status: LightroomStatus
    # the first image found (also for many_found, for the debug output), None if not found
    row: sqlite3.Row | None = None


def find_catalog_file(folder: str) -> str | None:
    """
    the first Lightroom catalog file in a folder: sorted by name, extension .lrcat in any case,
    only files (Lightroom side folders like "x.lrcat-data" or "x.lrdata" are not used)

    Args:
        folder (str): Lightroom catalog folder

    Returns:
        str | None: path of the catalog file or None if there is none
    """
    for file in sorted(os.listdir(folder)):
        file_path = os.path.join(folder, file)
        if file.lower().endswith(".lrcat") and os.path.isfile(file_path):
            return file_path
    return None


class LightroomCatalog:
    """
    a Lightroom catalog, always opened read only
    use LightroomCatalog.open(folder), can be used as a context manager (closes the catalog)
    """

    def __init__(self, database: str, connection: sqlite3.Connection, strict: bool = False) -> None:
        """
        Args:
            database (str): catalog file path
            connection (sqlite3.Connection): open (read only) connection
            strict (bool, optional): the folder of the XMP file must match too. Defaults to False.
        """
        self.database = database
        self.strict = strict
        self.connection = connection
        # access the columns by name
        self.connection.row_factory = sqlite3.Row

    @classmethod
    def open(cls, folder: str, strict: bool = False) -> Self:
        """
        finds the catalog in the folder (see find_catalog_file) and opens it read only

        Args:
            folder (str): Lightroom catalog folder
            strict (bool, optional): the folder of the XMP file must match too. Defaults to False.

        Raises:
            LightroomError: no catalog in the folder or it can not be opened

        Returns:
            LightroomCatalog: the open catalog
        """
        database = find_catalog_file(folder)
        if database is None:
            raise LightroomError(f"We could not find a lrcat file in the given lightroom folder: {folder}")
        try:
            # always open read only, the catalog must never be changed
            # (URI, so special characters in the path are escaped)
            connection = sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error as e:
            raise LightroomError(f"Could not open the Lightroom catalog {database}: {e}") from e
        return cls(database, connection, strict)

    def find(self, xmp_file: str) -> LightroomResult:
        """
        searches the image for an XMP file by the base name (and the folder if strict)

        names with accents can be stored decomposed (NFD, eg "u" + combining "¨") or composed (NFC, "ü"),
        in the file system and in the catalog, both forms are found

        Args:
            xmp_file (str): XMP file path

        Returns:
            LightroomResult: status and the image data
        """
        # base file name without extension, in both Unicode forms
        # (exact matches, so the catalog index on the base name is used)
        base_name = os.path.splitext(os.path.basename(xmp_file))[0]
        params = [unicodedata.normalize("NFC", base_name), unicodedata.normalize("NFD", base_name)]
        # fetchall is untyped (Any), with row_factory = sqlite3.Row it is a list of Row
        rows = cast(list[sqlite3.Row], self.connection.execute(LIGHTROOM_QUERY, params).fetchall())
        if self.strict:
            # the image must be in the folder of the XMP file, compared in NFC
            # (only the few images with this base name are checked here)
            xmp_folder = folder_key(xmp_file)
            rows = [row for row in rows if folder_key_catalog(row) == xmp_folder]
        if not rows:
            return LightroomResult("not_found")
        if len(rows) > 1:
            return LightroomResult("many_found", rows[0])
        return LightroomResult("found", rows[0])

    def close(self) -> None:
        """close the catalog"""
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def folder_key(xmp_file: str) -> str:
    """
    folder of an XMP file as Lightroom stores it, for the strict check:
    absolute real path (symlinks resolved, no "//", "./", "../"), exactly one "/" at the end,
    Unicode NFC form

    Args:
        xmp_file (str): XMP file path

    Returns:
        str: folder path ending with "/"
    """
    # rstrip for the root folder "/"
    return unicodedata.normalize("NFC", f"{os.path.realpath(os.path.dirname(xmp_file)).rstrip('/')}/")


def folder_key_catalog(row: sqlite3.Row) -> str:
    """
    folder of a catalog image (root folder + folder from root), Unicode NFC form

    Args:
        row (sqlite3.Row): Lightroom image data

    Returns:
        str: folder path as stored in the catalog, ending with "/"
    """
    return unicodedata.normalize("NFC", f"{row['absolutePath']}{row['pathFromRoot']}")


def lightroom_gps(row: sqlite3.Row) -> tuple[float, float] | None:
    """
    the GPS coordinates of a Lightroom image, only as a complete pair:
    - no value (NULL) for latitude or longitude: not set, a half pair is never used
    - 0.0 is a valid coordinate (equator, prime meridian)
    - both exactly 0.0 ("Null Island") is not set: a common placeholder for missing GPS data

    Args:
        row (sqlite3.Row): Lightroom image data (see LightroomCatalog.find)

    Returns:
        tuple[float, float] | None: latitude, longitude or None if not set
    """
    latitude, longitude = row["gpsLatitude"], row["gpsLongitude"]
    if latitude is None or longitude is None:
        return None
    if float(latitude) == 0.0 and float(longitude) == 0.0:
        return None
    return float(latitude), float(longitude)


def merge_lightroom_data(
    data_set: dict[str, str],
    row: sqlite3.Row,
    replace_keys: Collection[str] = (),
    debug: bool = False,
) -> tuple[dict[str, str], set[str]]:
    """
    merges the Lightroom data into an XMP data set:
    - GPS: only empty fields are filled, existing GPS is never replaced,
      only a complete Lightroom GPS pair is used (see lightroom_gps)
    - location fields: empty fields are filled, set fields only if in replace_keys (overwrite)
    - empty Lightroom values are never used

    Args:
        data_set (dict[str, str]): XMP data set (GPSLatitude, GPSLongitude, Location, City, ...)
        row (sqlite3.Row): Lightroom image data (see LightroomCatalog.find)
        replace_keys (Collection[str], optional): location keys where a set value is replaced
            by the Lightroom value (-f overwrite). Defaults to ().
        debug (bool, optional): print the used Lightroom values. Defaults to False.

    Returns:
        tuple[dict[str, str], set[str]]: new data set with the Lightroom data,
            the location keys set from Lightroom (also if the value did not change)
    """
    merged = data_set.copy()
    # Lightroom stores GPS as decimal number (REAL),
    # the XMP uses the Degree,Min.Sec[NSEW] format
    gps = lightroom_gps(row)
    if gps is not None:
        latitude, longitude = gps
        if not merged["GPSLatitude"]:
            merged["GPSLatitude"] = convert_lat_to_dms(latitude)
        if not merged["GPSLongitude"]:
            merged["GPSLongitude"] = convert_long_to_dms(longitude)
    location_keys: set[str] = set()
    for key in LOCATION_KEYS:
        if row[key] and (not merged[key] or key in replace_keys):
            merged[key] = str(row[key])
            location_keys.add(key)
            if debug:
                print(f"### -> LR: {key} => {row[key]}")
    return merged, location_keys


# __END__
