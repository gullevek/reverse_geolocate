"""
reverse geolacte functions
"""

import re
import requests
from utils.long_lat import long_lat_reg
from utils.string_helpers import only_latin_chars


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
    if map_type == "google":
        return reverse_geolocate_google(lat_long["longitude"], lat_long["latitude"], args)
    elif map_type == "openstreetmap":
        return reverse_geolocate_open_street_map(lat_long["longitude"], lat_long["latitude"], args)
    else:
        return {"Country": "", "status": "ERROR", "error": "Map type not valid"}


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
        "CountryCode": "",
        "Country": "",
        "State": "",
        "City": "",
        "Location": "",
        # below for error reports
        "status": "",
        "error_message": "",
    }
    # error if long/lat is not valid
    latlong_re = re.compile(r"^\d+\.\d+$")
    if not latlong_re.match(str(longitude)) or not latlong_re.match(str(latitude)):
        geolocation["status"] = "ERROR"
        geolocation["error_message"] = f"Latitude {latitude} or Longitude {longitude} are not valid"
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
    if geolocation["status"] == "ERROR":
        return geolocation
    # query format
    query_format = "jsonv2"
    # language to return (english)
    language = "en-US,en"
    # build query
    base = "https://nominatim.openstreetmap.org/reverse.php?"
    # parameters
    payload = {"format": query_format, "lat": latitude, "lon": longitude, "accept-language": language}
    # if we have an email, add it here
    if args.email:
        payload["email"] = args.email
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
        "CountryCode": ["country_code"],
        "Country": ["country"],
        "State": ["state"],
        "City": ["city", "city_district", "state_district"],
        "Location": ["county", "town", "suburb", "hamlet", "neighbourhood", "road"],
    }
    # if not error
    if "error" not in response.json():
        # get address block
        addr = response.json()["address"]
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
        geolocation["status"] = "ERROR"
        geolocation["error_message"] = response.json()["error"]
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
    if geolocation["status"] == "ERROR":
        return geolocation
    # sensor (why?)
    sensor = "false"
    # language, so we get ascii en back
    language = "en"
    # request to google
    # if a google api key is used, the request has to be via https
    protocol = "https://" if args.google_api_key else "http://"
    base = "maps.googleapis.com/maps/api/geocode/json?"
    # build the base params
    payload = {"latlng": f"{latitude},{longitude}", "language": language, "sensor": sensor}
    # if we have a google api key, add it here
    if args.google_api_key:
        payload["key"] = args.google_api_key
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
        "CountryCode": ["country"],
        "Country": ["country"],
        "State": ["administrative_area_level_1", "administrative_area_level_2"],
        "City": ["locality", "administrative_area_level_3"],
        "Location": ["sublocality_level_1", "sublocality_level_2", "route"],
    }
    # print("Error: {}".format(response.json()['status']))
    if response.json()["status"] == "OK":
        # first entry for type = premise
        for entry in response.json()["results"]:
            for sub_entry in entry:
                if sub_entry == "types" and (
                    "premise" in entry[sub_entry]
                    or "route" in entry[sub_entry]
                    or "street_address" in entry[sub_entry]
                    or "sublocality" in entry[sub_entry]
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
                            for addr in entry["address_components"]:
                                # in types check that index is in there
                                # and the location is not yet set
                                # also check that entry is in LATIN based
                                # NOTE: fallback if all are non LATIN?
                                if index in addr["types"] and not geolocation[loc_index]:
                                    # for country code we need to use short name,
                                    # else we use long name
                                    if loc_index == "CountryCode":
                                        if only_latin_chars(addr["short_name"]):
                                            geolocation[loc_index] = addr["short_name"]
                                        elif not temp_geolocation[loc_index]:
                                            temp_geolocation[loc_index] = addr["short_name"]
                                    else:
                                        if only_latin_chars(addr["long_name"]):
                                            geolocation[loc_index] = addr["long_name"]
                                        elif not temp_geolocation[loc_index]:
                                            temp_geolocation[loc_index] = addr["long_name"]
        # check that all in geoloaction are filled and if not fille from temp_geolocation dictionary
        for loc_index in type_map:
            if not geolocation[loc_index] and temp_geolocation[loc_index]:
                geolocation[loc_index] = temp_geolocation[loc_index]
        # write OK status
        geolocation["status"] = response.json()["status"]
    else:
        geolocation["error_message"] = response.json()["error_message"]
        geolocation["status"] = response.json()["status"]
        print(f"Error in request: {geolocation['status']} {geolocation['error_message']}")
    # return
    return geolocation
