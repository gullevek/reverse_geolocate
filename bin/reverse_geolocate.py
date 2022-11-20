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

import configparser
import unicodedata
# import textwrap
import glob
import os
import sys
import re
import argparse
import sqlite3
from shutil import copyfile, get_terminal_size
from math import ceil, radians, sin, cos, atan2, sqrt
import requests
# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import XMPMeta, consts

##############################################################
# FUNCTIONS
##############################################################

# this is for looking up if string is non latin letters
# this is used by isLatin and onlyLatinChars
cache_latin_letters = {}

# ARGPARSE HELPERS

class WritableDirFolder(argparse.Action):
    """
    checks if this is a writeable folder OR file
    AND it works on nargs *

    Args:
        argparse (_type_): _description_
    """
    def __call__(self, parser, namespace, values, option_string=None):
        if isinstance(values, str) or values is None:
            print("FAIL")
        else:
            # we loop through list (this is because of nargs *)
            for prospective_dir in iter(values):
                # if valid and writeable (dir or file)
                if os.access(prospective_dir, os.W_OK):
                    # init new output array
                    out = []
                    # if we have a previous list in the namespace extend current list
                    if isinstance(getattr(namespace, self.dest), list):
                        out.extend(getattr(namespace, self.dest))
                    # add the new dir to it
                    out.append(prospective_dir)
                    # and write that list back to the self.dest in the namespace
                    setattr(namespace, self.dest, out)
                else:
                    raise argparse.ArgumentTypeError(
                        f"writable_dir_folder: {prospective_dir} is not a writable dir"
                    )

class ReadableDir(argparse.Action):
    """
    custom define to check if it is a valid directory

    Args:
        argparse (_type_): _description_
    """
    def __call__(self, parser, namespace, values, option_string=None):
        prospective_dir = values
        if not isinstance(prospective_dir, str):
            raise argparse.ArgumentTypeError(
                f"readable_dir:{prospective_dir} is not a readable dir"
            )
        else:
            if not os.path.isdir(prospective_dir):
                raise argparse.ArgumentTypeError(
                    f"readable_dir:{prospective_dir} is not a valid path"
                )
            if os.access(prospective_dir, os.R_OK):
                setattr(namespace, self.dest, prospective_dir)
            else:
                raise argparse.ArgumentTypeError(
                    f"readable_dir:{prospective_dir} is not a readable dir"
                )

class DistanceValues(argparse.Action):
    """
    check distance values are valid

    Args:
        argparse (_type_): _description_
    """
    def __call__(self, parser, namespace, values, option_string=None):
        if not isinstance(values, str):
            raise argparse.ArgumentTypeError(
                f"distance_values:{values} is not a valid argument"
            )
        else:
            _distance = re.match(r'^(\d+)\s?(m|km)$', values)
            if _distance:
                # convert to int in meters
                values = int(_distance.group(1))
                if _distance.group(2) == 'km':
                    values *= 1000
                setattr(namespace, self.dest, values)
            else:
                raise argparse.ArgumentTypeError(
                    f"distance_values:{values} is not a valid argument"
                )


# MAIN FUNCTIONS

def reverse_geolocate(longitude, latitude, map_type, args):
    """
    wrapper to call to either the google or openstreetmap

    Args:
        longitude (float): latitude
        latitude (float): longitue
        map_type(str): map search target (google or openstreetmap)
        args (_type_): _description_

    Returns:
        _type_: dict with all data (see below)
    """
    # clean up long/lat
    # they are stored with N/S/E/W if they come from an XMP
    # format: Deg,Min.Sec[NSEW]
    # NOTE: lat is N/S, long is E/W
    # detect and convert
    lat_long = long_lat_reg(longitude=longitude, latitude=latitude)
    # which service to use
    if map_type == 'google':
        return reverse_geolocate_google(lat_long['longitude'], lat_long['latitude'], args)
    elif map_type == 'openstreetmap':
        return reverse_geolocate_open_street_map(lat_long['longitude'], lat_long['latitude'], args)
    else:
        return {
            'Country': '',
            'status': 'ERROR',
            'error': 'Map type not valid'
        }

def reverse_geolocate_init(longitude, latitude):
    """
    inits the dictionary for return, and checks the lat/long on valid
    returns geolocation dict with status = 'ERROR' if an error occurded

    Args:
        longitude (float): longitude
        latitude (float): latitude

    Returns:
        _type_: empty geolocation dictionary, or error flag if lat/long is not valid
    """
    # basic dict format
    geolocation = {
        'CountryCode': '',
        'Country': '',
        'State': '',
        'City': '',
        'Location': '',
        # below for error reports
        'status': '',
        'error_message': ''
    }
    # error if long/lat is not valid
    latlong_re = re.compile(r'^\d+\.\d+$')
    if not latlong_re.match(str(longitude)) or not latlong_re.match(str(latitude)):
        geolocation['status'] = 'ERROR'
        geolocation['error_message'] = f"Latitude {latitude} or Longitude {longitude} are not valid"
    return geolocation

def reverse_geolocate_open_street_map(longitude, latitude, args):
    """
    OpenStreetMap reverse lookcation lookup

    sample:
    https://nominatim.openstreetmap.org/reverse.php?format=jsonv2&
        at=<latitude>&lon=<longitude>&zoom=21&accept-languge=en-US,en&

    Args:
        longitude (float): longitude
        latitude (float): latitude
        args (_type_): _description_

    Returns:
        dictionary: dict with locaiton, city, state, country, country code
                    if not fillable, entry is empty
    """
    # init
    geolocation = reverse_geolocate_init(longitude, latitude)
    if geolocation['status'] == 'ERROR':
        return geolocation
    # query format
    query_format = 'jsonv2'
    # language to return (english)
    language = 'en-US,en'
    # build query
    base = 'https://nominatim.openstreetmap.org/reverse.php?'
    # parameters
    payload = {
        'format': query_format,
        'lat': latitude,
        'lon': longitude,
        'accept-language': language
    }
    # if we have an email, add it here
    if args.email:
        payload['email'] = args.email
    url = f"{base}"
    # timeout in seconds
    timeout = 60
    response = requests.get(url, params=payload, timeout=timeout)
    # debug output
    if args.debug:
        print(f"OpenStreetMap search for Lat: {latitude}, Long: {longitude}")
    if args.debug and args.verbose >= 1:
        print(f"OpenStreetMap response: {response} => JSON: {response.json()}")
    # type map
    # Country to Location and for each in order of priority
    type_map = {
        'CountryCode': ['country_code'],
        'Country': ['country'],
        'State': ['state'],
        'City': ['city', 'city_district', 'state_district'],
        'Location': ['county', 'town', 'suburb', 'hamlet', 'neighbourhood', 'road']
    }
    # if not error
    if 'error' not in response.json():
        # get address block
        addr = response.json()['address']
        # loop for locations
        for loc_index, sub_index in type_map.items():
            for index in sub_index:
                if index in addr and not geolocation[loc_index]:
                    geolocation[loc_index] = addr[index]
        # for loc_index in type_map:
        #     for index in type_map[loc_index]:
        #         if index in addr and not geolocation[loc_index]:
        #             geolocation[loc_index] = addr[index]
    else:
        geolocation['status'] = 'ERROR'
        geolocation['error_message'] = response.json()['error']
        print(f"Error in request: {geolocation['error']}")
    # return
    return geolocation

