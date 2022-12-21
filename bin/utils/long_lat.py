"""
latitude/longitude functions
"""

import re
from math import radians, sin, cos, atan2, sqrt

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
