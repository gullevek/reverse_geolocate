"""
latitude/longitude functions
"""

import re
from math import atan2, cos, radians, sin, sqrt
from typing import TypedDict


class LongLatEntry(TypedDict):
    """For the long/lat return"""

    longitude: float
    latitude: float


def convert_lat_long_to_dms(lat_long: float, is_latitude: bool = False, is_longitude: bool = False) -> str:
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
        # compare the float, int() truncates towards 0, so -0.5 would become 0 (N/E)
        direction = "S" if lat_long < 0 else "N"
    elif is_longitude is True:
        direction = "W" if lat_long < 0 else "E"
    else:
        direction = "(INVALID)"
    return f"{degree},{minutes}{direction}"


def convert_lat_to_dms(lat_long: float) -> str:
    """
    wrapper functions for Long/Lat calls: latitude

    Args:
        lat_long(str): latLong in (-)N.N format

    Returns:
        string: Deg,Min.Sec(NESW) format
    """
    return convert_lat_long_to_dms(lat_long, is_latitude=True)


# wrapper for Long/Lat call: longitute
def convert_long_to_dms(lat_long: float) -> str:
    """
    wrapper for Long/Lat call: longitute

    Args:
        lat_long(str): latLong in (-)N.N format

    Returns:
        string: Deg,Min.Sec(NESW) format
    """
    return convert_lat_long_to_dms(lat_long, is_longitude=True)


def long_lat_reg(longitude: str, latitude: str) -> LongLatEntry:
    """
    converts the XMP/EXIF formatted GPS Long/Lat coordinates
    from the <Degree>,<Minute.Second><NSEW> to the normal float
    number used in google/lr internal

    Args:
        longitude(str): n,n.nNSEW format
        latitude(str): n,n.nNSEW format

    Returns:
        LongLatEntry: dict with converted lat/long
    """
    # dict for loop
    lat_long: LongLatEntry = {
        "longitude": parse_long_lat(longitude),
        "latitude": parse_long_lat(latitude),
    }
    return lat_long


def parse_long_lat(entry: str) -> float:
    """
    Convert to float

    Arguments:
        entry {str} -- _description_

    Raises:
        ValueError: _description_

    Returns:
        float -- _description_
    """
    latlong_re = re.compile(r"^(\d+),(\d+\.\d+)([NESW]{1})$")
    _match = latlong_re.match(entry)
    long_lat = 0
    if _match is not None:
        # convert from Degree, Min.Sec into float format
        long_lat = float(_match.group(1)) + (float(_match.group(2)) / 60)
        # if S or W => inverse to negative
        if _match.group(3) == "S" or _match.group(3) == "W":
            long_lat *= -1
    else:
        raise ValueError(f"Invalid long/lat entry: {entry}")
    return long_lat


def convert_dms_to_lat(lat_long: str) -> float:
    """
    rapper calls for DMS to Lat/Long: latitude

    Args:
        lat_long(str): n,n.nNSEW format

    Returns:
        float: converted latitude in decimal format
    """
    return long_lat_reg("0,0.0N", lat_long)["latitude"]


def convert_dms_to_long(lat_long: str) -> float:
    """
    wrapper calls for DMS to Lat/Long: longitude

    Args:
        lat_long(str): n,n.nNSEW format

    Returns:
        float: converted longitude in decimal format
    """
    return long_lat_reg(lat_long, "0,0.0N")["longitude"]


def get_distance(from_longitude: str, from_latitude: str, to_longitude: str, to_latitude: str) -> float:
    """
    calculates the distance between two coordinates (haversine formula)

    Args:
        from_longitude(str): from longitude in DMS format
        from_latitude(str): from latitude in DMS format
        to_longitude(str): to longitude in DMS format
        to_latitude(str): to latitude in DMS format

    Returns:
        float: distance in meters
    """
    # mean earth radius in meters (IUGG), the haversine formula assumes a sphere
    earth_radius = 6371008.8
    # convert DMS to decimal and then to radians
    from_long_rad = radians(convert_dms_to_long(from_longitude))
    from_lat_rad = radians(convert_dms_to_lat(from_latitude))
    to_long_rad = radians(convert_dms_to_long(to_longitude))
    to_lat_rad = radians(convert_dms_to_lat(to_latitude))
    # distance from - to
    distance_longitude = from_long_rad - to_long_rad
    distance_latitude = from_lat_rad - to_lat_rad
    # main distance calculation
    haversine = sin(distance_latitude / 2) ** 2 + cos(from_lat_rad) * cos(to_lat_rad) * sin(distance_longitude / 2) ** 2
    # clamp, float rounding can push it slightly above 1 (antipodal points) -> sqrt of negative
    haversine = min(1.0, max(0.0, haversine))
    central_angle = 2 * atan2(sqrt(haversine), sqrt(1 - haversine))
    return earth_radius * central_angle


# __END__