def reverse_geolocate_google(longitude, latitude, args):
    """
    Google Maps reverse location lookup

    sample:
    http://maps.googleapis.com/maps/api/geocode/json?latlng=<latitude>,<longitude>&language=<lang>
        &sensor=false&key=<api key>

    Args:
        longitude (float): longitude
        latitude (float): latitude
        args (_type_): _description_

    Returns:
        dictionary: dict with location, city, state, country, country code
                    if not fillable, entry is empty
    """
    # init
    geolocation = reverse_geolocate_init(longitude, latitude)
    temp_geolocation = geolocation.copy()
    if geolocation['status'] == 'ERROR':
        return geolocation
    # sensor (why?)
    sensor = 'false'
    # language, so we get ascii en back
    language = 'en'
    # request to google
    # if a google api key is used, the request has to be via https
    protocol = 'https://' if args.google_api_key else 'http://'
    base = "maps.googleapis.com/maps/api/geocode/json?"
    # build the base params
    payload = {
        'latlng': f"{latitude},{longitude}",
        'language': language,
        'sensor': sensor
    }
    # if we have a google api key, add it here
    if args.google_api_key:
        payload['key'] = args.google_api_key
    # build the full url and send it to google
    url = f"{protocol}{base}"
    # timeout in seconds
    timeout = 60
    response = requests.get(url, params=payload, timeout=timeout)
    # debug output
    if args.debug:
        print(f"Google search for Lat: {latitude}, Long: {longitude} with {response.url}")
    if args.debug and args.verbose >= 1:
        print(f"Google response: {response} => JSON: {response.json()}")
    # type map
    # For automated return of correct data into set to return
    type_map = {
        'CountryCode': ['country'],
        'Country': ['country'],
        'State': ['administrative_area_level_1', 'administrative_area_level_2'],
        'City': ['locality', 'administrative_area_level_3'],
        'Location': ['sublocality_level_1', 'sublocality_level_2', 'route'],
    }
    # print("Error: {}".format(response.json()['status']))
    if response.json()['status'] == 'OK':
        # first entry for type = premise
        for entry in response.json()['results']:
            for sub_entry in entry:
                if sub_entry == 'types' and (
                    'premise' in entry[sub_entry] or
                    'route' in entry[sub_entry] or
                    'street_address' in entry[sub_entry] or
                    'sublocality' in entry[sub_entry]
                ):
                    # print("Entry {}: {}".format(sub_entry, entry[sub_entry]))
                    # print("Address {}".format(entry['address_components']))
                    # type
                    # -> country,
                    # -> administrative_area (1, 2),
                    # -> locality,
                    # -> sublocality (_level_1 or 2 first found, then route)
                    # so we get the data in the correct order
                    # for loc_index in type_map:
                    #     for index in type_map[loc_index]:
                    for loc_index, sub_index in type_map.items():
                        for index in sub_index:
                            # this is an array, so we need to loop through each
                            for addr in entry['address_components']:
                                # in types check that index is in there
                                # and the location is not yet set
                                # also check that entry is in LATIN based
                                # NOTE: fallback if all are non LATIN?
                                if index in addr['types'] and not geolocation[loc_index]:
                                    # for country code we need to use short name,
                                    # else we use long name
                                    if loc_index == 'CountryCode':
                                        if only_latin_chars(addr['short_name']):
                                            geolocation[loc_index] = addr['short_name']
                                        elif not temp_geolocation[loc_index]:
                                            temp_geolocation[loc_index] = addr['short_name']
                                    else:
                                        if only_latin_chars(addr['long_name']):
                                            geolocation[loc_index] = addr['long_name']
                                        elif not temp_geolocation[loc_index]:
                                            temp_geolocation[loc_index] = addr['long_name']
        # check that all in geoloaction are filled and if not fille from temp_geolocation dictionary
        for loc_index in type_map:
            if not geolocation[loc_index] and temp_geolocation[loc_index]:
                geolocation[loc_index] = temp_geolocation[loc_index]
        # write OK status
        geolocation['status'] = response.json()['status']
    else:
        geolocation['error_message'] = response.json()['error_message']
        geolocation['status'] = response.json()['status']
        print(f"Error in request: {geolocation['status']} {geolocation['error_message']}")
    # return
    return geolocation

def convert_lat_long_to_dms(lat_long, is_latitude=False, is_longitude=False):
    """
    convert the LR format of N.N to the Exif GPS format

    Args:
        lat_long(str): latLong in (-)N.N format
        is_latitude (bool, optional): flag, else we can't set North/Sout. Defaults to False.
        is_longitude (bool, optional): flag, else we can't set West/East. Defaults to False.

    Returns:
        string: Deg,Min.Sec(NESW) format
    """
    # minus part before . and then multiply rest by 60
    degree = int(abs(lat_long))
    minutes = round((float(abs(lat_long)) - int(abs(lat_long))) * 60, 10)
    if is_latitude is True:
        direction = 'S' if int(lat_long) < 0 else 'N'
    elif is_longitude is True:
        direction = 'W' if int(lat_long) < 0 else 'E'
    else:
        direction = '(INVALID)'
    return f"{degree},{minutes}{direction}"

def convert_lat_to_dms(lat_long):
    """
    wrapper functions for Long/Lat calls: latitude

    Args:
        lat_long(str): latLong in (-)N.N format

    Returns:
        string: Deg,Min.Sec(NESW) format
    """
    return convert_lat_long_to_dms(lat_long, is_latitude=True)


# wrapper for Long/Lat call: longitute
def convert_long_to_dms(lat_long):
    """
    wrapper for Long/Lat call: longitute

    Args:
        lat_long(str): latLong in (-)N.N format

    Returns:
        string: Deg,Min.Sec(NESW) format
    """
    return convert_lat_long_to_dms(lat_long, is_longitude=True)

def long_lat_reg(longitude, latitude):
    """
    converts the XMP/EXIF formatted GPS Long/Lat coordinates
    from the <Degree>,<Minute.Second><NSEW> to the normal float
    number used in google/lr internal

    Args:
        longitude(str): n,n.nNSEW format
        latitude(str): n,n.nNSEW format

    Returns:
        dictionary: dict with converted lat/long
    """
    # regex
    latlong_re = re.compile(r'^(\d+),(\d+\.\d+)([NESW]{1})$')
    # dict for loop
    lat_long = {
        'longitude': longitude,
        'latitude': latitude
    }
    # for element in lat_long:
    for index, element in lat_long.items():
        # match if it is exif GPS format
        _match = latlong_re.match(element)
        if _match is not None:
            # convert from Degree, Min.Sec into float format
            lat_long[index] = float(_match.group(1)) + (float(_match.group(2)) / 60)
            # if S or W => inverse to negative
            if _match.group(3) == 'S' or _match.group(3) == 'W':
                lat_long[index] *= -1
    return lat_long

