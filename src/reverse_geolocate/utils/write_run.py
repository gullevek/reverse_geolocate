"""
Write run: sets the location data in the work files, for each file:
- read XMP -> merge Lightroom data (optional) -> map lookup for still unset fields (cached) -> write changes
"""

from argparse import Namespace
from pathlib import Path
from typing import Literal

from libxmp import XMPMeta

from reverse_geolocate.utils.function_collection import (
    check_overwrite,
    get_display_path,
)
from reverse_geolocate.utils.geolocate import reverse_geolocate
from reverse_geolocate.utils.lightroom import LOCATION_KEYS, LightroomCatalog, merge_lightroom_data
from reverse_geolocate.utils.location_cache import LocationCache
from reverse_geolocate.utils.long_lat import long_lat_reg
from reverse_geolocate.utils.statistics import RunStatistics
from reverse_geolocate.utils.xmp_data import (
    XMP_FIELDS,
    XmpReadError,
    read_xmp_file,
    write_xmp_file,
)

MapType = Literal["google", "openstreetmap"]

##############################################################
# MARK: WRITE RUN
##############################################################


class WriteRun:
    """
    sets the location data in the work files, for each file:
    read XMP -> merge Lightroom data (optional) -> map lookup for still unset fields (cached) -> write changes
    """

    def __init__(
        self,
        args: Namespace,
        map_type: MapType,
        lightroom: LightroomCatalog | None,
        statistics: RunStatistics,
    ) -> None:
        """
        Args:
            args (Namespace): command line arguments
            map_type (MapType): map lookup service
            lightroom (LightroomCatalog | None): open Lightroom catalog or None
            statistics (RunStatistics): counters, updated for each file
        """
        self.args = args
        self.map_type = map_type
        self.lightroom = lightroom
        self.statistics = statistics
        # cache to avoid double lookups for identical or close (fuzzy) coordinates
        # (DistanceValues action stores an int in meters)
        self.cache = LocationCache(float(args.fuzzy_distance) if args.fuzzy_distance else None)

    def process_file(self, xmp_file: str, xmp_file_print: str) -> None:
        """
        sets the location data in one XMP file, prints the status and updates the statistics

        Args:
            xmp_file (str): XMP file path
            xmp_file_print (str): XMP file path for the output
        """
        args = self.args
        try:
            xmp, data_set = read_xmp_file(xmp_file, debug=bool(args.debug))
        except XmpReadError as e:
            # damaged or unreadable file: failed, the run continues
            print(f"(!) Could not read XMP data ({e}) ", end="")
            self.fail(xmp_file_print)
            return
        # original data for checking if something changed
        data_set_original = data_set.copy()
        data_set, lightroom_keys, lightroom_data_ok = self.merge_lightroom(xmp_file, data_set)

        # anything unset (or forced overwrite) in the data set: map lookup
        # (fields set from Lightroom are done, Lightroom has priority over the lookup)
        has_unset = False
        for key in LOCATION_KEYS:
            if key not in lightroom_keys and check_overwrite(data_set[key], key, args.field_controls, args):
                has_unset = True
        # set if the map lookup was needed but could not give data
        lookup_failed = False
        from_cache = False
        # location keys filled from the map lookup (for the statistics)
        map_keys: set[str] = set()
        if has_unset and not has_valid_gps(data_set):
            print("(!) No valid GPS data for geo location lookup ", end="")
            lookup_failed = True
        elif has_unset:
            maps_location, from_cache = self.get_location(data_set)
            if args.debug:
                print(f"### Map Location ({self.map_type}): {maps_location}")
            # must have at least the country set to write anything back
            if maps_location["Country"]:
                map_keys = self.apply_map_location(data_set, data_set_original, maps_location, lightroom_keys)
            else:
                print("(!) Could not get geo location data ", end="")
                lookup_failed = True
        elif args.debug:
            print(f"Lightroom data use: {self.lightroom is not None}, Lightroom data ok: {lightroom_data_ok}")

        # all changed values: from Lightroom (also GPS) and from the map lookup
        written_keys = self.set_changed_values(xmp, data_set, data_set_original)
        write_file = bool(written_keys)
        # only count new map lookups, cache hits are counted separately
        if map_keys and write_file and not from_cache:
            self.statistics.map += 1
        if written_keys - map_keys:
            self.statistics.lightroom += 1

        if write_file:
            if not args.test:
                write_xmp_file(xmp, xmp_file, backup=not args.no_xmp_backup, args=args)
            else:
                print(f"{xmp_file_print}: [TEST] Would write {data_set} {xmp_file}")
            print(f"{xmp_file_print}: [UPDATED FROM CACHE]" if from_cache else f"{xmp_file_print}: [UPDATED]")
            self.statistics.changed += 1
        # failed only if the lookup failed and there is nothing else (Lightroom) to write
        elif lookup_failed:
            self.fail(xmp_file_print)
        else:
            if args.verbose >= 1:
                print(f"{xmp_file_print}: [SKIP]")
            self.statistics.skipped += 1

    def fail(self, xmp_file_print: str) -> None:
        """
        prints the failed status, counts the file as failed and keeps it for the list at the end

        Args:
            xmp_file_print (str): XMP file path for the output
        """
        print(f"{xmp_file_print}: [FAILED]")
        self.statistics.failed += 1
        self.statistics.failed_files.append(xmp_file_print)

    def merge_lightroom(self, xmp_file: str, data_set: dict[str, str]) -> tuple[dict[str, str], set[str], bool]:
        """
        merges the Lightroom data into the data set (if used): fills empty fields,
        with overwrite (-f) also replaces the set location fields that may be overwritten

        Args:
            xmp_file (str): XMP file path
            data_set (dict[str, str]): XMP data set

        Returns:
            tuple[dict[str, str], set[str], bool]: data set with the Lightroom data,
                the location keys set from Lightroom, True if Lightroom data was found
        """
        if self.lightroom is None:
            return data_set, set(), False
        result = self.lightroom.find(xmp_file)
        if result.status == "many_found":
            # do not use the data, we found more than one image
            print("(!) Lightroom DB returned more than one row")
            self.statistics.lightroom_many_found += 1
        elif result.status == "not_found":
            print("(!) Could not get data from Lightroom DB")
            self.statistics.lightroom_not_found += 1
        if self.args.debug and result.row is not None:
            print(f"### LightroomDB: {tuple(result.row)} / {result.row.keys()}")
        if result.status != "found" or result.row is None:
            return data_set, set(), False
        # set location fields that may be overwritten (-f overwrite, and selected if fields are given):
        # Lightroom has priority over the existing XMP values and over the lookup
        replace_keys = {
            key
            for key in LOCATION_KEYS
            if data_set[key] and check_overwrite(data_set[key], key, self.args.field_controls, self.args)
        }
        merged, lightroom_keys = merge_lightroom_data(
            data_set, result.row, replace_keys=replace_keys, debug=bool(self.args.debug)
        )
        return merged, lightroom_keys, True

    def get_location(self, data_set: dict[str, str]) -> tuple[dict[str, str], bool]:
        """
        location for the GPS coordinates: from the cache or the map lookup (then cached)

        Args:
            data_set (dict[str, str]): data set with valid GPS coordinates

        Returns:
            tuple[dict[str, str], bool]: location, True if it came from the cache
        """
        longitude, latitude = data_set["GPSLongitude"], data_set["GPSLatitude"]
        hit = self.cache.get(longitude, latitude, debug=bool(self.args.debug))
        if hit is not None:
            self.statistics.cache += 1
            if hit.fuzzy:
                self.statistics.fuzzy_cache += 1
            return hit.location, True
        # get location from maps (google or openstreetmap)
        location = reverse_geolocate(longitude=longitude, latitude=latitude, map_type=self.map_type, args=self.args)
        self.cache.add(longitude, latitude, location)
        return location, False

    def apply_map_location(
        self,
        data_set: dict[str, str],
        data_set_original: dict[str, str],
        maps_location: dict[str, str],
        lightroom_keys: set[str],
    ) -> set[str]:
        """
        fills the data set from the map lookup:
        - Lightroom data has priority, only fields Lightroom did not set are filled
        - only if the overwrite check passes and the value changes
            (overwrite with the same value must not write the file or create a backup)
        - an empty value from the lookup never replaces (clears) an existing value

        Args:
            data_set (dict[str, str]): data set (with Lightroom data), changed in place
            data_set_original (dict[str, str]): data set as read from the XMP file
            maps_location (dict[str, str]): location from the map lookup
            lightroom_keys (set[str]): location keys set from Lightroom (not changed by the lookup)

        Returns:
            set[str]: the location keys filled from the map lookup
        """
        map_keys: set[str] = set()
        for key in LOCATION_KEYS:
            if key in lightroom_keys:
                continue
            if (
                check_overwrite(data_set_original[key], key, self.args.field_controls, self.args)
                and maps_location[key]
                and maps_location[key] != data_set_original[key]
            ):
                data_set[key] = maps_location[key]
                map_keys.add(key)
        return map_keys

    def set_changed_values(self, xmp: XMPMeta, data_set: dict[str, str], data_set_original: dict[str, str]) -> set[str]:
        """
        sets all changed values in the XMP object:
        - location fields only if they pass the overwrite check (-f field controls)
        - GPS is not selectable with -f: missing GPS (only filled from Lightroom, never replaced)
            is always written, so location data is never written without the coordinates it is based on

        Args:
            xmp (XMPMeta): XMP object of the file
            data_set (dict[str, str]): new data set
            data_set_original (dict[str, str]): data set as read from the XMP file

        Returns:
            set[str]: the keys set in the XMP object, empty if nothing to write
        """
        written_keys: set[str] = set()
        for key, value in data_set.items():
            if value == data_set_original[key]:
                continue
            if key in LOCATION_KEYS and not check_overwrite(
                data_set_original[key], key, self.args.field_controls, self.args
            ):
                continue
            xmp.set_property(XMP_FIELDS[key], key, value)
            written_keys.add(key)
        return written_keys


