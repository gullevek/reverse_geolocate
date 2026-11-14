"""
Setups and parses the arguments
"""

import argparse
import re

from reverse_geolocate.setup.argparse.distance_values import DistanceValues
from reverse_geolocate.setup.argparse.readable_dir import ReadableDir
from reverse_geolocate.setup.argparse.writeable_dir_folder import WritableDirFolder


class ArgumentSetup:
    """
    ArgumentParser setup and parsning
    use .get_args() to get the argument data
    """

    def __init__(self):
        # NO OP RUN
        self.parser = argparse.ArgumentParser(
            description="Reverse Geoencoding based on set Latitude/Longitude data in XMP files",
            # formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="Sample: (todo)",
        )
        self.args: argparse.Namespace | None = None

    # def __get_alias_list(self, action_name: str) -> list[str]:
    #     """
    #     get the list of aliases for an action name

    #     Args:
    #         action_name (str): action name

    #     Returns:
    #         list[str]: list of aliaes for it
    #     """
    #     return [alias for alias, name in self.ACTION_MAP.items() if name == action_name]

    def __arguments_set(self):
        """
        parses arguments and returns argument Namespace
        """

        # xmp folder (or folders), or file (or files)
        # note that the target directory or file needs to be writeable
        self.parser.add_argument(
            "-i",
            "--include-source",
            required=True,
            nargs="*",
            action=WritableDirFolder,
            dest="xmp_sources",
            metavar="XMP SOURCE FOLDER",
            help=(
                "The source folder or folders with the XMP files that need reverse geo encoding "
                "to be set. Single XMP files can be given here"
            ),
        )
        # exclude folders
        self.parser.add_argument(
            "-x",
            "--exclude-source",
            nargs="*",
            action=WritableDirFolder,
            dest="exclude_sources",
            metavar="EXCLUDE XMP SOURCE FOLDER",
            help="Folders and files that will be excluded.",
        )

        # LR database (base folder)
        # get .lrcat file in this folder
        self.parser.add_argument(
            "-l",
            "--lightroom",
            # required=True,
            action=ReadableDir,
            dest="lightroom_folder",
            metavar="LIGHTROOM FOLDER",
            help="Lightroom catalogue base folder",
        )

        # strict LR check with base path next to the file base name
        self.parser.add_argument(
            "-s",
            "--strict",
            dest="lightroom_strict",
            action="store_true",
            help="Do strict check for Lightroom files including Path in query",
        )

        # set behaviour override
        # FLAG: default: only set not filled
        # other: overwrite all or overwrite if one is missing,
        # overwrite specifc field (as defined below)
        # fields: Location, City, State, Country, CountryCode
        self.parser.add_argument(
            "-f",
            "--field",
            action="append",
            type=str.lower,  # make it lowercase for check
            choices=["overwrite", "location", "city", "state", "country", "countrycode"],
            dest="field_controls",
            metavar="<overwrite, location, city, state, country, countrycode>",
            help=(
                "On default only set fields that are not set yet. Options are: "
                "Overwrite (write all new), Location, City, State, Country, CountryCode. "
                "Multiple can be given for combination overwrite certain fields only "
                "or set only certain fields. "
                "If with overwrite the field will be overwritten if already set, "
                "else it will be always skipped."
            ),
        )

        self.parser.add_argument(
            "-d",
            "--fuzzy-cache",
            type=str.lower,
            action=DistanceValues,
            nargs="?",
            const="10m",  # default is 10m
            dest="fuzzy_distance",
            metavar="FUZZY DISTANCE",
            help=(
                "Allow fuzzy distance cache lookup. Optional distance can be given, "
                "if not set default of 10m is used. "
                "Allowed argument is in the format of 12m or 12km"
            ),
        )

        # Google Maps API key to overcome restrictions
        self.parser.add_argument(
            "-g",
            "--google",
            dest="google_api_key",
            metavar="GOOGLE API KEY",
            help="Set a Google API Maps key to overcome the default lookup limitations",
        )

        # use open street maps
        self.parser.add_argument(
            "-o",
            "--openstreetmap",
            dest="use_openstreetmap",
            action="store_true",
            help="Use openstreetmap instead of Google",
        )

        # email of open street maps requests
        self.parser.add_argument(
            "-e", "--email", dest="email", metavar="EMIL ADDRESS", help="An email address for OpenStreetMap"
        )

        # write api/email settings to config file
        self.parser.add_argument(
            "-w",
            "--write-settings",
            dest="config_write",
            action="store_true",
            help="Write Google API or OpenStreetMap email to config file",
        )

        # only read data and print on screen, do not write anything
        self.parser.add_argument(
            "-r",
            "--read-only",
            dest="read_only",
            action="store_true",
            help=("Read current values from the XMP file only, do not read from LR or lookup any data and write back"),
        )

        # only list unset ones
        self.parser.add_argument(
            "-u",
            "--unset-only",
            dest="unset_only",
            action="store_true",
            help="Only list unset XMP files",
        )

        # only list unset GPS codes
        self.parser.add_argument(
            "-p",
            "--unset-gps-only",
            dest="unset_gps_only",
            action="store_true",
            help="Only list unset XMP files for GPS fields",
        )

        # don't try to do auto adjust in list view
        self.parser.add_argument(
            "-a",
            "--no-autoadjust",
            dest="no_autoadjust",
            action="store_true",
            help="Don't try to auto adjust columns",
        )

        # compact view, compresses columns down to a minimum
        self.parser.add_argument(
            "-c",
            "--compact",
            dest="compact_view",
            action="store_true",
            help="Very compact list view",
        )

        # Do not create backup files
        self.parser.add_argument(
            "-n",
            "--nobackup",
            dest="no_xmp_backup",
            action="store_true",
            help="Do not create a backup from the XMP file",
        )

        # verbose args for more detailed output
        self.parser.add_argument(
            "-v",
            "--verbose",
            action="count",
            dest="verbose",
            help="Set verbose output level",
        )

        # debug flag
        self.parser.add_argument(
            "--debug",
            action="store_true",
            dest="debug",
            help="Set detailed debug output",
        )
        # test flag
        self.parser.add_argument(
            "--test",
            action="store_true",
            dest="test",
            help="Do not write data back to file",
        )

    def __arguments_check(self):
        """
        checks that argument combinations are valid and sets default settings if needed
        """

        # MARK: Argument checks
        if self.args is None:
            raise ValueError("Could not setup arguemnts through parse_args()")

        # make sure all are set to None if they are not existing in the args
        for attr_name in [
            "xmp_sources",
            "exclude_sources",
            "lightroom_folder",
            "lightroom_strict",
            "field_controls",
            "fuzzy_distance",
            "google_api_key",
            "use_openstreetmap",
            "email",
            "config_write",
            "read_only",
            "unset_only",
            "unset_gps_only",
            "no_autoadjust",
            "compact_view",
            "no_xmp_backup",
            "verbose",
            "debug",
            "test",
        ]:
            if not hasattr(self.args, attr_name):
                setattr(self.args, attr_name, None)

        # init verbose to 0 if not set
        if not self.args.verbose:
            self.args.verbose = 0
        # init exclude source to list if not set
        if not self.args.exclude_sources:
            # typed empty list, an untyped [] makes args.exclude_sources a list[Unknown]
            no_exclude_sources: list[str] = []
            self.args.exclude_sources = no_exclude_sources
        # init args unset (for list view) with 0 if unset
        if not self.args.unset_only:
            self.args.unset_only = 0

        if self.args.debug:
            print(
                "### ARGUMENT VARS: "
                f"I: {self.args.xmp_sources}, X: {self.args.exclude_sources}, L: {self.args.lightroom_folder}, "
                f"F: {self.args.field_controls}, D: {self.args.fuzzy_distance}, M: {self.args.use_openstreetmap}, "
                f"G: {self.args.google_api_key}, E: {self.args.email}, R: {self.args.read_only}, "
                f"U: {self.args.unset_only}, A: {self.args.no_autoadjust}, C: {self.args.compact_view}, "
                f"N: {self.args.no_xmp_backup}, W: {self.args.config_write}, V: {self.args.verbose}, "
                f"D: {self.args.debug}, T: {self.args.test}"
            )

        # error flag
        error = False
        # if -g and -o, error
        if self.args.google_api_key and self.args.use_openstreetmap:
            print("You cannot set a Google API key and use OpenStreetMap at the same time")
            error = True
        # or if -g and -e
        if self.args.google_api_key and self.args.email:
            print("You cannot set a Google API key and OpenStreetMap email at the same time")
            error = True
        # or -e and no -o
        if self.args.email and not self.args.use_openstreetmap:
            print("You cannot set an OpenStreetMap email and not use OpenStreetMap")
            error = True
        # if email and not basic valid email (@ .)
        if self.args.email and not re.match(r"^.+@.+\.[A-Za-z]{1,}$", self.args.email):
            print(f"Not a valid email for OpenStreetMap: {self.args.email}")
            error = True
        # on error exit here
        if error:
            raise SystemExit("Argument error, see above")

    def get_args(self) -> argparse.Namespace:
        """
        return the argument parser

        Returns:
            Namespace: _description_
        """

        # set arguments
        self.__arguments_set()
        # parse the arguments
        try:
            self.args = self.parser.parse_args()
        except argparse.ArgumentTypeError as e:
            raise SystemExit(f"Argument error: {e}") from e
        # post fix
        self.__arguments_check()

        return self.args


# __END__