def convert_dms_to_lat(lat_long):
    """
    rapper calls for DMS to Lat/Long: latitude

    Args:
        lat_long(str): n,n.nNSEW format

    Returns:
        dict: dict with converted lat/long
    """
    return long_lat_reg('0,0.0N', lat_long)['latitude']

def convert_dms_to_long(lat_long):
    """
    wrapper calls for DMS to Lat/Long: longitude

    Args:
        lat_long(str): n,n.nNSEW format

    Returns:
        dict: dict with converted lat/long
    """
    return long_lat_reg(lat_long, '0,0.0N')['longitude']

def get_distance(from_longitude, from_latitude, to_longitude, to_latitude):
    """
    calculates the difference between two coordinates

    Args:
        from_longitude(str): from longitude
        from_latitude(str): from latitude
        to_longitude(str): to longitude
        to_latitude(str): to latitude

    Returns:
        float: distance in meters
    """
    # earth radius in meters
    earth_radius = 6378137.0
    # convert all from radians with pre convert DMS to long and to float
    from_longitude = radians(float(convert_dms_to_long(from_longitude)))
    from_latitude = radians(float(convert_dms_to_lat(from_latitude)))
    to_longitude = radians(float(convert_dms_to_long(to_longitude)))
    to_latitude = radians(float(convert_dms_to_lat(to_latitude)))
    # distance from - to
    distance_longitude = from_longitude - to_longitude
    distance_latitude = from_latitude - to_latitude
    # main distance calculation
    distance = sin(distance_latitude / 2)**2 + cos(from_latitude) * \
        cos(to_latitude) * sin(distance_longitude / 2)**2
    distance = 2 * atan2(sqrt(distance), sqrt(1 - distance))
    return earth_radius * distance

def check_overwrite(data, key, field_controls, args):
    """
    checks with field control flags if given data for key should be written
        1) data is not set
        2) data is set or not and field_control: overwrite only set
        3) data for key is not set, but only for key matches field_control
        4) data for key is set or not, but only for key matches field_control and overwrite is set

    Args:
        data(str): value field
        key(str): xmpt key
        field_controls (array): array from args
        args (_type_): _description_

    Returns:
        bool: true/false
    """
    status = False
    # init field controls for empty
    if not field_controls:
        field_controls = []
    if (
        not data and (len(field_controls) == 0 or
        ('overwrite' in field_controls and len(field_controls) == 1))
    ):
        status = True
    elif not data and key.lower() in field_controls:
        status = True
    elif data and 'overwrite' in field_controls and len(field_controls) == 1:
        status = True
    elif data and key.lower() in field_controls and 'overwrite' in field_controls:
        status = True
    if args.debug:
        print(
            f"Data set: {'YES' if data else 'NO'}, "
            f"Key: {key.lower()}, "
            f"Field Controls len: {len(field_controls)}, "
            f"Overwrite: {'OVERWRITE' if 'overwrite' in field_controls else 'NOT OVERWRITE'}, "
            "Key in Field Controls: "
            f"{'KEY OK' if key.lower() in field_controls else 'KEY NOT MATCHING'}, "
            f"OVERWRITE: {status}"
        )
    return status

def shorten_path(path, length=30, file_only=False, path_only=False):
    """
    shortes a path from the left so it fits into lenght
    if file only is set to true, it will split the file, if path only is set, only the path

    Args:
        path(str): path
        length (int, optional): maximum length to shorten to. Defaults to 30.
        file_only (bool, optional): only file. Defaults to False.
        path_only (bool, optional): only path. Defaults to False.

    Returns:
        string: shortend path with ... in front
    """
    length = length - 3
    # I assume the XMP file name has no CJK characters inside, so I strip out the path
    # The reason is that if there are CJK characters inside it will screw up the formatting
    if file_only:
        path = os.path.split(path)[1]
    if path_only:
        path = os.path.split(path)[0]
    if string_len_cjk(path) > length:
        path = f".. {path[string_len_cjk(path) - length:]}"
    return path

def shorten_string(string, width, placeholder='..'):
    """
    shortens a string to width and attached placeholder

    Args:
        string(str): string to shorten
        width (int): length th shorten to
        placeholder (str, optional): optional string for removed shortend part. Defaults to '..'.

    Returns:
        string: shortened string
    """
    # get the length with double byte charactes
    string_length_cjk = string_len_cjk(str(string))
    # if double byte width is too big
    if string_length_cjk > width:
        # set current length and output string
        cur_len = 0
        out_string = ''
        # loop through each character
        for char in str(string):
            # set the current length if we add the character
            cur_len += 2 if unicodedata.east_asian_width(char) in "WF" else 1
            # if the new length is smaller than the output length to shorten too add the char
            if cur_len <= (width - len(placeholder)):
                out_string += char
        # return string with new width and placeholder
        return f"{out_string}{placeholder}"
    else:
        return str(string)

def string_len_cjk(string):
    """
    because len on string in python counts characters but we need the width
    count for formatting, we count two for a double byte characters

    Args:
        string (string): string to check length

    Returns:
        int: length including double count for double width characters
    """
    # return string len including double count for double width characters
    return sum(1 + (unicodedata.east_asian_width(c) in "WF") for c in string)

def is_latin(uchr):
    """
    checks via the unciode class if a character is LATIN char based

    from
    https://stackoverflow.com/a/3308844/7811993

    Args:
        uchr (str): _description_

    Returns:
        str: flagged LATIN or not char
    """
    try:
        # if we found in the dictionary return
        return cache_latin_letters[uchr]
    except KeyError:
        # find LATIN in uncide type returned and set in dictionary for this character
        return cache_latin_letters.setdefault(uchr, 'LATIN' in unicodedata.name(uchr))

def only_latin_chars(unistr):
    """
    chekcs if a string is based on LATIN chars. No for any CJK, Cyrillic, Hebrew, etc

    from:
    https://stackoverflow.com/a/3308844/7811993

    Args:
        unistr (str): string

    Returns:
        bool: True/False for if string is LATIN char based
    """
    return all(is_latin(uchr) for uchr in unistr if uchr.isalpha())

# def print_header(header, lines=0, header_line=0):
#     """
#     prints header line and header seperator line

#     Args:
#         header (str): header string
#         lines (int, optional): line counter. Defaults to 0.
#         header_line (int, optional): print header counter grigger. Defaults to 0.

#     Returns:
#         int: line counter +1
#     """
#     global page_no
#     if lines == header_line:
#         # add one to the pages shown and reset the lines to start new page
#         page_no += 1
#         lines = 0
#         # print header
#         print(f"{header}")
#     lines += 1
#     return lines

