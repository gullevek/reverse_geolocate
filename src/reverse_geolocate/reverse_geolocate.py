#!/usr/bin/env python3

"""
AUTHOR : Clemens Schwaighofer
DATE   : 2018/2/20
LICENSE: GPLv3
DESC   :
Set the reverse Geo location (name) from Lat/Long data in XMP files
in a lightroom catalogue
 * tries to get pre-set geo location from LR catalog
 * if not found tries to get data from Google
 * all data is translated into English with long vowl system (aka ou or oo is ō)
MUST HAVE: Python XMP Toolkit (http://python-xmp-toolkit.readthedocs.io/)
"""

import os
import sys
from argparse import Namespace
from pathlib import Path
from typing import Literal

# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import ExempiLoadError, XMPMeta

from reverse_geolocate.setup.arguments import ArgumentSetup
from reverse_geolocate.setup.configurate import read_config
from reverse_geolocate.utils.file_collection import collect_work_files
from reverse_geolocate.utils.function_collection import (
    check_overwrite,
    get_display_path,
    normalize_path,
    output_list_width_adjust,
)
from reverse_geolocate.utils.geolocate import reverse_geolocate
from reverse_geolocate.utils.lightroom import LOCATION_KEYS, LightroomCatalog, LightroomError, merge_lightroom_data
from reverse_geolocate.utils.location_cache import LocationCache
from reverse_geolocate.utils.long_lat import long_lat_reg
from reverse_geolocate.utils.read_only_output import create_read_only_output, matches_read_only_filter
from reverse_geolocate.utils.statistics import RunStatistics, print_statistics
from reverse_geolocate.utils.xmp_data import XMP_FIELDS, read_xmp_data_set, write_xmp_file

MapType = Literal["google", "openstreetmap"]


##############################################################
# MARK: READ ONLY RUN
##############################################################


def run_read_only(
    xmp: XMPMeta, work_files: list[str], args: Namespace, statistics: RunStatistics, call_path: Path
) -> None:
    """
    lists the XMP data of the work files, nothing is written and no lookup is done

    Args:
        xmp (XMPMeta): XMP object, reused for all files
        work_files (list[str]): XMP files
        args (Namespace): command line arguments
        statistics (RunStatistics): counters, listed is updated
        call_path (Path): normalized folder the script is called from (for the debug output)
    """
    read_only_output = create_read_only_output(
        output_list_width_adjust(args),
        len(work_files),
        filtered=bool(args.unset_only or args.unset_gps_only),
    )
    read_only_output.print_header()
    if not work_files:
        print(f"{'[!!!] No files found':<60}")
    for xmp_file in work_files:
        if args.debug:
            print(f"---> {xmp_file} -> {get_display_path(xmp_file, call_path)}: ", end="")
        data_set = read_xmp_data_set(xmp, xmp_file, debug=bool(args.debug))
        # view only if list all or if data is unset
        if matches_read_only_filter(data_set, bool(args.unset_only), bool(args.unset_gps_only)):
            read_only_output.next_line()
            read_only_output.print_line(xmp_file, data_set)
            statistics.listed += 1


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
        xmp: XMPMeta,
        args: Namespace,
        map_type: MapType,
        lightroom: LightroomCatalog | None,
        statistics: RunStatistics,
    ) -> None:
        """
        Args:
            xmp (XMPMeta): XMP object, reused for all files
            args (Namespace): command line arguments
            map_type (MapType): map lookup service
            lightroom (LightroomCatalog | None): open Lightroom catalog or None
            statistics (RunStatistics): counters, updated for each file
        """
        self.xmp = xmp
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
        data_set = read_xmp_data_set(self.xmp, xmp_file, debug=bool(args.debug))
        # original data for checking if something changed
        data_set_original = data_set.copy()
        data_set, lightroom_data_ok = self.merge_lightroom(xmp_file, data_set)

        # anything unset (or forced overwrite) in the data set: map lookup
        has_unset = False
        for key in LOCATION_KEYS:
            if check_overwrite(data_set[key], key, args.field_controls, args):
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
                map_keys = self.apply_map_location(data_set, data_set_original, maps_location)
            else:
                print("(!) Could not get geo location data ", end="")
                lookup_failed = True
        elif args.debug:
            print(f"Lightroom data use: {self.lightroom is not None}, Lightroom data ok: {lightroom_data_ok}")

        # all changed values: from Lightroom (also GPS) and from the map lookup
        written_keys = self.set_changed_values(data_set, data_set_original)
        write_file = bool(written_keys)
        # only count new map lookups, cache hits are counted separately
        if map_keys and write_file and not from_cache:
            self.statistics.map += 1
        if written_keys - map_keys:
            self.statistics.lightroom += 1

        if write_file:
            if not args.test:
                write_xmp_file(self.xmp, xmp_file, backup=not args.no_xmp_backup, args=args)
            else:
                print(f"{xmp_file_print}: [TEST] Would write {data_set} {xmp_file}")
            print(f"{xmp_file_print}: [UPDATED FROM CACHE]" if from_cache else f"{xmp_file_print}: [UPDATED]")
            self.statistics.changed += 1
        # failed only if the lookup failed and there is nothing else (Lightroom) to write
        elif lookup_failed:
            print(f"{xmp_file_print}: [FAILED]")
            self.statistics.failed += 1
            self.statistics.failed_files.append(xmp_file)
        else:
            if args.verbose >= 1:
                print(f"{xmp_file_print}: [SKIP]")
            self.statistics.skipped += 1

    def merge_lightroom(self, xmp_file: str, data_set: dict[str, str]) -> tuple[dict[str, str], bool]:
        """
        fills empty data set fields from the Lightroom catalog (if used)

        Args:
            xmp_file (str): XMP file path
            data_set (dict[str, str]): XMP data set

        Returns:
            tuple[dict[str, str], bool]: data set with the Lightroom data, True if Lightroom data was found
        """
        if self.lightroom is None:
            return data_set, False
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
            return data_set, False
        return merge_lightroom_data(data_set, result.row, debug=bool(self.args.debug)), True

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
        self, data_set: dict[str, str], data_set_original: dict[str, str], maps_location: dict[str, str]
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

        Returns:
            set[str]: the location keys filled from the map lookup
        """
        map_keys: set[str] = set()
        for key in LOCATION_KEYS:
            if data_set[key] != data_set_original[key]:
                continue
            if (
                check_overwrite(data_set_original[key], key, self.args.field_controls, self.args)
                and maps_location[key]
                and maps_location[key] != data_set_original[key]
            ):
                data_set[key] = maps_location[key]
                map_keys.add(key)
        return map_keys

    def set_changed_values(self, data_set: dict[str, str], data_set_original: dict[str, str]) -> set[str]:
        """
        sets all changed values (that pass the overwrite check) in the XMP object

        Args:
            data_set (dict[str, str]): new data set
            data_set_original (dict[str, str]): data set as read from the XMP file

        Returns:
            set[str]: the keys set in the XMP object, empty if nothing to write
        """
        written_keys: set[str] = set()
        for key, value in data_set.items():
            if value != data_set_original[key] and check_overwrite(
                data_set_original[key], key, self.args.field_controls, self.args
            ):
                self.xmp.set_property(XMP_FIELDS[key], key, value)
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
    xmp: XMPMeta,
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
        xmp (XMPMeta): XMP object, reused for all files
        work_files (list[str]): XMP files
        args (Namespace): command line arguments
        map_type (MapType): map lookup service
        lightroom (LightroomCatalog | None): open Lightroom catalog or None
        statistics (RunStatistics): counters
        call_path (Path): normalized folder the script is called from, for the output paths
    """
    write_run = WriteRun(xmp, args, map_type, lightroom, statistics)
    for xmp_file in work_files:
        # path for the output: relative to the call folder, or as given if outside of it
        xmp_file_print = get_display_path(xmp_file, call_path)
        if args.debug:
            print(f"---> {xmp_file} -> {xmp_file_print}: ", end="")
        write_run.process_file(xmp_file, xmp_file_print)


