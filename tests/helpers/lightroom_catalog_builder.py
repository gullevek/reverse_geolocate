"""
builds a minimal Lightroom catalog (.lrcat) for tests, with only the tables and columns used by the script
"""

import os
import sqlite3
from pathlib import Path
from typing import TypedDict, Unpack


class LocationFields(TypedDict, total=False):
    """location keyword arguments for LightroomCatalogBuilder.add_image (data set keys)"""

    Location: str
    City: str
    State: str
    Country: str
    CountryCode: str


# MARK: Lightroom catalog
LIGHTROOM_SCHEMA = """
CREATE TABLE Adobe_images (id_local INTEGER PRIMARY KEY, rootFile INTEGER);
CREATE TABLE AgLibraryFile (id_local INTEGER PRIMARY KEY, baseName TEXT, folder INTEGER, originalFilename TEXT);
CREATE TABLE AgLibraryFolder (id_local INTEGER PRIMARY KEY, rootFolder INTEGER, pathFromRoot TEXT);
CREATE TABLE AgLibraryRootFolder (id_local INTEGER PRIMARY KEY, absolutePath TEXT, name TEXT);
CREATE TABLE AgHarvestedExifMetadata (image INTEGER, gpsLatitude REAL, gpsLongitude REAL);
CREATE TABLE AgHarvestedIptcMetadata (
    image INTEGER, locationDataOrigination TEXT,
    locationRef INTEGER, cityRef INTEGER, stateRef INTEGER, countryRef INTEGER, isoCountryCodeRef INTEGER
);
CREATE TABLE AgInternedIptcLocation (id_local INTEGER PRIMARY KEY, value TEXT);
CREATE TABLE AgInternedIptcCity (id_local INTEGER PRIMARY KEY, value TEXT);
CREATE TABLE AgInternedIptcState (id_local INTEGER PRIMARY KEY, value TEXT);
CREATE TABLE AgInternedIptcCountry (id_local INTEGER PRIMARY KEY, value TEXT);
CREATE TABLE AgInternedIptcIsoCountryCode (id_local INTEGER PRIMARY KEY, value TEXT);
"""
# data set key -> interned value table, metadata reference column
LIGHTROOM_LOCATION_TABLES = {
    "Location": ("AgInternedIptcLocation", "locationRef"),
    "City": ("AgInternedIptcCity", "cityRef"),
    "State": ("AgInternedIptcState", "stateRef"),
    "Country": ("AgInternedIptcCountry", "countryRef"),
    "CountryCode": ("AgInternedIptcIsoCountryCode", "isoCountryCodeRef"),
}


class LightroomCatalogBuilder:
    """
    minimal Lightroom catalog (.lrcat) with only the tables and columns used by the script
    each image gets its own root folder (parent of the XMP folder) and folder entry
    """

    def __init__(self, folder: Path, name: str = "catalog.lrcat") -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self.path = folder / name
        with sqlite3.connect(self.path) as connection:
            connection.executescript(LIGHTROOM_SCHEMA)
        connection.close()

    def add_image(
        self,
        xmp_file: Path,
        gps_latitude: float | None = None,
        gps_longitude: float | None = None,
        **location: Unpack[LocationFields],
    ) -> None:
        """
        adds an image for an XMP file: base name and folder from the XMP file path,
        GPS as decimal numbers, location with the data set keys (Location, City, ...)
        """
        # Lightroom stores real paths, folders end with "/"
        folder = os.path.realpath(xmp_file.parent)
        root, folder_name = os.path.split(folder)
        with sqlite3.connect(self.path) as connection:
            root_id = connection.execute(
                "INSERT INTO AgLibraryRootFolder (absolutePath, name) VALUES (?, ?)",
                (f"{root.rstrip('/')}/", os.path.basename(root)),
            ).lastrowid
            folder_id = connection.execute(
                "INSERT INTO AgLibraryFolder (rootFolder, pathFromRoot) VALUES (?, ?)",
                (root_id, f"{folder_name}/"),
            ).lastrowid
            file_id = connection.execute(
                "INSERT INTO AgLibraryFile (baseName, folder, originalFilename) VALUES (?, ?, ?)",
                (xmp_file.stem, folder_id, f"{xmp_file.stem}.RAF"),
            ).lastrowid
            image_id = connection.execute("INSERT INTO Adobe_images (rootFile) VALUES (?)", (file_id,)).lastrowid
            connection.execute(
                "INSERT INTO AgHarvestedExifMetadata (image, gpsLatitude, gpsLongitude) VALUES (?, ?, ?)",
                (image_id, gps_latitude, gps_longitude),
            )
            references: dict[str, int | None] = {}
            for key, (table, column) in LIGHTROOM_LOCATION_TABLES.items():
                references[column] = None
                value = location.get(key, "")
                if value:
                    references[column] = connection.execute(
                        # fixed table names from LIGHTROOM_LOCATION_TABLES
                        f"INSERT INTO {table} (value) VALUES (?)",
                        (value,),
                    ).lastrowid
            connection.execute(
                "INSERT INTO AgHarvestedIptcMetadata (image, locationDataOrigination, "
                "locationRef, cityRef, stateRef, countryRef, isoCountryCodeRef) "
                "VALUES (:image, 'setByUser', :locationRef, :cityRef, :stateRef, :countryRef, :isoCountryCodeRef)",
                {"image": image_id, **references},
            )
        connection.close()


# __END__