class ReadOnlyOutput:
    """
    for read only listing
    """
    page_no = 1
    page_all = 1
    lines = 0
    header_print = 0
    header_template = ''

    def __init__(self, header_template, max_pages, header_print_line):
        self.page_all = max_pages
        self.header_template = header_template
        self.header_print = header_print_line

    def print_header(self):
        """
        prints header line and header seperator line

        Args:
            header (str): header string
            lines (int, optional): line counter. Defaults to 0.
            header_line (int, optional): print header counter grigger. Defaults to 0.

        Returns:
            int: line counter +1
        """
        if self.lines == self.header_print:
            # add one to the pages shown and reset the lines to start new page
            self.page_no += 1
            self.lines = 0
            # print header
            # print(f"{header}")
            print(self.header_template.format(
                page_no=self.page_no, page_all=self.page_all
            ))
        self.lines += 1

def format_len(string, length):
    """
    in case of CJK characters we need to adjust the format length dynamically
    calculate correct length based on string given

    Args:
        string (str): string
        length (int): format length

    Returns:
        int: adjusted format legnth
    """
    # returns length udpated for string with double byte characters
    # get string length normal, get string length including double byte characters
    # then subtract that from the original length
    return length - (string_len_cjk(string) - len(string))
\
def file_sort_number(file):
    """
    gets the BK number for sorting in the file list

    Args:
        file (str): file name

    Returns:
        int: number found in the BK string or 0 for none
    """
    match = re.match(r'.*\.BK\.(\d+)\.xmp$', file)
    return int(match.group(1)) if match is not None else 0

def output_list_width_adjust(args):
    """
    adjusts the size for the format length for the list output

    Args:
        args (_type_): arguments

    Returns:
        dictionary: format_length dictionary
    """
    # various string lengths
    format_length = {
        'filename': 35,
        'latitude': 18,
        'longitude': 18,
        'code': 4,
        'country': 15,
        'state': 18,
        'city': 20,
        'location': 25,
        'path': 40,
    }
    if args.compact_view:
        reduce_percent = 40
        # all formats are reduced to a mininum, we cut % off
        for format_key in [
            'filename', 'latitude', 'longitude', 'country', 'state', 'city', 'location', 'path'
        ]:
            format_length[format_key] = ceil(
                format_length[format_key] - ((format_length[format_key] / 100) * reduce_percent)
            )
    else:
        # minimum resize size for a column
        resize_width_min = 4
        # the resize percent
        # start with 10, then increase until we reach max
        resize_percent_min = 10
        resize_percent_max = 50
        # abort flag so we can break out of the second loop too
        abort = False
        # formay key order, in which order the elements will be resized
        format_key_order = []
        # resize flag: 0 no, 1: make bigger, -1: make smaller
        # change sizes for print based on terminal size
        # NOTE: in screen or term this data might NOT be correct
        # Current size needs the in between and left/right space data
        current_columns = sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2
        if current_columns < get_terminal_size().columns:
            resize = 1
            format_key_order = ['path', 'location', 'state', 'city', 'country', 'filename']
        else:
            resize = -1
            format_key_order = [
                'latitude', 'longitude', 'path', 'country', 'state', 'city', 'location', 'filename'
            ]
        # if we have no auto adjust
        if resize and args.no_autoadjust:
            # warningn if screen is too small
            if resize == -1:
                print("[!!!] Screen layout might be skewed. Increase Terminal width")
            resize = 0
        else:
            for resize_percent in range(resize_percent_min, resize_percent_max, 10):
                for format_key in format_key_order:
                    resize_width = (format_length[format_key] / 100) * resize_percent
                    # if we down size, make it negative
                    if resize == -1:
                        resize_width *= -1
                    resize_width = ceil(format_length[format_key] + resize_width)
                    # in case too small, keep old one
                    format_length[format_key] = (
                        resize_width
                            if resize_width > resize_width_min else format_length[format_key]
                    )
                    # calc new width for check if we can abort
                    current_columns = (
                        sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2
                    )
                    if (
                        (resize == 1 and current_columns >= get_terminal_size().columns) or
                        (resize == -1 and current_columns < get_terminal_size().columns)
                    ):
                        # check that we are not OVER but one under
                        width_up = get_terminal_size().columns - current_columns - 1
                        if (resize == 1 and width_up < 0) or (resize == -1 and width_up != 0):
                            if format_length['path'] + width_up >= resize_width_min:
                                format_length['path'] += width_up
                        abort = True
                        break
                if abort:
                    break
            if (
                sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2 >
                    get_terminal_size().columns
            ):
                print("[!!!] Screen layout might be skewed. Increase Terminal width")
    return format_length

def get_backup_file_counter(xmp_file, args):
    """
    get backup file counter

    Args:
        xmp_file (str): file name
        args (_type_): arguments

    Returns:
        int: next counter to be used for backup
    """
    # set to 1 for if we have no backups yet
    bk_file_counter = 1
    # get PATH from file and look for .BK. data in this folder matching,
    # output is sorted per BK counter key
    for bk_file in sorted(
        glob.glob(
            # "{path}/{file}*.xmp".format(
            #     path=os.path.split(xmp_file)[0],
            #     file=f"{os.path.splitext(os.path.split(xmp_file)[1])[0]}.BK."
            # )
            os.path.join(
                f"{os.path.split(xmp_file)[0]}",
                f"{os.path.splitext(os.path.split(xmp_file)[1])[0]}.BK.*.xmp"
            )
        ),
        # custom sort key to get the backup files sorted correctly
        key=lambda pos: file_sort_number(pos),
        # key=file_sort_number(),
        reverse=True
    ):
        # BK.1, etc -> get the number
        bk_pos = file_sort_number(bk_file)
        if bk_pos > 0:
            if args.debug:
                print(f"#### **** File: {bk_file}, Counter: {bk_pos} -> {bk_pos + 1}")
            # check if found + 1 is bigger than set, if yes, set to new bk counter
            if bk_pos + 1 > bk_file_counter:
                bk_file_counter = bk_pos + 1
                break
    # return the next correct number for backup
    return bk_file_counter

##############################################################
# ARGUMENT PARSING
##############################################################

