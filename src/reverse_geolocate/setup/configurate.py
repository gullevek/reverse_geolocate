"""
read config file and write args
"""

import configparser
import os
from argparse import Namespace

from reverse_geolocate.setup.arguments import is_valid_email


def read_config(args: Namespace) -> Namespace:
    """
    reads the API settings from the config file ~/.config/reverseGeolocate/reverse_geolocate.cfg
    and writes them there with -w (config_write)

    only the setting for the used service is read, values from the command line have priority:
    - Google (default): googleapikey
    - OpenStreetMap (-o): openstreetmapemail, checked like -e, an invalid email is not used (warning)

    Args:
        args (Namespace): command line arguments, the API settings are set in there

    Returns:
        Namespace: the command line arguments with the API settings from the config file
    """
    config = configparser.ConfigParser()
    # try to find config file in following order
    # $HOME/.config/
    config_file = "reverse_geolocate.cfg"
    config_folder = os.path.expanduser("~/.config/reverseGeolocate/")
    config_data = os.path.join(f"{config_folder}", f"{config_file}")
    # if file exists read, if not skip unless we have write flag and
    # google api or openstreetmaps email
    if os.path.isfile(config_data):
        config.read(config_data)
        # check if api group & setting is there. also never overwrite argument given data
        # only the setting for the used service (the argument checks are done before for the command line)
        if "API" in config:
            if not args.use_openstreetmap:
                if "googleapikey" in config["API"] and not args.google_api_key:
                    args.google_api_key = config["API"]["googleapikey"]
            elif "openstreetmapemail" in config["API"] and not args.email:
                config_email = config["API"]["openstreetmapemail"]
                if is_valid_email(config_email):
                    args.email = config_email
                else:
                    print(f"(!) Not a valid email for OpenStreetMap in the config file {config_data}: {config_email}")
    # write data if exists and changed
    if args.config_write and (args.google_api_key or args.email):
        config_change = False
        # check if new value differs, if yes, change and write
        if "API" not in config:
            config["API"] = {}
        if args.google_api_key and (
            "googleapikey" not in config["API"] or config["API"]["googleapikey"] != args.google_api_key
        ):
            config["API"]["googleapikey"] = args.google_api_key
            config_change = True
        if args.email and (
            "openstreetmapemail" not in config["API"] or config["API"]["openstreetmapemail"] != args.email
        ):
            config["API"]["openstreetmapemail"] = args.email
            config_change = True
        if config_change:
            # if we do not have the base folder create that first
            if not os.path.exists(config_folder):
                os.makedirs(config_folder)
            with open(config_data, "w", encoding="UTF-8") as fptr:
                config.write(fptr)
    if args.debug:
        print(f"### OVERRIDE API: G: {args.google_api_key}, O: {args.email}")
    return args
