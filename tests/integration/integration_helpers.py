"""
helpers for the main() integration tests: XMP file writing/reading and output parsing
"""

import ast
import os
import sqlite3
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, cast

# sample XMP files from the repository (Tokyo, GPS set, no location data)
SAMPLE_FOLDER = Path(__file__).parents[2] / "data" / "orig"
SAMPLE_FILES = sorted(SAMPLE_FOLDER.glob("*.xmp"))
TOKYO_LAT = "35,40.4617426011N"
TOKYO_LONG = "139,44.3986917318E"
# terminal width for the read only list
TERMINAL_COLUMNS = 200

XMP_TEMPLATE = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/"
{attributes}/>
 </rdf:RDF>
</x:xmpmeta>
"""
# data set key -> XMP attribute name
XMP_ATTRIBUTES = {
    "GPSLatitude": "exif:GPSLatitude",
    "GPSLongitude": "exif:GPSLongitude",
    "Location": "Iptc4xmpCore:Location",
    "City": "photoshop:City",
    "State": "photoshop:State",
    "Country": "photoshop:Country",
    "CountryCode": "Iptc4xmpCore:CountryCode",
}


# MARK: fake lookup
class FakeLookup:
    """replaces reverse_geolocate() in main, records the calls"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        # default result for every lookup
        self.result: dict[str, str] = {
            "CountryCode": "JP",
            "Country": "Japan",
            "State": "Tokyo",
            "City": "Shibuya",
            "Location": "Jingumae",
            "status": "OK",
            "error_message": "",
        }
        # fields that replace the default result for a latitude (DMS string)
        self.by_latitude: dict[str, dict[str, str]] = {}

    def __call__(self, longitude: str, latitude: str, map_type: str, args: Any) -> dict[str, str]:
        self.calls.append({"longitude": longitude, "latitude": latitude, "map_type": map_type})
        return {**self.result, **self.by_latitude.get(latitude, {})}


# MARK: run result
@dataclass
class RunResult:
    out: str
    err: str
    exit_code: int | str | None = None
    lines: list[str] = field(default_factory=list[str])

    def work_files(self) -> list[str]:
        """the work file list from the debug output (needs --debug)"""
        for line in self.lines:
            if line.startswith("### Work Files "):
                return cast(list[str], ast.literal_eval(line.removeprefix("### Work Files ")))
        raise AssertionError("no work files debug line, run with --debug")

    def stat(self, name: str) -> int:
        """a number from the end statistics, eg stat("XMP Files found")"""
        for line in self.lines:
            if line.startswith(name) and ":" in line:
                return int(line.split(":", 1)[1].strip().replace(",", ""))
        raise AssertionError(f"no statistic line: {name}")

    def statuses(self) -> dict[str, str]:
        """write mode per file status: file name -> UPDATED, UPDATED FROM CACHE, FAILED, SKIP"""
        statuses: dict[str, str] = {}
        for line in self.lines:
            if not line.endswith("]") or ": [" not in line:
                continue
            path, status = line.rsplit(": [", 1)
            statuses[path.rsplit("/", 1)[-1]] = status.removesuffix("]")
        return statuses

    def table_rows(self) -> list[list[str]]:
        """data rows of the read only list, cells stripped"""
        rows: list[list[str]] = []
        for line in self.lines:
            if " | " not in line or line.startswith("---"):
                continue
            cells = [cell.strip() for cell in line.split(" | ")]
            if cells[0] == "File":
                continue
            rows.append(cells)
        return rows


# MARK: XMP files
def write_xmp(path: Path, **fields: str) -> Path:
    """
    writes a minimal XMP sidecar file, fields are the data set keys (GPSLatitude, City, ...)
    by default GPS is set to Tokyo, pass GPSLatitude="" / GPSLongitude="" to leave it out
    """
    values = {"GPSLatitude": TOKYO_LAT, "GPSLongitude": TOKYO_LONG, **fields}
    attributes = "".join(
        f'    {XMP_ATTRIBUTES[key]}="{escape(value, quote=True)}"\n' for key, value in values.items() if value
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(XMP_TEMPLATE.format(attributes=attributes), encoding="UTF-8")
    return path


def read_xmp(path: Path) -> dict[str, str]:
    """reads the data set fields back with Exempi, missing fields are empty"""
    # imported here, so this module can be imported without Exempi
    from libxmp import XMPMeta

    xmp = XMPMeta()
    xmp.parse_from_str(path.read_text(encoding="UTF-8"))
    namespaces = {
        "GPSLatitude": "http://ns.adobe.com/exif/1.0/",
        "GPSLongitude": "http://ns.adobe.com/exif/1.0/",
        "Location": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/",
        "City": "http://ns.adobe.com/photoshop/1.0/",
        "State": "http://ns.adobe.com/photoshop/1.0/",
        "Country": "http://ns.adobe.com/photoshop/1.0/",
        "CountryCode": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/",
    }
    return {
        key: (xmp.get_property(namespace, key) if xmp.does_property_exist(namespace, key) else "")
        for key, namespace in namespaces.items()
    }


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


class LightroomCatalog:
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
        **location: str,
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
                if location.get(key, ""):
                    references[column] = connection.execute(
                        # fixed table names from LIGHTROOM_LOCATION_TABLES
                        f"INSERT INTO {table} (value) VALUES (?)",
                        (location[key],),
                    ).lastrowid
            connection.execute(
                "INSERT INTO AgHarvestedIptcMetadata (image, locationDataOrigination, "
                "locationRef, cityRef, stateRef, countryRef, isoCountryCodeRef) "
                "VALUES (:image, 'setByUser', :locationRef, :cityRef, :stateRef, :countryRef, :isoCountryCodeRef)",
                {"image": image_id, **references},
            )
        connection.close()


# __END__
