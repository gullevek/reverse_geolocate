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

# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import ExempiLoadError, XMPMeta

from reverse_geolocate.setup.arguments import ArgumentSetup
from reverse_geolocate.setup.configurate import read_config
from reverse_geolocate.utils.file_collection import collect_work_files
from reverse_geolocate.utils.function_collection import (
    normalize_path,
)
from reverse_geolocate.utils.lightroom import LightroomCatalog, LightroomError
from reverse_geolocate.utils.read_only_output import run_read_only
from reverse_geolocate.utils.statistics import RunStatistics, print_statistics
from reverse_geolocate.utils.write_run import MapType, run_write
from reverse_geolocate.utils.xmp_data import (
    XmpWriteError,
)

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

    # set if the run was stopped because a file could not be written
    write_error = False
    try:
        # MARK: check Exempi
        # each file is read into its own XMP object, check here once that Exempi can be loaded
        try:
            XMPMeta()
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
            run_read_only(work_files, args, statistics, call_path)
        else:
            try:
                run_write(work_files, args, map_type, lightroom, statistics, call_path)
            except XmpWriteError as e:
                # no write permission, disk full, ...: critical, do not continue with the other files
                # (the file itself is unchanged)
                print(f"(!!!) CRITICAL: Could not write the XMP file {e.xmp_file}: {e.reason}")
                print("(!!!) Run stopped, the remaining files are not processed")
                write_error = True
    finally:
        # MARK: close Lightroom
        if lightroom is not None:
            lightroom.close()

    # MARK: print stats
    # also after a critical error, shows what was done until then
    print_statistics(statistics, read_only=bool(args.read_only), use_lightroom=lightroom is not None)
    if write_error:
        sys.exit(1)


##############################################################
# MARK: MAIN RUN
##############################################################

if __name__ == "__main__":
    main()

# __END__
