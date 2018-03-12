#!/usr/bin/env python3

# AUTHOR : Clemens Schwaighofer
# DATE   : 2018/2/20
# LICENSE: GPLv3
# DESC   : Set the reverse Geo location (name) from Lat/Long data in XMP files in a lightroom catalogue
#          * tries to get pre-set geo location from LR catalog
#          * if not found tries to get data from Google
#          * all data is translated into English with long vowl system (aka ou or oo is ō)
# MUST HAVE: Python XMP Toolkit (http://python-xmp-toolkit.readthedocs.io/)

import argparse
import sqlite3
import requests
import configparser
# import textwrap
import glob
import os
import sys
import re
# Note XMPFiles does not work with sidecar files, need to read via XMPMeta
from libxmp import XMPMeta, consts
from shutil import copyfile, get_terminal_size
from math import ceil

##############################################################
# FUNCTIONS
##############################################################


# ARGPARSE HELPERS

# call: writable_dir_folder
# checks if this is a writeable folder OR file
# AND it works on nargs *
class writable_dir_folder(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        # we loop through list (this is because of nargs *)
        for prospective_dir in values:
            # if valid and writeable (dir or file)
            if os.access(prospective_dir, os.W_OK):
                # init new output array
                out = []
                # if we have a previous list in the namespace extend current list
                if type(getattr(namespace, self.dest)) is list:
                    out.extend(getattr(namespace, self.dest))
                # add the new dir to it
                out.append(prospective_dir)
                # and write that list back to the self.dest in the namespace
                setattr(namespace, self.dest, out)
            else:
                raise argparse.ArgumentTypeError("writable_dir_folder: {0} is not a writable dir".format(prospective_dir))


# call: readable_dir
# custom define to check if it is a valid directory
class readable_dir(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        prospective_dir = values
        if not os.path.isdir(prospective_dir):
            raise argparse.ArgumentTypeError("readable_dir:{0} is not a valid path".format(prospective_dir))
        if os.access(prospective_dir, os.R_OK):
            setattr(namespace, self.dest, prospective_dir)
        else:
            raise argparse.ArgumentTypeError("readable_dir:{0} is not a readable dir".format(prospective_dir))


# MAIN FUNCTIONS

# METHOD: reverseGeolocate
# PARAMS: latitude, longitude, map search target (google or openstreetmap)
# RETURN: dict with all data (see below)
# DESC  : wrapper to call to either the google or openstreetmap
def reverseGeolocate(longitude, latitude, map_type):
    # clean up long/lat
    # they are stored with N/S/E/W if they come from an XMP
    # format: Deg,Min.Sec[NSEW]
    # NOTE: lat is N/S, long is E/W
    # detect and convert
    lat_long = longLatReg(longitude=longitude, latitude=latitude)
    # which service to use
    if map_type == 'google':
        return reverseGeolocateGoogle(lat_long['longitude'], lat_long['latitude'])
    elif map_type == 'openstreetmap':
        return reverseGeolocateOpenStreetMap(lat_long['longitude'], lat_long['latitude'])
    else:
        return {
            'Country': '',
            'status': 'ERROR',
            'error': 'Map type not valid'
        }


# METHOD: reverseGeolocateInit
# PARAMS: longitude, latitude
# RETURN: empty geolocation dictionary, or error flag if lat/long is not valid
# DESC  : inits the dictionary for return, and checks the lat/long on valid
#         returns geolocation dict with status = 'ERROR' if an error occurded
def reverseGeolocateInit(longitude, latitude):
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
    latlong_re = re.compile('^\d+\.\d+$')
    if not latlong_re.match(str(longitude)) or not latlong_re.match(str(latitude)):
        geolocation['status'] = 'ERROR'
        geolocation['error_message'] = 'Latitude {} or Longitude {} are not valid'.format(latitude, longitude)
    return geolocation


# METHOD: reverseGeolocateOpenStreetMap
# PARAMS: latitude, longitude
# RETURN: OpenStreetMap reverse lookcation lookup
#         dict with locaiton, city, state, country, country code
#         if not fillable, entry is empty
# SAMPLE: https://nominatim.openstreetmap.org/reverse.php?format=jsonv2&lat=<latitude>&lon=<longitude>&zoom=21&accept-languge=en-US,en&
def reverseGeolocateOpenStreetMap(longitude, latitude):
    # init
    geolocation = reverseGeolocateInit(longitude, latitude)
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
    url = "{base}".format(base=base)
    response = requests.get(url, params=payload)
    # debug output
    if args.debug:
        print("OpenStreetMap search for Lat: {}, Long: {}".format(latitude, longitude))
    if args.debug and args.verbose >= 1:
        print("OpenStreetMap response: {} => JSON: {}".format(response, response.json()))
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
        for loc_index in type_map:
            for index in type_map[loc_index]:
                if index in addr and not geolocation[loc_index]:
                    geolocation[loc_index] = addr[index]
    else:
        geolocation['status'] = 'ERROR'
        geolocation['error_message'] = response.json()['error']
        print("Error in request: {}".format(geolocation['error']))
    # return
    return geolocation


# METHOD: reverseGeolocateGoogle
# PARAMS: latitude, longitude
# RETURN: Google Maps reverse location lookup
#         dict with location, city, state, country, country code
#         if not fillable, entry is empty
# SAMPLE: http://maps.googleapis.com/maps/api/geocode/json?latlng=<latitude>,<longitude>&sensor=false&key=<api key>
def reverseGeolocateGoogle(longitude, latitude):
    # init
    geolocation = reverseGeolocateInit(longitude, latitude)
    if geolocation['status'] == 'ERROR':
        return geolocation
    # sensor (why?)
    sensor = 'false'
    # request to google
    # if a google api key is used, the request has to be via https
    protocol = 'https://' if args.google_api_key else 'http://'
    base = "maps.googleapis.com/maps/api/geocode/json?"
    # build the base params
    payload = {
        'latlng': '{lat},{lon}'.format(lon=longitude, lat=latitude),
        'sensor': sensor
    }
    # if we have a google api key, add it here
    if args.google_api_key:
        payload['key'] = args.google_api_key
    # build the full url and send it to google
    url = "{protocol}{base}".format(protocol=protocol, base=base)
    response = requests.get(url, params=payload)
    # debug output
    if args.debug:
        print("Google search for Lat: {}, Long: {} with {}".format(longitude, latitude, response.url))
    if args.debug and args.verbose >= 1:
        print("Google response: {} => JSON: {}".format(response, response.json()))
    # type map
    # For automated return of correct data into set to return
    type_map = {
        'CountryCode': ['country'],
        'Country': ['country'],
        'State': ['administrative_area_level_1', 'administrative_area_level_2'],
        'City': ['locality'],
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
                    for loc_index in type_map:
                        for index in type_map[loc_index]:
                            # this is an array, so we need to loop through each
                            for addr in entry['address_components']:
                                # in types check that index is in there and the location is not yet set
                                if index in addr['types'] and not geolocation[loc_index]:
                                    # for country code we need to use short name, else we use long name
                                    if loc_index == 'CountryCode':
                                        geolocation[loc_index] = addr['short_name']
                                    else:
                                        geolocation[loc_index] = addr['long_name']
        # write OK status
        geolocation['status'] = response.json()['status']
    else:
        geolocation['error_message'] = response.json()['error_message']
        geolocation['status'] = response.json()['status']
        print("Error in request: {} {}".format(geolocation['status'], geolocation['error_message']))

    # return
    return geolocation


# METHOD: convertLatLongToDMS
# PARAMS: latLong in (-)N.N format, lat or long flag (else we can't set N/S)
# RETURN: Deg,Min.Sec(NESW) format
# DESC  : convert the LR format of N.N to the Exif GPS format
def convertLatLongToDMS(lat_long, is_latitude=False, is_longitude=False):
    # minus part before . and then multiply rest by 60
    degree = int(abs(lat_long))
    minutes = round((float(abs(lat_long)) - int(abs(lat_long))) * 60, 10)
    if is_latitude is True:
        direction = 'S' if int(lat_long) < 0 else 'N'
    elif is_longitude is True:
        direction = 'W' if int(lat_long) < 0 else 'E'
    else:
        direction = '(INVALID)'
    return "{},{}{}".format(degree, minutes, direction)


# wrapper functions for Long/Lat calls: latitude
def convertLatToDMS(lat_long):
    return convertLatLongToDMS(lat_long, is_latitude=True)


# wrapper for Long/Lat call: longitute
def convertLongToDMS(lat_long):
    return convertLatLongToDMS(lat_long, is_longitude=True)


# METHOD: longLatReg
# PARAMS: latitude in (n,n.nNSEW format), longitude
# RETURN: dict with converted lat/long
# DESC  : converts the XMP/EXIF formatted GPS Long/Lat coordinates
#         from the <Degree>,<Minute.Second><NSEW> to the normal float
#         number used in google/lr internal
def longLatReg(longitude, latitude):
    # regex
    latlong_re = re.compile('^(\d+),(\d+\.\d+)([NESW]{1})$')
    # dict for loop
    lat_long = {
        'longitude': longitude,
        'latitude': latitude
    }
    for element in lat_long:
        # match if it is exif GPS format
        m = latlong_re.match(lat_long[element])
        if m is not None:
            # convert from Degree, Min.Sec into float format
            lat_long[element] = float(m.group(1)) + (float(m.group(2)) / 60)
            # if S or W => inverse to negative
            if m.group(3) == 'S' or m.group(3) == 'W':
                lat_long[element] *= -1
    return lat_long


# wrapper calls for DMS to Lat/Long: latitude
def convertDMStoLat(lat_long):
    return longLatReg('0,0.0N', lat_long)['latitude']


# # wrapper calls for DMS to Lat/Long: longitude
def convertDMStoLong(lat_long):
    return longLatReg(lat_long, '0,0.0N')['longitude']


# METHOD: checkOverwrite
# PARAMS: data: value field, key: XMP key, field_controls: array from args
# RETURN: true/false
# DESC  : checks with field control flags if given data for key should be written
#         1) data is not set
#         2) data is set or not and field_control: overwrite only set
#         3) data for key is not set, but only for key matches field_control
#         4) data for key is set or not, but only for key matches field_control and overwrite is set
def checkOverwrite(data, key, field_controls):
    status = False
    # init field controls for empty
    if not field_controls:
        field_controls = []
    if not data and (len(field_controls) == 0 or ('overwrite' in field_controls and len(field_controls) == 1)):
        status = True
    elif not data and key.lower() in field_controls:
        status = True
    elif data and 'overwrite' in field_controls and len(field_controls) == 1:
        status = True
    elif data and key.lower() in field_controls and 'overwrite' in field_controls:
        status = True
    if args.debug:
        print("Data set: {data_set}, Key: {key_lower}, Field Controls len: {field_count}, Overwrite: {overwrite_flag}, Key in Field Controls: {key_ok}, OVERWRITE: {do_overwrite}".format(
            data_set='YES' if data else 'NO',
            key_lower=key.lower(),
            field_count=len(field_controls),
            overwrite_flag='OVERWRITE' if 'overwrite' in field_controls else 'NOT OVERWRITE',
            key_ok='KEY OK' if key.lower() in field_controls else 'KEY NOT MATCHING',
            do_overwrite=status
        ))
    return status


# METHOD: shortenPath
# PARAMS: path = string, length = int, file_only = true/false, path_only = true/false
# RETURN: shortend path with ... in front
# DESC  : shortes a path from the left so it fits into lenght
#         if file only is set to true, it will split the file, if path only is set, only the path
def shortenPath(path, length=30, file_only=False, path_only=False):
    length = length - 3
    # I assume the XMP file name has no CJK characters inside, so I strip out the path
    # The reason is that if there are CJK characters inside it will screw up the formatting
    if file_only:
        path = os.path.split(path)[1]
    if path_only:
        path = os.path.split(path)[0]
    if len(path) > length:
        path = "{} {}".format("..", path[len(path) - length:])
    return path


# METHOD: shortenString
# PARAMS: string, shorten width, override shorten placeholder
# RETURN: shortened string
# DESC  : shortens a string to width and attached placeholder
def shortenString(string, width, placeholder='..'):
    if len(str(string)) > width:
        width -= len(placeholder)
        return "{}{}".format(str(string)[:width], placeholder)
    else:
        return str(string)


# METHOD: printHeader
# PARAMS: header string, line counter, print header counter trigger
# RETURN: line counter +1
# DESC  : prints header line and header seperator line
def printHeader(header, lines=0, header_line=0):
    global page_no
    if lines == header_line:
        # add one to the pages shown and reset the lines to start new page
        page_no += 1
        lines = 0
        # print header
        print("{}".format(header))
    lines += 1
    return lines


# METHOD: fileSortNumber
# PARAMS: file name
# RETURN: number found in the BK string or 0 for none
# DESC  : gets the BK number for sorting in the file list
def fileSortNumber(file):
    m = re.match('.*\.BK\.(\d+)\.xmp$', file)
    return int(m.group(1)) if m is not None else 0

##############################################################
# ARGUMENT PARSNING
##############################################################


parser = argparse.ArgumentParser(
    description='Reverse Geoencoding based on set Latitude/Longitude data in XMP files',
    # formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog='Sample: (todo)'
)

# xmp folder (or folders), or file (or files)
# note that the target directory or file needs to be writeable
parser.add_argument('-i', '--include-source',
                    required=True,
                    nargs='*',
                    action=writable_dir_folder,
                    dest='xmp_sources',
                    metavar='XMP SOURCE FOLDER',
                    help='The source folder or folders with the XMP files that need reverse geo encoding to be set. Single XMP files can be given here'
                    )
# exclude folders
parser.add_argument('-x', '--exclude-source',
                    nargs='*',
                    action=writable_dir_folder,
                    dest='exclude_sources',
                    metavar='EXCLUDE XMP SOURCE FOLDER',
                    help='Folders and files that will be excluded.'
                    )

# LR database (base folder)
# get .lrcat file in this folder
parser.add_argument('-l', '--lightroom',
                    # required=True,
                    action=readable_dir,
                    dest='lightroom_folder',
                    metavar='LIGHTROOM FOLDER',
                    help='Lightroom catalogue base folder'
                    )

# strict LR check with base path next to the file base name
parser.add_argument('-s', '--strict',
                    dest='lightroom_strict',
                    action='store_true',
                    help='Do strict check for Lightroom files including Path in query'
                    )

# set behaviour override
# FLAG: default: only set not filled
# other: overwrite all or overwrite if one is missing, overwrite specifc field (as defined below)
# fields: Location, City, State, Country, CountryCode
parser.add_argument('-f', '--field',
                    action='append',
                    type=str.lower,  # make it lowercase for check
                    choices=['overwrite', 'location', 'city', 'state', 'country', 'countrycode'],
                    dest='field_controls',
                    metavar='<overwrite, location, city, state, country, countrycode>',
                    help='On default only set fields that are not set yet. Options are: '\
                         'Overwrite (write all new), Location, City, State, Country, CountryCode. '\
                         'Multiple can be given for combination overwrite certain fields only or set only certain fields. '\
                         'If with overwrite the field will be overwritten if already set, else it will be always skipped.'
                    )

# Google Maps API key to overcome restrictions
parser.add_argument('-g', '--google',
                    dest='google_api_key',
                    metavar='GOOGLE API KEY',
                    help='Set a Google API Maps key to overcome the default lookup limitations'
                    )

# use open street maps
parser.add_argument('-o', '--openstreetmap',
                    dest='use_openstreetmap',
                    action='store_true',
                    help='Use openstreetmap instead of Google'
                    )

# email of open street maps requests
parser.add_argument('-e', '--email',
                    dest='email',
                    metavar='EMIL ADDRESS',
                    help='An email address for OpenStreetMap'
                    )

# write api/email settings to config file
parser.add_argument('-w', '--write-settings',
                    dest='config_write',
                    action='store_true',
                    help='Write Google API or OpenStreetMap email to config file'
                    )

# only read data and print on screen, do not write anything
parser.add_argument('-r', '--read-only',
                    dest='read_only',
                    action='store_true',
                    help='Read current values from the XMP file only, do not read from LR or lookup any data and write back'
                    )

# only list unset ones
parser.add_argument('-u', '--unset-only',
                    dest='unset_only',
                    action='store_true',
                    help='Only list unset XMP files'
                    )

# don't try to do auto adjust in list view
parser.add_argument('-a', '--no-autoadjust',
                    dest='no_autoadjust',
                    action='store_true',
                    help='Don\'t try to auto adjust columns'
                    )

# compact view, compresses columns down to a minimum
parser.add_argument('-c', '--compact',
                    dest='compact_view',
                    action='store_true',
                    help='Very compact list view'
                    )

# Do not create backup files
parser.add_argument('-n', '--nobackup',
                    dest='no_xmp_backup',
                    action='store_true',
                    help='Do not create a backup from the XMP file'
                    )

# verbose args for more detailed output
parser.add_argument('-v', '--verbose',
                    action='count',
                    dest='verbose',
                    help='Set verbose output level'
                    )

# debug flag
parser.add_argument('--debug', action='store_true', dest='debug', help='Set detailed debug output')
# test flag
parser.add_argument('--test', action='store_true', dest='test', help='Do not write data back to file')

# read in the argumens
args = parser.parse_args()

##############################################################
# MAIN CODE
##############################################################

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
    print("### ARGUMENT VARS: I: {incl}, X: {excl}, L: {lr}, F: {fc}, M: {osm}, G: {gp}, E: {em}, R: {read}, U: {us}, A: {adj}, C: {cmp}, N: {nbk}, W: {wrc}, V: {v}, D: {d}, T: {t}".format(
        incl=args.xmp_sources,
        excl=args.exclude_sources,
        lr=args.lightroom_folder,
        fc=args.field_controls,
        osm=args.use_openstreetmap,
        gp=args.google_api_key,
        em=args.email,
        read=args.read_only,
        us=args.unset_only,
        adj=args.no_autoadjust,
        cmp=args.compact_view,
        nbk=args.no_xmp_backup,
        wrc=args.config_write,
        v=args.verbose,
        d=args.debug,
        t=args.test
    ))

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
    if not re.match('^.+@.+\.[A-Za-z]{1,}$', args.email):
        print("Not a valid email for OpenStreetMap: {}".format(args.email))
        error = True
# on error exit here
if error:
    sys.exit(1)

config = configparser.ConfigParser()
# try to find config file in following order
# $HOME/.config/
config_file = 'reverse_geolocate.cfg'
config_folder = os.path.expanduser('~/.config/reverseGeolocate/')
config_data = '{}{}'.format(config_folder, config_file)
# if file exists read, if not skip unless we have write flag and google api or openstreetmaps email
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
    if args.google_api_key and ('googleapikey' not in config['API'] or config['API']['googleapikey'] != args.google_api_key):
        config['API']['googleapikey'] = args.google_api_key
        config_change = True
    if args.email and ('openstreetmapemail' not in config['API'] or config['API']['openstreetmapemail'] != args.email):
        config['API']['openstreetmapemail'] = args.email
        config_change = True
    if config_change:
        # if we do not have the base folder create that first
        if not os.path.exists(config_folder):
            os.makedirs(config_folder)
        with open(config_data, 'w') as fptr:
            config.write(fptr)
if args.debug:
    print("### OVERRIDE API: G: {}, O: {}".format(args.google_api_key, args.email))

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
    'GPSLatitude': consts.XMP_NS_EXIF,  # EXIF GPSLat/Long are stored in Degree,Min.Sec[NESW] format
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
# cursors & query
query = ''
cur = ''
# count variables
count = {
    'all': 0,
    'listed': 0,
    'read': 0,
    'map': 0,
    'cache': 0,
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
    query = 'SELECT Adobe_images.id_local, AgLibraryFile.baseName, AgLibraryRootFolder.absolutePath, AgLibraryRootFolder.name as realtivePath, AgLibraryFolder.pathFromRoot, AgLibraryFile.originalFilename, '
    query += 'AgHarvestedExifMetadata.gpsLatitude, AgHarvestedExifMetadata.gpsLongitude, '
    query += 'AgHarvestedIptcMetadata.locationDataOrigination, AgInternedIptcLocation.value as Location, AgInternedIptcCity.value as City, '
    query += 'AgInternedIptcState.value as State, AgInternedIptcCountry.value as Country, AgInternedIptcIsoCountryCode.value as CountryCode '
    query += 'FROM AgLibraryFile, AgHarvestedExifMetadata, AgLibraryFolder, AgLibraryRootFolder, Adobe_images '
    query += 'LEFT JOIN AgHarvestedIptcMetadata ON Adobe_images.id_local = AgHarvestedIptcMetadata.image '
    query += 'LEFT JOIN AgInternedIptcLocation ON AgHarvestedIptcMetadata.locationRef = AgInternedIptcLocation.id_local '
    query += 'LEFT JOIN AgInternedIptcCity ON AgHarvestedIptcMetadata.cityRef = AgInternedIptcCity.id_local '
    query += 'LEFT JOIN AgInternedIptcState ON AgHarvestedIptcMetadata.stateRef = AgInternedIptcState.id_local '
    query += 'LEFT JOIN AgInternedIptcCountry ON AgHarvestedIptcMetadata.countryRef = AgInternedIptcCountry.id_local '
    query += 'LEFT JOIN AgInternedIptcIsoCountryCode ON AgHarvestedIptcMetadata.isoCountryCodeRef = AgInternedIptcIsoCountryCode.id_local '
    query += 'WHERE Adobe_images.rootFile = AgLibraryFile.id_local AND Adobe_images.id_local = AgHarvestedExifMetadata.image AND AgLibraryFile.folder = AgLibraryFolder.id_local AND AgLibraryFolder.rootFolder = AgLibraryRootFolder.id_local '
    query += 'AND AgLibraryFile.baseName = ?'
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
        print("(!) We could not find a lrcat file in the given lightroom folder or DB connection failed: {}".format(args.lightroom_folder))
        # flag for end
        error = True
    else:
        # set row so we can access each element by the name
        lrdb.row_factory = sqlite3.Row
        # set cursor
        cur = lrdb.cursor()
        # flag that we have Lightroom DB
        use_lightroom = True

# on error exit here
if error:
    sys.exit(1)

# init the XML meta for handling
xmp = XMPMeta()

# loop through the xmp_sources (folder or files) and read in the XMP data for LAT/LONG, other data
for xmp_file_source in args.xmp_sources:
    # if folder, open and loop
    # NOTE: we do check for folders in there, if there are we recourse traverse them
    # also check that folder is not in exclude list
    if os.path.isdir(xmp_file_source) and xmp_file_source.rstrip('/') not in [x.rstrip('/') for x in args.exclude_sources]:
        # open folder and look for any .xmp files and push them into holding array
        # if there are folders, dive into them
        # or glob glob all .xmp files + directory
        for root, dirs, files in os.walk(xmp_file_source):
            for file in sorted(files):
                # 1) but has no .BK. inside
                # 2) file is not in exclude list
                # 3) full folder is not in exclude list
                if file.endswith(".xmp") and ".BK." not in file \
                  and "{}/{}".format(root, file) not in args.exclude_sources \
                  and root.rstrip('/') not in [x.rstrip('/') for x in args.exclude_sources]:
                    if "{}/{}".format(root, file) not in work_files:
                        work_files.append("{}/{}".format(root, file))
                        count['all'] += 1
    else:
        # not already added to list and not in the exclude list either
        if xmp_file_source not in work_files and xmp_file_source not in args.exclude_sources:
            work_files.append(xmp_file_source)
            count['all'] += 1
if args.debug:
    print("### Work Files {}".format(work_files))

# if we have read only we print list format style
if args.read_only:
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
        for format_key in ['filename', 'latitude', 'longitude', 'country', 'state', 'city', 'location', 'path']:
            format_length[format_key] = ceil(format_length[format_key] - ((format_length[format_key] / 100) * reduce_percent))
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
            format_key_order = ['latitude', 'longitude', 'path', 'country', 'state', 'city', 'location', 'filename']
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
                    format_length[format_key] = resize_width if resize_width > resize_width_min else format_length[format_key]
                    # calc new width for check if we can abort
                    current_columns = sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2
                    if (resize == 1 and current_columns >= get_terminal_size().columns) or (resize == -1 and current_columns < get_terminal_size().columns):
                        # check that we are not OVER but one under
                        width_up = get_terminal_size().columns - current_columns - 1
                        if (resize == 1 and width_up < 0) or (resize == -1 and width_up != 0):
                            if format_length['path'] + width_up >= resize_width_min:
                                format_length['path'] += width_up
                        abort = True
                        break
                if abort:
                    break
            if sum(format_length.values()) + ((len(format_length) - 1) * 3) + 2 > get_terminal_size().columns:
                print("[!!!] Screen layout might be skewed. Increase Terminal width")

    # after how many lines do we reprint the header
    header_repeat = 50
    # how many pages will we have
    page_all = ceil(len(work_files) / header_repeat)
    # current page number
    page_no = 1
    # the formatted line for the output
    format_line = " {{filename:<{}}} | {{latitude:>{}}} | {{longitude:>{}}} | {{code:<{}}} | {{country:<{}}} | {{state:<{}}} | {{city:<{}}} | {{location:<{}}} | {{path:<{}}}".format(
        format_length['filename'],
        format_length['latitude'],
        format_length['longitude'],
        format_length['code'],
        format_length['country'],
        format_length['state'],
        format_length['city'],
        format_length['location'],
        format_length['path']
    )
    # header line format:
    # blank line
    # header title
    # seperator line
    header_line = '''{}
{}
{}'''.format(
        '> Page {page_no:,}/{page_all:,}',  # can later be set to something else, eg page numbers
        format_line.format(  # the header title line
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
    # print header
    printHeader(header_line.format(page_no=page_no, page_all=page_all))
    # print no files found if we have no files
    if not work_files:
        print("{:<60}".format('[!!!] No files found'))
# now we just loop through each file and work on them
for xmp_file in work_files:
    if not args.read_only:
        print("---> {}: ".format(xmp_file), end='')
    # ### ACTION FLAGs
    write_file = False
    lightroom_data_ok = True
    # ### LIGHTROOM DB READING
    # read in data from DB if we uave lightroom folder
    if use_lightroom and not args.read_only:
        # get the base file name, we need this for lightroom
        xmp_file_basename = os.path.splitext(os.path.split(xmp_file)[1])[0]
        # for strict check we need to get the full path, and add / as the LR stores the last folder with /
        if args.lightroom_strict:
            xmp_file_path = "{}/{}".format(os.path.split(xmp_file)[0], '/')
        # try to get this file name from the DB
        lr_query_params = [xmp_file_basename]
        if args.lightroom_strict:
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
            print("### LightroomDB: {} / {}".format(tuple(lrdb_row), lrdb_row.keys()))

    # ### XMP FILE READING
    # open file & read all into buffer
    with open(xmp_file, 'r') as fptr:
        strbuffer = fptr.read()
    # read fields from the XMP file and store in hash
    xmp.parse_from_str(strbuffer)
    for xmp_field in xmp_fields:
        data_set[xmp_field] = xmp.get_property(xmp_fields[xmp_field], xmp_field)
        if args.debug:
            print("### => XMP: {}:{} => {}".format(xmp_fields[xmp_field], xmp_field, data_set[xmp_field]))
    if args.read_only:
        # view only if list all or if data is unset
        if not args.unset_only or (args.unset_only and '' in data_set.values()):
            # for read only we print out the data formatted
            # headline check, do we need to print that
            count['read'] = printHeader(header_line.format(page_no=page_no, page_all=page_all), count['read'], header_repeat)
            # the data content
            print(format_line.format(
                filename=shortenPath(xmp_file, format_length['filename'], file_only=True),  # shorten from the left
                latitude=str(convertDMStoLat(data_set['GPSLatitude']))[:format_length['latitude']],  # cut off from the right
                longitude=str(convertDMStoLong(data_set['GPSLongitude']))[:format_length['longitude']],
                code=data_set['CountryCode'][:2].center(4),  # is only 2 chars
                country=shortenString(data_set['Country'], width=format_length['country']),  # shorten from the right
                state=shortenString(data_set['State'], width=format_length['state']),
                city=shortenString(data_set['City'], width=format_length['city']),
                location=shortenString(data_set['Location'], width=format_length['location']),
                path=shortenPath(xmp_file, format_length['path'], path_only=True)
            ))
            count['listed'] += 1
    else:
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
                data_set['GPSLatitude'] = convertLatToDMS(lrdb_row['gpsLatitude'])
            if lrdb_row['gpsLongitude'] and not data_set['GPSLongitude']:
                data_set['GPSLongitude'] = convertLongToDMS(lrdb_row['gpsLongitude'])
            # now check Location, City, etc
            for loc in data_set_loc:
                # overwrite original set (read from XMP) with LR data if original data is missing
                if lrdb_row[loc] and not data_set[loc]:
                    data_set[loc] = lrdb_row[loc]
                    if args.debug:
                        print("### -> LR: {} => {}".format(loc, lrdb_row[loc]))
        # base set done, now check if there is anything unset in the data_set, if yes do a lookup in maps
        # run this through the overwrite checker to get unset if we have a forced overwrite
        has_unset = False
        failed = False
        for loc in data_set_loc:
            if checkOverwrite(data_set[loc], loc, args.field_controls):
                has_unset = True
        if has_unset:
            # check if lat/long is in cache
            cache_key = '{}.#.{}'.format(data_set['GPSLatitude'], data_set['GPSLongitude'])
            if args.debug:
                print("### *** CACHE: {}: {}".format(cache_key, 'NO' if cache_key not in data_cache else 'YES'))
            if cache_key not in data_cache:
                # get location from maps (google or openstreetmap)
                maps_location = reverseGeolocate(latitude=data_set['GPSLatitude'], longitude=data_set['GPSLongitude'], map_type=map_type)
                # cache data with Lat/Long
                data_cache[cache_key] = maps_location
            else:
                # load location from cache
                maps_location = data_cache[cache_key]
                count['cache'] += 1
            # overwrite sets (note options check here)
            if args.debug:
                print("### Map Location ({}): {}".format(map_type, maps_location))
            # must have at least the country set to write anything back
            if maps_location['Country']:
                for loc in data_set_loc:
                    # only write to XMP if overwrite check passes
                    if checkOverwrite(data_set_original[loc], loc, args.field_controls):
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
                print("Lightroom data use: {}, Lightroom data ok: {}".format(use_lightroom, lightroom_data_ok))
            # check if the data_set differs from the original (LR db load)
            # if yes write, else skip
            if use_lightroom and lightroom_data_ok:
                for key in data_set:
                    # if not the same (to original data) and passes overwrite check
                    if data_set[key] != data_set_original[key] and checkOverwrite(data_set_original[key], key, args.field_controls):
                        xmp.set_property(xmp_fields[key], key, data_set[key])
                        write_file = True
                if write_file:
                    count['lightroom'] += 1
        # if we have the write flag set, write data
        if write_file:
            if not args.test:
                # use copyfile to create a backup copy
                if not args.no_xmp_backup:
                    # check if there is another file with .BK. already there, if yes, get the max number and +1 it, if not set to 1
                    # set to 1 for if we have no backups yet
                    bk_file_counter = 1
                    # get PATH from file and look for .BK. data in this folder matching, output is sorted per BK counter key
                    for bk_file in sorted(
                        glob.glob("{path}/{file}*.xmp".format(
                            path=os.path.split(xmp_file)[0],
                            file="{}.BK.".format(os.path.splitext(os.path.split(xmp_file)[1])[0])
                            )
                        ),
                        key=lambda pos: fileSortNumber(pos),
                        reverse=True
                    ):
                        # BK.1, etc -> get the number
                        bk_pos = fileSortNumber(bk_file)
                        if bk_pos > 0:
                            if args.debug:
                                print("#### **** File: {}, Counter: {} -> {}".format(bk_file, bk_pos, bk_pos + 1))
                            # check if found + 1 is bigger than set, if yes, set to new bk counter
                            if bk_pos + 1 > bk_file_counter:
                                bk_file_counter = bk_pos + 1
                                break
                    # copy to new backup file
                    copyfile(xmp_file, "{}.BK.{}{}".format(os.path.splitext(xmp_file)[0], bk_file_counter, os.path.splitext(xmp_file)[1]))
                # write back to riginal file
                with open(xmp_file, 'w') as fptr:
                    fptr.write(xmp.serialize_to_str(omit_packet_wrapper=True))
            else:
                print("[TEST] Would write {} ".format(data_set, xmp_file), end='')
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
if use_lightroom:
    lrdb.close()

# end stats only if we write
print("{}".format('=' * 39))
print("XMP Files found             : {:9,}".format(count['all']))
if args.read_only:
    print("XMP Files listed            : {:9,}".format(count['listed']))
if not args.read_only:
    print("Updated                     : {:9,}".format(count['changed']))
    print("Skipped                     : {:9,}".format(count['skipped']))
    print("New GeoLocation from Map    : {:9,}".format(count['map']))
    print("GeoLocation from Cache      : {:9,}".format(count['cache']))
    print("Failed reverse GeoLocate    : {:9,}".format(count['failed']))
    if use_lightroom:
        print("GeoLocaction from Lightroom : {:9,}".format(count['lightroom']))
        print("No Lightroom data found     : {:9,}".format(count['not_found']))
        print("More than one found in LR   : {:9,}".format(count['many_found']))
    # if we have failed data
    if len(failed_files) > 0:
        print("{}".format('-' * 39))
        print("Files that failed to update:")
        print("{}".format(', '.join(failed_files)))

# __END__