def has_valid_gps(data_set: dict[str, str]) -> bool:
    """
    a map lookup needs valid GPS data, missing (empty) or malformed
    coordinates would raise a ValueError in the distance/geolocate calls

    Args:
        data_set (dict[str, str]): data set

    Returns:
        bool: True if latitude and longitude are valid DMS values
    """
    try:
        long_lat_reg(longitude=data_set["GPSLongitude"], latitude=data_set["GPSLatitude"])
    except ValueError:
        return False
    return True


def run_write(
    work_files: list[str],
    args: Namespace,
    map_type: MapType,
    lightroom: LightroomCatalog | None,
    statistics: RunStatistics,
    call_path: Path,
) -> None:
    """
    sets the location data in all work files (see WriteRun)

    Args:
        work_files (list[str]): XMP files
        args (Namespace): command line arguments
        map_type (MapType): map lookup service
        lightroom (LightroomCatalog | None): open Lightroom catalog or None
        statistics (RunStatistics): counters
        call_path (Path): normalized folder the script is called from, for the output paths

    Raises:
        XmpWriteError: an XMP file could not be written (critical, the run must stop)
    """
    write_run = WriteRun(args, map_type, lightroom, statistics)
    for xmp_file in work_files:
        # path for the output: relative to the call folder, or as given if outside of it
        xmp_file_print = get_display_path(xmp_file, call_path)
        if args.debug:
            print(f"---> {xmp_file} -> {xmp_file_print}: ", end="")
        write_run.process_file(xmp_file, xmp_file_print)


# __END__