def argument_parser():
    """
    Parses the command line arguments

    Returns:
        Namespace: parsed arguments
    """

    parser = argparse.ArgumentParser(
        description='Reverse Geoencoding based on set Latitude/Longitude data in XMP files',
        # formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Sample: (todo)'
    )

    # xmp folder (or folders), or file (or files)
    # note that the target directory or file needs to be writeable
    parser.add_argument(
        '-i',
        '--include-source',
        required=True,
        nargs='*',
        action=WritableDirFolder,
        dest='xmp_sources',
        metavar='XMP SOURCE FOLDER',
        help=(
            'The source folder or folders with the XMP files that need reverse geo encoding '
            'to be set. Single XMP files can be given here'
        )
    )
    # exclude folders
    parser.add_argument(
        '-x',
        '--exclude-source',
        nargs='*',
        action=WritableDirFolder,
        dest='exclude_sources',
        metavar='EXCLUDE XMP SOURCE FOLDER',
        help='Folders and files that will be excluded.'
    )

    # LR database (base folder)
    # get .lrcat file in this folder
    parser.add_argument(
        '-l',
        '--lightroom',
        # required=True,
        action=ReadableDir,
        dest='lightroom_folder',
        metavar='LIGHTROOM FOLDER',
        help='Lightroom catalogue base folder'
    )

    # strict LR check with base path next to the file base name
    parser.add_argument(
        '-s',
        '--strict',
        dest='lightroom_strict',
        action='store_true',
        help='Do strict check for Lightroom files including Path in query'
    )

    # set behaviour override
    # FLAG: default: only set not filled
    # other: overwrite all or overwrite if one is missing,
    # overwrite specifc field (as defined below)
    # fields: Location, City, State, Country, CountryCode
    parser.add_argument(
        '-f',
        '--field',
        action='append',
        type=str.lower,  # make it lowercase for check
        choices=['overwrite', 'location', 'city', 'state', 'country', 'countrycode'],
        dest='field_controls',
        metavar='<overwrite, location, city, state, country, countrycode>',
        help=(
            'On default only set fields that are not set yet. Options are: '
            'Overwrite (write all new), Location, City, State, Country, CountryCode. '
            'Multiple can be given for combination overwrite certain fields only '
            'or set only certain fields. '
            'If with overwrite the field will be overwritten if already set, '
            'else it will be always skipped.'
        )
    )

    parser.add_argument(
        '-d',
        '--fuzzy-cache',
        type=str.lower,
        action=DistanceValues,
        nargs='?',
        const='10m',  # default is 10m
        dest='fuzzy_distance',
        metavar='FUZZY DISTANCE',
        help=(
            'Allow fuzzy distance cache lookup. Optional distance can be given, '
            'if not set default of 10m is used. '
            'Allowed argument is in the format of 12m or 12km'
        )
    )

    # Google Maps API key to overcome restrictions
    parser.add_argument(
        '-g',
        '--google',
        dest='google_api_key',
        metavar='GOOGLE API KEY',
        help='Set a Google API Maps key to overcome the default lookup limitations'
    )

    # use open street maps
    parser.add_argument(
        '-o',
        '--openstreetmap',
        dest='use_openstreetmap',
        action='store_true',
        help='Use openstreetmap instead of Google'
    )

    # email of open street maps requests
    parser.add_argument(
        '-e',
        '--email',
        dest='email',
        metavar='EMIL ADDRESS',
        help='An email address for OpenStreetMap'
    )

    # write api/email settings to config file
    parser.add_argument(
        '-w',
        '--write-settings',
        dest='config_write',
        action='store_true',
        help='Write Google API or OpenStreetMap email to config file'
    )

    # only read data and print on screen, do not write anything
    parser.add_argument(
        '-r',
        '--read-only',
        dest='read_only',
        action='store_true',
        help=(
            'Read current values from the XMP file only, '
            'do not read from LR or lookup any data and write back'
        )
    )

    # only list unset ones
    parser.add_argument(
        '-u',
        '--unset-only',
        dest='unset_only',
        action='store_true',
        help='Only list unset XMP files'
    )

    # only list unset GPS codes
    parser.add_argument(
        '-p',
        '--unset-gps-only',
        dest='unset_gps_only',
        action='store_true',
        help='Only list unset XMP files for GPS fields'
    )

    # don't try to do auto adjust in list view
    parser.add_argument(
        '-a',
        '--no-autoadjust',
        dest='no_autoadjust',
        action='store_true',
        help='Don\'t try to auto adjust columns'
    )

    # compact view, compresses columns down to a minimum
    parser.add_argument(
        '-c',
        '--compact',
        dest='compact_view',
        action='store_true',
        help='Very compact list view'
    )

    # Do not create backup files
    parser.add_argument(
        '-n',
        '--nobackup',
        dest='no_xmp_backup',
        action='store_true',
        help='Do not create a backup from the XMP file'
    )

    # verbose args for more detailed output
    parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        dest='verbose',
        help='Set verbose output level'
    )

    # debug flag
    parser.add_argument(
        '--debug', action='store_true', dest='debug', help='Set detailed debug output'
    )
    # test flag
    parser.add_argument(
        '--test', action='store_true', dest='test', help='Do not write data back to file'
    )

    # read in the argumens
    return parser.parse_args()

##############################################################
# MAIN CODE
##############################################################

