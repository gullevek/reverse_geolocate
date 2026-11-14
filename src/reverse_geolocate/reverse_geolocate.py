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

# import textwrap
import os
import sqlite3
import sys
from math import ceil
from shutil import copyfile
from typing import Literal, cast

# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import ExempiLoadError, XMPMeta, consts

from reverse_geolocate.setup.arguments import ArgumentSetup
from reverse_geolocate.setup.configurate import read_config
from reverse_geolocate.utils.function_collection import (
    check_overwrite,
    get_backup_file_counter,
    output_list_width_adjust,
)
from reverse_geolocate.utils.geolocate import reverse_geolocate
from reverse_geolocate.utils.long_lat import (
    convert_lat_to_dms,
    convert_long_to_dms,
    get_distance,
)
from reverse_geolocate.utils.read_only_output import ReadOnlyOutput

# this is for looking up if string is non latin letters
# this is used by isLatin and onlyLatinChars
cache_latin_letters = {}


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
    map_type: Literal["google", "openstreetmap"] = "google" if not args.use_openstreetmap else "openstreetmap"

    # error flag for erros
    error = False
    args = read_config(args)

    # MARK: core settings
    # The XMP fields const lookup values
    # XML/XMP
    # READ:
    # exif:GPSLatitude
    # exif:GPSLongitude
    # READ for if filled
    # Iptc4xmpCore:Location
    # photoshop:City
    # photoshop:State
    # photoshop:Country
    # Iptc4xmpCore:CountryCode
    xmp_fields = {
        # EXIF GPSLat/Long are stored in Degree,Min.Sec[NESW] format
        "GPSLatitude": consts.XMP_NS_EXIF,
        "GPSLongitude": consts.XMP_NS_EXIF,
        "Location": consts.XMP_NS_IPTCCore,
        "City": consts.XMP_NS_Photoshop,
        "State": consts.XMP_NS_Photoshop,
        "Country": consts.XMP_NS_Photoshop,
        "CountryCode": consts.XMP_NS_IPTCCore,
    }
    # non lat/long fields (for loc loops)
    data_set_loc = ("Location", "City", "State", "Country", "CountryCode")
    # one xmp data set
    data_set: dict[str, str] = {
        "GPSLatitude": "",
        "GPSLongitude": "",
        "Location": "",
        "City": "",
        "State": "",
        "Country": "",
        "CountryCode": "",
    }
    # original set for compare (is constant unchanged)
    data_set_original: dict[str, str] = {}
    # cache set to avoid double lookups for identical Lat/Long
    # key: "<GPSLongitude>#<GPSLatitude>", value: location dict from reverse_geolocate
    data_cache: dict[str, dict[str, str]] = {}
    # work files, all files + folders we need to work on
    work_files: list[str] = []
    # all failed files
    failed_files: list[str] = []
    # use lightroom
    use_lightroom = False
    # path to lightroom database
    lightroom_database = ""
    # cursors & query
    query = ""
    cur = None
    lrdb = None
    # count variables
    count = {
        "all": 0,
        "listed": 0,
        "read": 0,
        "map": 0,
        "cache": 0,
        "fuzzy_cache": 0,
        "lightroom": 0,
        "changed": 0,
        "failed": 0,
        "skipped": 0,
        "not_found": 0,
        "many_found": 0,
    }

    # do lightroom stuff only if we have the lightroom folder
    if args.lightroom_folder:
        # query string for lightroom DB check
        query = (
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
            "AND AgLibraryFile.baseName = ? "
        )
        # absolutePath + pathFromRoot = path of XMP file - XMP file
        if args.lightroom_strict:
            query += " AND AgLibraryRootFolder.absolutePath || AgLibraryFolder.pathFromRoot = ?"

        # connect to LR database for reading
        # open the folder and look for the first lrcat file in there
        # typed, args values are Any and os.listdir(Any) gives an unknown type
        # (ReadableDir action always stores a str)
        lightroom_folder = str(args.lightroom_folder)
        for file in sorted(os.listdir(lightroom_folder)):
            if file.endswith(".lrcat"):
                lightroom_database = os.path.join(lightroom_folder, file)
                lrdb = sqlite3.connect(lightroom_database)
                # only use the first one, do not open (and leak) further connections
                break
        if not lightroom_database or not lrdb:
            print(
                "(!) We could not find a lrcat file in the given lightroom folder or "
                f"DB connection failed: {args.lightroom_folder}"
            )
            # flag for end
            error = True
        else:
            # set row so we can access each element by the name
            lrdb.row_factory = sqlite3.Row
            # set cursor
            cur = lrdb.cursor()
            # flag that we have Lightroom DB
            use_lightroom = True
        if args.debug:
            print(f"### USE Lightroom {use_lightroom}")

    # on error exit here
    if error:
        sys.exit(1)

    # MARK: load XMPMeta data
    # init the XML meta for handling
    try:
        xmp = XMPMeta()
    except ExempiLoadError as e:
        print(f"(!) Exempi library not found or not working (must be installed separated): {e}")
        sys.exit(1)

    # typed copies of the include/exclude sources (args values are Any)
    # (WritableDirFolder action always stores a list of str)
    xmp_sources: list[str] = [str(source) for source in args.xmp_sources]
    exclude_sources: list[str] = [str(source) for source in args.exclude_sources]
    # exclude folders without trailing separator, build once and not for every file
    exclude_folders: set[str] = {source.rstrip(os.sep) for source in exclude_sources}

    # MARK: read data
    # loop through the xmp_sources (folder or files)
    # and read in the XMP data for LAT/LONG, other data
    for xmp_file_source in xmp_sources:
        # if folder, open and loop
        # NOTE: we do check for folders in there, if there are we recourse traverse them
        # also check that folder is not in exclude list
        if os.path.isdir(xmp_file_source) and xmp_file_source.rstrip(os.sep) not in exclude_folders:
            # open folder and look for any .xmp files and push them into holding array
            # if there are folders, dive into them
            # or glob glob all .xmp files + directory
            for root, _, files in os.walk(xmp_file_source):
                for file in sorted(files):
                    # 1) but has no .BK. inside
                    # 2) file is not in exclude list
                    # 3) full folder is not in exclude list
                    file_path = os.path.join(root, file)
                    if (
                        file.endswith(".xmp")
                        and ".BK." not in file
                        and file_path not in exclude_sources
                        and root.rstrip(os.sep) not in exclude_folders
                        and file_path not in work_files
                    ):
                        work_files.append(file_path)
                        count["all"] += 1
        else:
            # not already added to list and not in the exclude list either
            if xmp_file_source not in work_files and xmp_file_source not in exclude_sources:
                work_files.append(xmp_file_source)
                count["all"] += 1

    # MARK: work on the files
    if args.debug:
        print(f"### Work Files {work_files}")
    format_line = ""
    header_line = ""
    format_length = {}
    read_only_output = None
    # if we have read only we print list format style
    if args.read_only:
        # adjust the output width for the list view
        format_length = output_list_width_adjust(args)

        # after how many lines do we reprint the header
        header_repeat = 50
        # how many pages will we have
        page_all = ceil(len(work_files) / header_repeat)
        # current page number
        # page_no = 1
        # the formatted line for the output
        # 4 {} => final replace: data (2 pre replaces)
        # 1 {} => length replace here
        format_line = (
            " {{{{filename:<{{filenamelen}}}}}} | "
            "{{{{latitude:>"
            f"{format_length['latitude']}"
            "}}}} | "
            "{{{{longitude:>"
            f"{format_length['longitude']}"
            "}}}} | "
            "{{{{code:<"
            f"{format_length['code']}"
            "}}}} | "
            "{{{{country:<{{countrylen}}}}}} | "
            "{{{{state:<{{statelen}}}}}} | "
            "{{{{city:<{{citylen}}}}}} | "
            "{{{{location:<{{locationlen}}}}}} | "
            "{{{{path:<{{pathlen}}}}}}"
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
        page_all_marker = "?" if args.unset_only or args.unset_gps_only else ""
        header_line = (
            # can later be set to something else, eg page numbers
            "> Page {page_no:,}/{page_all:,}"
            + page_all_marker
            + "\n"
            + header_line_2.replace("{", "{{").replace("}", "}}")
            + "\n"
            + header_line_3
        )
        # header print class
        read_only_output = ReadOnlyOutput(
            header_line,
            format_line,
            format_length,
            page_all,
            header_repeat,
        )
        # print header
        # print_header(header_line.format(page_no=page_no, page_all=page_all))
        read_only_output.print_header()
        # print no files found if we have no files
        if not work_files:
            print(f"{'[!!!] No files found':<60}")

    # MARK: MAIN WORK LOOP
    # now we just loop through each file and work on them
    for xmp_file in work_files:
        # get the script run location and remove that path from the xmp_file
        # and write this new file name to a print file variable
        script_path = os.path.dirname(os.path.realpath(__file__))
        xmp_real_path = os.path.realpath(xmp_file)
        try:
            common_path = os.path.commonpath([script_path, xmp_real_path])
            xmp_file_print = os.path.relpath(xmp_real_path, common_path)
        except ValueError:
            # no common path (e.g. different drives on Windows)
            xmp_file_print = xmp_file
        if args.debug:
            print(f"---> {xmp_file} -> {xmp_file_print}: ", end="")

        # ### ACTION FLAGs
        write_file = False

        # ### XMP FILE READING
        # open file & read all into buffer
        with open(xmp_file, "r", encoding="UTF-8") as fptr:
            strbuffer = fptr.read()
        # read fields from the XMP file and store in hash
        xmp.parse_from_str(strbuffer)
        # for xmp_field in xmp_fields:
        #     # need to check if propert exist or it will the exempi routine will fail
        #     if xmp.does_property_exist(xmp_fields[xmp_field], xmp_field):
        #         data_set[xmp_field] = xmp.get_property(xmp_fields[xmp_field], xmp_field)
        #     else:
        #         data_set[xmp_field] = ''
        #     if args.debug:
        #         print(f"### => XMP: {xmp_fields[xmp_field]}:{xmp_field} => {data_set[xmp_field]}")
        for xmp_field_key, xmp_field_value in xmp_fields.items():
            # need to check if propert exist or it will the exempi routine will fail
            if xmp.does_property_exist(xmp_field_value, xmp_field_key):
                data_set[xmp_field_key] = xmp.get_property(xmp_field_value, xmp_field_key)
            else:
                data_set[xmp_field_key] = ""
            if args.debug:
                print(f"### [{xmp_file}] => XMP: {xmp_field_value}:{xmp_field_key} => {data_set[xmp_field_key]}")
        if args.read_only:
            # MARK: read only
            # view only if list all or if data is unset
            if (
                (not args.unset_only and not args.unset_gps_only)
                or (args.unset_only and "" in data_set.values())
                or (args.unset_gps_only and (not data_set["GPSLatitude"] or not data_set["GPSLongitude"]))
            ):
                # for read only we print out the data formatted
                # headline check, do we need to print that
                if read_only_output is not None:
                    read_only_output.next_line()
                    read_only_output.print_line(xmp_file, data_set)
                count["listed"] += 1
        else:
            # MARK: write mode
            # ### LR Action Flag (data ok)
            lightroom_data_ok = True
            # sqlite3.Row (row_factory is set) or None if nothing found / no lightroom
            lrdb_row: sqlite3.Row | None = None
            # ### LIGHTROOM DB READING
            # read in data from DB if we uave lightroom folder
            if use_lightroom and cur is not None:
                # get the base file name, we need this for lightroom
                xmp_file_basename = os.path.splitext(os.path.split(xmp_file)[1])[0]
                # try to get this file name from the DB
                lr_query_params = [xmp_file_basename]
                # for strict check we need to get the full path
                # and add / as the LR stores the last folder with /
                # LR stores absolute, real paths: realpath resolves symlinks and also collapses
                # any "//", "./", "../" and removes a trailing "/", then exactly one "/" is added
                # (rstrip for the root folder "/")
                if args.lightroom_strict:
                    xmp_file_path = f"{os.path.realpath(os.path.dirname(xmp_file)).rstrip('/')}/"
                    lr_query_params.append(xmp_file_path)
                cur.execute(query, lr_query_params)
                # get the row data
                # fetchone is untyped (Any), with row_factory = sqlite3.Row it is a Row or None
                lrdb_row = cast(sqlite3.Row | None, cur.fetchone())
                # abort the read because we found more than one row
                if cur.fetchone() is not None:
                    print("(!) Lightroom DB returned more than one more row")
                    lightroom_data_ok = False
                    count["many_found"] += 1
                # Notify if we couldn't find one
                elif lrdb_row is None:
                    print("(!) Could not get data from Lightroom DB")
                    lightroom_data_ok = False
                    count["not_found"] += 1
                if args.debug and lrdb_row is not None:
                    print(f"### LightroomDB: {tuple(lrdb_row)} / {lrdb_row.keys()}")

            # create a duplicate copy for later checking if something changed
            data_set_original = data_set.copy()
            # check if LR exists and use this to compare to XMP data
            # is LR GPS and no XMP GPS => use LR and set XMP
            # same for location names
            # if missing in XMP but in LR -> set in XMP
            # if missing in both do lookup in Maps
            if use_lightroom and lightroom_data_ok and lrdb_row is not None:
                # check lat/long separate
                # LR stores GPS as decimal number (REAL), sqlite3.Row values are untyped
                if lrdb_row["gpsLatitude"] and not data_set["GPSLatitude"]:
                    # we need to convert to the Degree,Min.sec[NSEW] format
                    data_set["GPSLatitude"] = convert_lat_to_dms(float(lrdb_row["gpsLatitude"]))
                if lrdb_row["gpsLongitude"] and not data_set["GPSLongitude"]:
                    data_set["GPSLongitude"] = convert_long_to_dms(float(lrdb_row["gpsLongitude"]))
                # now check Location, City, etc
                for loc in data_set_loc:
                    # overwrite original set (read from XMP) with LR data
                    # if original data is missing
                    if lrdb_row[loc] and not data_set[loc]:
                        data_set[loc] = lrdb_row[loc]
                        if args.debug:
                            print(f"### -> LR: {loc} => {lrdb_row[loc]}")
            # base set done, now check if there is anything unset in the data_set,
            # if yes do a lookup in maps
            # run this through the overwrite checker to get unset if we have a forced overwrite
            has_unset = False
            failed = False
            from_cache = False
            for loc in data_set_loc:
                if check_overwrite(data_set[loc], loc, args.field_controls, args):
                    has_unset = True
            if has_unset:
                # check if lat/long is in cache
                cache_key = f"{data_set['GPSLongitude']}#{data_set['GPSLatitude']}"
                if args.debug:
                    print(f"### *** CACHE: {cache_key}: {'NO' if cache_key not in data_cache else 'YES'}")
                # main chache check = identical
                # second cache level check is on distance:
                # default distance is 10m, can be set via flag
                # check distance to previous cache entries (reverse newest to oldest)
                # and match before we do google lookup
                if cache_key not in data_cache:
                    has_fuzzy_cache = False
                    best_match_latlong = ""
                    if args.fuzzy_distance:
                        # distance in meters (DistanceValues action stores an int)
                        shortest_distance = float(args.fuzzy_distance)
                        # check if we have fuzzy distance, if no valid found do maps lookup
                        for _cache_key in data_cache:
                            # split up cache key so we can use in the distance calc method
                            to_lat_long = _cache_key.split("#")
                            # get the distance based on current set + cached set
                            # print(
                            #     f"Lookup f-long {data_set['GPSLongitude']} "
                            #     f"f-lat {data_set['GPSLatitude']} "
                            #     f"t-long {to_lat_long[0]} t-lat {to_lat_long[1]}"
                            # )
                            distance = get_distance(
                                from_longitude=data_set["GPSLongitude"],
                                from_latitude=data_set["GPSLatitude"],
                                to_longitude=to_lat_long[0],
                                to_latitude=to_lat_long[1],
                            )
                            if args.debug:
                                print(
                                    f"### **= FUZZY CACHE: => distance: {distance} (m), shortest: {shortest_distance}"
                                )
                            if distance <= shortest_distance:
                                # set new distance and keep current best matching location
                                shortest_distance = distance
                                best_match_latlong = _cache_key
                                has_fuzzy_cache = True
                                if args.debug:
                                    print(f"### ***= FUZZY CACHE: YES => Best match: {best_match_latlong}")
                    if not has_fuzzy_cache:
                        # get location from maps (google or openstreetmap)
                        maps_location = reverse_geolocate(
                            latitude=data_set["GPSLatitude"],
                            longitude=data_set["GPSLongitude"],
                            map_type=map_type,
                            args=args,
                        )
                        # cache data with Lat/Long
                        data_cache[cache_key] = maps_location
                        from_cache = False
                    else:
                        maps_location = data_cache[best_match_latlong]
                        # cache this one, because the next one will match this one too
                        # we don't need to loop search again for the same fuzzy location
                        data_cache[cache_key] = maps_location
                        count["cache"] += 1
                        count["fuzzy_cache"] += 1
                        from_cache = True
                else:
                    # load location from cache
                    maps_location = data_cache[cache_key]
                    count["cache"] += 1
                    from_cache = True
                # overwrite sets (note options check here)
                if args.debug:
                    print(f"### Map Location ({map_type}): {maps_location}")
                # must have at least the country set to write anything back
                if maps_location["Country"]:
                    for loc in data_set_loc:
                        # only write to XMP if overwrite check passes
                        if check_overwrite(data_set_original[loc], loc, args.field_controls, args):
                            data_set[loc] = maps_location[loc]
                            xmp.set_property(xmp_fields[loc], loc, maps_location[loc])
                            write_file = True
                    if write_file:
                        count["map"] += 1
                else:
                    print("(!) Could not geo loaction data ", end="")
                    failed = True
            else:
                if args.debug:
                    print(f"Lightroom data use: {use_lightroom}, Lightroom data ok: {lightroom_data_ok}")
                # check if the data_set differs from the original (LR db load)
                # if yes write, else skip
                if use_lightroom and lightroom_data_ok:
                    # for key in data_set:
                    #     # if not the same (to original data) and passes overwrite check
                    #     if (
                    #           data_set[key] != data_set_original[key] and
                    #           check_overwrite(data_set_original[key], key, args.field_controls)
                    #       ):
                    #         xmp.set_property(xmp_fields[key], key, data_set[key])
                    #         write_file = True
                    for key, value in data_set.items():
                        # if not the same (to original data) and passes overwrite check
                        if value != data_set_original[key] and check_overwrite(
                            data_set_original[key], key, args.field_controls, args
                        ):
                            xmp.set_property(xmp_fields[key], key, value)
                            write_file = True
                    if write_file:
                        count["lightroom"] += 1
            # if we have the write flag set, write data
            if write_file:
                if not args.test:
                    # use copyfile to create a backup copy
                    if not args.no_xmp_backup:
                        # check if there is another file with .BK. already there,
                        # if yes, get the max number and +1 it, if not set to 1
                        bk_file_counter = get_backup_file_counter(xmp_file, args)
                        # copy to new backup file
                        copyfile(
                            xmp_file,
                            f"{os.path.splitext(xmp_file)[0]}.BK.{bk_file_counter}{os.path.splitext(xmp_file)[1]}",
                        )
                    # write back to riginal file
                    with open(xmp_file, "w", encoding="UTF-8") as fptr:
                        fptr.write(xmp.serialize_to_str(omit_packet_wrapper=True))
                else:
                    print(f"{xmp_file_print}: [TEST] Would write {data_set} {xmp_file}", end="")
                if from_cache:
                    print(f"{xmp_file_print}: [UPDATED FROM CACHE]")
                else:
                    print(f"{xmp_file_print}: [UPDATED]")
                count["changed"] += 1
            elif failed:
                print(f"{xmp_file_print}: [FAILED]")
                count["failed"] += 1
                # log data to array for post print
                failed_files.append(xmp_file)
            else:
                if args.verbose >= 1:
                    print(f"{xmp_file_print}: [SKIP]")
                count["skipped"] += 1

    # MARK: close DB
    # close DB connection
    if use_lightroom and lrdb is not None:
        lrdb.close()

    # MARK: print stats
    # end stats only if we write
    print(f"{'=' * 44}")
    print(f"XMP Files found                  : {count['all']:9,}")
    if args.read_only:
        print(f"XMP Files listed                 : {count['listed']:9,}")
    if not args.read_only:
        print(f"Updated                          : {count['changed']:9,}")
        print(f"Skipped                          : {count['skipped']:9,}")
        print(f"New GeoLocation from Map         : {count['map']:9,}")
        print(f"GeoLocation from Cache           : {count['cache']:9,}")
        print(f"GeoLocation from Fuzzy Cache     : {count['fuzzy_cache']:9,}")
        print(f"Failed reverse GeoLocate         : {count['failed']:9,}")
        if use_lightroom:
            print(f"GeoLocaction from Lightroom      : {count['lightroom']:9,}")
            print(f"No Lightroom data found          : {count['not_found']:9,}")
            print(f"More than one found in Lightroom : {count['many_found']:9,}")
        # if we have failed data
        if len(failed_files) > 0:
            print(f"{'-' * 44}")
            print("Files that failed to update:")
            print(f"{', '.join(failed_files)}")


##############################################################
# MARK: MAIN RUN
##############################################################

if __name__ == "__main__":
    main()

# __END__