##############################################################
# MARK: MAIN CODE
##############################################################


def main():
    """
    Main code run
    """
    try:
        args = ArgumentSetup().get_args()
    except SystemExit as e:
        # catch the SystemExit from the ArgumentParser and exit with the same code
        sys.exit(e.code)
    # set search map type
    map_type: MapType = "google" if not args.use_openstreetmap else "openstreetmap"
    args = read_config(args)
    # counters for the summary at the end
    statistics = RunStatistics()

    # MARK: open Lightroom
    # only if we have the lightroom folder, the catalog is opened read only
    lightroom: LightroomCatalog | None = None
    if args.lightroom_folder:
        try:
            # typed, args values are Any (ReadableDir action always stores a str)
            lightroom = LightroomCatalog.open(str(args.lightroom_folder), strict=bool(args.lightroom_strict))
        except LightroomError as e:
            print(f"(!) {e}")
            sys.exit(1)
        if args.debug:
            print(f"### USE Lightroom {lightroom.database}")

    try:
        # MARK: load XMPMeta data
        try:
            xmp = XMPMeta()
        except ExempiLoadError as e:
            print(f"(!) Exempi library not found or not working (must be installed separated): {e}")
            sys.exit(1)

        # MARK: collect files
        # typed copies of the include/exclude sources (args values are Any)
        # (WritableDirFolder action always stores a list of str)
        work_files = collect_work_files(
            [str(source) for source in args.xmp_sources], [str(source) for source in args.exclude_sources]
        )
        statistics.found = len(work_files)
        if args.debug:
            print(f"### Work Files {work_files}")

        # MARK: work on the files
        # the folder the script is called from, file paths inside it are printed relative to it
        call_path = normalize_path(os.getcwd())
        if args.read_only:
            run_read_only(xmp, work_files, args, statistics, call_path)
        else:
            run_write(xmp, work_files, args, map_type, lightroom, statistics, call_path)
    finally:
        # MARK: close Lightroom
        if lightroom is not None:
            lightroom.close()

    # MARK: print stats
    print_statistics(statistics, read_only=bool(args.read_only), use_lightroom=lightroom is not None)


##############################################################
# MARK: MAIN RUN
##############################################################

if __name__ == "__main__":
    main()

# __END__