def main():
    """
    Main code run
    """
    args = argument_parser()

    # init verbose to 0 if not set
    if not args.verbose:
        args.verbose = 0
    # init exclude source to list if not set
    if not args.exclude_sources:
        args.exclude_sources = []
    # init args unset (for list view) with 0 if unset
    if not args.unset_only:
        args.unset_only = 0

    if args.debug:
        print(
            "### ARGUMENT VARS: "
            f"I: {args.xmp_sources}, X: {args.exclude_sources}, L: {args.lightroom_folder}, "
            f"F: {args.field_controls}, D: {args.fuzzy_distance}, M: {args.use_openstreetmap}, "
            f"G: {args.google_api_key}, E: {args.email}, R: {args.read_only}, "
            f"U: {args.unset_only}, A: {args.no_autoadjust}, C: {args.compact_view}, "
            f"N: {args.no_xmp_backup}, W: {args.config_write}, V: {args.verbose}, "
            f"D: {args.debug}, T: {args.test}"
        )

    # error flag
    error = False
    # set search map type
    map_type = 'google' if not args.use_openstreetmap else 'openstreetmap'
    # if -g and -o, error
    if args.google_api_key and args.use_openstreetmap:
        print("You cannot set a Google API key and use OpenStreetMap at the same time")
        error = True
    # or if -g and -e
    if args.google_api_key and args.email:
        print("You cannot set a Google API key and OpenStreetMap email at the same time")
        error = True
    # or -e and no -o
    if args.email and not args.use_openstreetmap:
        print("You cannot set an OpenStreetMap email and not use OpenStreetMap")
        error = True
    # if email and not basic valid email (@ .)
    if args.email:
        if not re.match(r'^.+@.+\.[A-Za-z]{1,}$', args.email):
            print(f"Not a valid email for OpenStreetMap: {args.email}")
            error = True
    # on error exit here
    if error:
        sys.exit(1)

    config = configparser.ConfigParser()
    # try to find config file in following order
    # $HOME/.config/
    config_file = 'reverse_geolocate.cfg'
    config_folder = os.path.expanduser('~/.config/reverseGeolocate/')
    config_data = os.path.join(f"{config_folder}", f"{config_file}")
    # if file exists read, if not skip unless we have write flag and
    # google api or openstreetmaps email
    if os.path.isfile(config_data):
        config.read(config_data)
        # check if api group & setting is there. also never overwrite argument given data
        if 'API' in config:
            if 'googleapikey' in config['API']:
                if not args.google_api_key:
                    args.google_api_key = config['API']['googleapikey']
            if 'openstreetmapemail' in config['API']:
                if not args.email:
                    args.email = config['API']['openstreetmapemail']
    # write data if exists and changed
    if args.config_write and (args.google_api_key or args.email):
        config_change = False
        # check if new value differs, if yes, change and write
        if 'API' not in config:
            config['API'] = {}
        if (
            args.google_api_key and ('googleapikey' not in config['API'] or
            config['API']['googleapikey'] != args.google_api_key)
        ):
            config['API']['googleapikey'] = args.google_api_key
            config_change = True
        if (
            args.email and ('openstreetmapemail' not in config['API'] or
            config['API']['openstreetmapemail'] != args.email)
        ):
            config['API']['openstreetmapemail'] = args.email
            config_change = True
        if config_change:
            # if we do not have the base folder create that first
            if not os.path.exists(config_folder):
                os.makedirs(config_folder)
            with open(config_data, 'w', encoding="UTF-8") as fptr:
                config.write(fptr)
    if args.debug:
        print(f"### OVERRIDE API: G: {args.google_api_key}, O: {args.email}")

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
        'GPSLatitude': consts.XMP_NS_EXIF,
        'GPSLongitude': consts.XMP_NS_EXIF,
        'Location': consts.XMP_NS_IPTCCore,
        'City': consts.XMP_NS_Photoshop,
        'State': consts.XMP_NS_Photoshop,
        'Country': consts.XMP_NS_Photoshop,
        'CountryCode': consts.XMP_NS_IPTCCore
    }
    # non lat/long fields (for loc loops)
    data_set_loc = ('Location', 'City', 'State', 'Country', 'CountryCode')
    # one xmp data set
    data_set = {
        'GPSLatitude': '',
        'GPSLongitude': '',
        'Location': '',
        'City': '',
        'State': '',
        'Country': '',
        'CountryCode': ''
    }
    # original set for compare (is constant unchanged)
    data_set_original = {}
    # cache set to avoid double lookups for identical Lat/Ling
    data_cache = {}
    # work files, all files + folders we need to work on
    work_files = []
    # all failed files
    failed_files = []
    # use lightroom
    use_lightroom = False
    # path to lightroom database
    lightroom_database = ''
    # cursors & query
    query = ''
    cur = None
    lrdb = None
    # count variables
    count = {
        'all': 0,
        'listed': 0,
        'read': 0,
        'map': 0,
        'cache': 0,
        'fuzzy_cache': 0,
        'lightroom': 0,
        'changed': 0,
        'failed': 0,
        'skipped': 0,
        'not_found': 0,
        'many_found': 0,
    }

    # do lightroom stuff only if we have the lightroom folder
    if args.lightroom_folder:
        # query string for lightroom DB check
        query = (
            'SELECT Adobe_images.id_local, AgLibraryFile.baseName, '
            'AgLibraryRootFolder.absolutePath, AgLibraryRootFolder.name as realtivePath, '
            'AgLibraryFolder.pathFromRoot, AgLibraryFile.originalFilename, '
            'AgHarvestedExifMetadata.gpsLatitude, AgHarvestedExifMetadata.gpsLongitude, '
            'AgHarvestedIptcMetadata.locationDataOrigination, '
            'AgInternedIptcLocation.value as Location, AgInternedIptcCity.value as City, '
            'AgInternedIptcState.value as State, AgInternedIptcCountry.value as Country, '
            'AgInternedIptcIsoCountryCode.value as CountryCode '
            'FROM AgLibraryFile, AgHarvestedExifMetadata, AgLibraryFolder, '
            'AgLibraryRootFolder, Adobe_images '
            'LEFT JOIN AgHarvestedIptcMetadata '
            'ON Adobe_images.id_local = AgHarvestedIptcMetadata.image '
            'LEFT JOIN AgInternedIptcLocation '
            'ON AgHarvestedIptcMetadata.locationRef = AgInternedIptcLocation.id_local '
            'LEFT JOIN AgInternedIptcCity '
            'ON AgHarvestedIptcMetadata.cityRef = AgInternedIptcCity.id_local '
            'LEFT JOIN AgInternedIptcState '
            'ON AgHarvestedIptcMetadata.stateRef = AgInternedIptcState.id_local '
            'LEFT JOIN AgInternedIptcCountry '
            'ON AgHarvestedIptcMetadata.countryRef = AgInternedIptcCountry.id_local '
            'LEFT JOIN AgInternedIptcIsoCountryCode '
            'ON AgHarvestedIptcMetadata.isoCountryCodeRef = AgInternedIptcIsoCountryCode.id_local '
            'WHERE Adobe_images.rootFile = AgLibraryFile.id_local '
            'AND Adobe_images.id_local = AgHarvestedExifMetadata.image '
            'AND AgLibraryFile.folder = AgLibraryFolder.id_local '
            'AND AgLibraryFolder.rootFolder = AgLibraryRootFolder.id_local '
            'AND AgLibraryFile.baseName = ?'
        )
        # absolutePath + pathFromRoot = path of XMP file - XMP file
        if args.lightroom_strict:
            query += 'AND AgLibraryRootFolder.absolutePath || AgLibraryFolder.pathFromRoot = ?'

        # connect to LR database for reading
        # open the folder and look for the first lrcat file in there
        for file in os.listdir(args.lightroom_folder):
            if file.endswith('.lrcat'):
                lightroom_database = os.path.join(args.lightroom_folder, file)
                lrdb = sqlite3.connect(lightroom_database)
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

    # init the XML meta for handling
    xmp = XMPMeta()

    # loop through the xmp_sources (folder or files)
    # and read in the XMP data for LAT/LONG, other data
    for xmp_file_source in args.xmp_sources:
        # if folder, open and loop
        # NOTE: we do check for folders in there, if there are we recourse traverse them
        # also check that folder is not in exclude list
        if (
            os.path.isdir(xmp_file_source) and
            xmp_file_source.rstrip(os.sep) not in [x.rstrip(os.sep)
                for x in args.exclude_sources]
        ):
            # open folder and look for any .xmp files and push them into holding array
            # if there are folders, dive into them
            # or glob glob all .xmp files + directory
            for root, _, files in os.walk(xmp_file_source):
                for file in sorted(files):
                    # 1) but has no .BK. inside
                    # 2) file is not in exclude list
                    # 3) full folder is not in exclude list
                    file_path = os.path.join(f"{root}", f"{file}")
                    if (
                        file.endswith(".xmp") and ".BK." not in file
                        and file_path not in args.exclude_sources
                        and root.rstrip(os.sep) not in [x.rstrip(os.sep)
                            for x in args.exclude_sources]
                    ):
                        if file_path not in work_files:
                            work_files.append(file_path)
                            count['all'] += 1
        else:
            # not already added to list and not in the exclude list either
            if xmp_file_source not in work_files and xmp_file_source not in args.exclude_sources:
                work_files.append(xmp_file_source)
                count['all'] += 1
    if args.debug:
        print(f"### Work Files {work_files}")

    format_line = ''
    header_line = ''
    format_length = {}
    header_print = None
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
            " {{{{filename:<{}}}}} | {{{{latitude:>{}}}}} | {{{{longitude:>{}}}}} | "
            "{{{{code:<{}}}}} | {{{{country:<{}}}}} | {{{{state:<{}}}}} | {{{{city:<{}}}}} | "
            "{{{{location:<{}}}}} | {{{{path:<{}}}}}"
        ).format(
            "{filenamelen}",
            format_length['latitude'],
            format_length['longitude'],
            format_length['code'],
            "{countrylen}",
            "{statelen}",
            "{citylen}",
            "{locationlen}",
            "{pathlen}"  # set path len replacer variable
        )
        # header line format:
        # blank line
        # header title
        # seperator line
        header_line = (
            "{}"
            "{}"
            "{}"
        ).format(
            # can later be set to something else, eg page numbers
            '> Page {page_no:,}/{page_all:,}',
            # pre replace path length before we add the header titles
            format_line.format(
                filenamelen=format_length['filename'],
                countrylen=format_length['country'],
                statelen=format_length['state'],
                citylen=format_length['city'],
                locationlen=format_length['location'],
                pathlen=format_length['path']
            ).format(  # the header title line
                filename='File'[:format_length['filename']],
                latitude='Latitude'[:format_length['latitude']],
                longitude='Longitude'[:format_length['longitude']],
                code='Code',
                country='Country'[:format_length['country']],
                state='State'[:format_length['state']],
                city='City'[:format_length['city']],
                location='Location'[:format_length['location']],
                path='Path'[:format_length['path']]
            ),
            "{}+{}+{}+{}+{}+{}+{}+{}+{}".format(  # the header seperator line
                '-' * (format_length['filename'] + 2),
                '-' * (format_length['latitude'] + 2),
                '-' * (format_length['longitude'] + 2),
                '-' * (format_length['code'] + 2),
                '-' * (format_length['country'] + 2),
                '-' * (format_length['state'] + 2),
                '-' * (format_length['city'] + 2),
                '-' * (format_length['location'] + 2),
                '-' * (format_length['path'] + 2)
            )
        )
        # header print class
        header_print = ReadOnlyOutput(header_line, page_all, header_repeat)
        # print header
        # print_header(header_line.format(page_no=page_no, page_all=page_all))
        header_print.print_header()
        # print no files found if we have no files
        if not work_files:
            print(f"{'[!!!] No files found':<60}")

    # ### MAIN WORK LOOP
    # now we just loop through each file and work on them
    for xmp_file in work_files:  # noqa: C901
        if not args.read_only:
            print(f"---> {xmp_file}: ", end='')

        # ### ACTION FLAGs
        write_file = False

        # ### XMP FILE READING
        # open file & read all into buffer
        with open(xmp_file, 'r', encoding="UTF-8") as fptr:
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
                data_set[xmp_field_key] = ''
            if args.debug:
                print(
                    f"### => XMP: {xmp_field_value}:{xmp_field_key} => {data_set[xmp_field_key]}"
                )
        if args.read_only:
            # view only if list all or if data is unset
            if (
                (not args.unset_only and not args.unset_gps_only) or
                (args.unset_only and '' in data_set.values()) or
                (args.unset_gps_only and (not data_set['GPSLatitude'] or
                    not data_set['GPSLongitude']))
            ):
                # for read only we print out the data formatted
                # headline check, do we need to print that
                # count['read'] = print_header(
                #   header_line.format(page_no=page_no, page_all=page_all),
                #   count['read'],
                #   header_repeat
                # )
                if header_print is not None:
                    header_print.print_header()
                # the data content
                print(format_line.format(
                        # for all possible non latin fields we do adjust
                        # if it has double byte characters inside
                        filenamelen=format_len(
                            shorten_path(xmp_file, format_length['filename'], file_only=True),
                            format_length['filename']
                        ),
                        countrylen=format_len(
                            shorten_string(data_set['Country'], width=format_length['country']),
                            format_length['country']
                        ),
                        statelen=format_len(
                            shorten_string(data_set['State'], width=format_length['state']),
                            format_length['state']
                        ),
                        citylen=format_len(
                            shorten_string(data_set['City'], width=format_length['city']),
                            format_length['city']
                        ),
                        locationlen=format_len(
                            shorten_string(data_set['Location'], width=format_length['location']),
                            format_length['location']
                        ),
                        pathlen=format_len(
                            shorten_path(xmp_file, format_length['path'], path_only=True),
                            format_length['path']
                        )
                    ).format(
                        # shorten from the left
                        filename=shorten_path(
                            xmp_file, format_length['filename'],
                            file_only=True
                        ),
                        # cut off from the right
                        latitude=(
                            str(convert_dms_to_lat(data_set['GPSLatitude']))
                                [:format_length['latitude']]
                        ),
                        longitude=(
                            str(convert_dms_to_long(data_set['GPSLongitude']))
                                [:format_length['longitude']]
                        ),
                        # is only 2 chars
                        code=data_set['CountryCode'][:2].center(4),
                        # shorten from the right
                        country=shorten_string(
                            data_set['Country'], width=format_length['country']
                        ),
                        state=shorten_string(
                            data_set['State'], width=format_length['state']
                        ),
                        city=shorten_string(
                            data_set['City'], width=format_length['city']
                        ),
                        location=shorten_string(
                            data_set['Location'],
                            width=format_length['location']
                        ),
                        path=shorten_path(
                            xmp_file,
                            format_length['path'],
                            path_only=True
                        )
                    )
                )
                count['listed'] += 1
        else:
            # ### LR Action Flag (data ok)
            lightroom_data_ok = True
            lrdb_row = {}
            # ### LIGHTROOM DB READING
            # read in data from DB if we uave lightroom folder
            if use_lightroom and cur is not None:
                # get the base file name, we need this for lightroom
                xmp_file_basename = os.path.splitext(os.path.split(xmp_file)[1])[0]
                # try to get this file name from the DB
                lr_query_params = [xmp_file_basename]
                # for strict check we need to get the full path
                # and add / as the LR stores the last folder with /
                if args.lightroom_strict:
                    # xmp_file_path = "{}/{}".format(os.path.split(xmp_file)[0], '/')
                    xmp_file_path = f"{os.path.split(xmp_file)[0]}/{'/'}"
                    lr_query_params.append(xmp_file_path)
                cur.execute(query, lr_query_params)
                # get the row data
                lrdb_row = cur.fetchone()
                # abort the read because we found more than one row
                if cur.fetchone() is not None:
                    print("(!) Lightroom DB returned more than one more row")
                    lightroom_data_ok = False
                    count['many_found'] += 1
                # Notify if we couldn't find one
                elif not lrdb_row:
                    print("(!) Could not get data from Lightroom DB")
                    lightroom_data_ok = False
                    count['not_found'] += 1
                if args.debug and lrdb_row:
                    print(f"### LightroomDB: {tuple(lrdb_row)} / {lrdb_row.keys()}")

            # create a duplicate copy for later checking if something changed
            data_set_original = data_set.copy()
            # check if LR exists and use this to compare to XMP data
            # is LR GPS and no XMP GPS => use LR and set XMP
            # same for location names
            # if missing in XMP but in LR -> set in XMP
            # if missing in both do lookup in Maps
            if use_lightroom and lightroom_data_ok:
                # check lat/long separate
                if lrdb_row['gpsLatitude'] and not data_set['GPSLatitude']:
                    # we need to convert to the Degree,Min.sec[NSEW] format
                    data_set['GPSLatitude'] = convert_lat_to_dms(lrdb_row['gpsLatitude'])
                if lrdb_row['gpsLongitude'] and not data_set['GPSLongitude']:
                    data_set['GPSLongitude'] = convert_long_to_dms(lrdb_row['gpsLongitude'])
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
                    print(
                        f"### *** CACHE: {cache_key}: "
                        f"{'NO' if cache_key not in data_cache else 'YES'}"
                    )
                # main chache check = identical
                # second cache level check is on distance:
                # default distance is 10m, can be set via flag
                # check distance to previous cache entries (reverse newest to oldest)
                # and match before we do google lookup
                if cache_key not in data_cache:
                    has_fuzzy_cache = False
                    best_match_latlong = ''
                    if args.fuzzy_distance:
                        shortest_distance = args.fuzzy_distance
                        # check if we have fuzzy distance, if no valid found do maps lookup
                        for _cache_key in data_cache:
                            # split up cache key so we can use in the distance calc method
                            to_lat_long = _cache_key.split('#')
                            # get the distance based on current set + cached set
                            # print(
                            #     f"Lookup f-long {data_set['GPSLongitude']} "
                            #     f"f-lat {data_set['GPSLatitude']} "
                            #     f"t-long {to_lat_long[0]} t-lat {to_lat_long[1]}"
                            # )
                            distance = get_distance(
                                from_longitude=data_set['GPSLongitude'],
                                from_latitude=data_set['GPSLatitude'],
                                to_longitude=to_lat_long[0],
                                to_latitude=to_lat_long[1]
                            )
                            if args.debug:
                                print(
                                    f"### **= FUZZY CACHE: => distance: {distance} (m), "
                                    f"shortest: {shortest_distance}"
                                )
                            if distance <= shortest_distance:
                                # set new distance and keep current best matching location
                                shortest_distance = distance
                                best_match_latlong = _cache_key
                                has_fuzzy_cache = True
                                if args.debug:
                                    print(
                                        "### ***= FUZZY CACHE: YES => "
                                        f"Best match: {best_match_latlong}"
                                    )
                    if not has_fuzzy_cache:
                        # get location from maps (google or openstreetmap)
                        maps_location = reverse_geolocate(
                            latitude=data_set['GPSLatitude'],
                            longitude=data_set['GPSLongitude'],
                            map_type=map_type,
                            args=args
                        )
                        # cache data with Lat/Long
                        data_cache[cache_key] = maps_location
                        from_cache = False
                    else:
                        maps_location = data_cache[best_match_latlong]
                        # cache this one, because the next one will match this one too
                        # we don't need to loop search again for the same fuzzy location
                        data_cache[cache_key] = maps_location
                        count['cache'] += 1
                        count['fuzzy_cache'] += 1
                        from_cache = True
                else:
                    # load location from cache
                    maps_location = data_cache[cache_key]
                    count['cache'] += 1
                    from_cache = True
                # overwrite sets (note options check here)
                if args.debug:
                    print(f"### Map Location ({map_type}): {maps_location}")
                # must have at least the country set to write anything back
                if maps_location['Country']:
                    for loc in data_set_loc:
                        # only write to XMP if overwrite check passes
                        if check_overwrite(data_set_original[loc], loc, args.field_controls, args):
                            data_set[loc] = maps_location[loc]
                            xmp.set_property(xmp_fields[loc], loc, maps_location[loc])
                            write_file = True
                    if write_file:
                        count['map'] += 1
                else:
                    print("(!) Could not geo loaction data ", end='')
                    failed = True
            else:
                if args.debug:
                    print(
                        f"Lightroom data use: {use_lightroom}, "
                        f"Lightroom data ok: {lightroom_data_ok}"
                    )
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
                        if (
                            value != data_set_original[key] and
                            check_overwrite(
                                data_set_original[key], key, args.field_controls, args
                            )
                        ):
                            xmp.set_property(xmp_fields[key], key, value)
                            write_file = True
                    if write_file:
                        count['lightroom'] += 1
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
                            f"{os.path.splitext(xmp_file)[0]}.BK."
                            f"{bk_file_counter}{os.path.splitext(xmp_file)[1]}"
                        )
                    # write back to riginal file
                    with open(xmp_file, 'w', encoding="UTF-8") as fptr:
                        fptr.write(xmp.serialize_to_str(omit_packet_wrapper=True))
                else:
                    print(f"[TEST] Would write {data_set} {xmp_file}", end='')
                if from_cache:
                    print("[UPDATED FROM CACHE]")
                else:
                    print("[UPDATED]")
                count['changed'] += 1
            elif failed:
                print("[FAILED]")
                count['failed'] += 1
                # log data to array for post print
                failed_files.append(xmp_file)
            else:
                print("[SKIP]")
                count['skipped'] += 1

    # close DB connection
    if use_lightroom and lrdb is not None:
        lrdb.close()

    # end stats only if we write
    print(f"{'=' * 40}")
    print(f"XMP Files found              : {count['all']:9,}")
    if args.read_only:
        print(f"XMP Files listed             : {count['listed']:9,}")
    if not args.read_only:
        print(f"Updated                      : {count['changed']:9,}")
        print(f"Skipped                      : {count['skipped']:9,}")
        print(f"New GeoLocation from Map     : {count['map']:9,}")
        print(f"GeoLocation from Cache       : {count['cache']:9,}")
        print(f"GeoLocation from Fuzzy Cache : {count['fuzzy_cache']:9,}")
        print(f"Failed reverse GeoLocate     : {count['failed']:9,}")
        if use_lightroom:
            print(f"GeoLocaction from Lightroom  : {count['lightroom']:9,}")
            print(f"No Lightroom data found      : {count['not_found']:9,}")
            print(f"More than one found in LR    : {count['many_found']:9,}")
        # if we have failed data
        if len(failed_files) > 0:
            print(f"{'-' * 40}")
            print("Files that failed to update:")
            print(f"{', '.join(failed_files)}")


##############################################################
# MAIN RUN
##############################################################

main()

# __END__
