"""
unit tests for reverse_geolocate.utils.long_lat
"""

from collections.abc import Callable
from math import pi

import pytest

from reverse_geolocate.utils.long_lat import (
    convert_dms_to_lat,
    convert_dms_to_long,
    convert_lat_long_to_dms,
    convert_lat_to_dms,
    convert_long_to_dms,
    get_distance,
    long_lat_reg,
    parse_long_lat,
)

# mean earth radius used in get_distance
EARTH_RADIUS = 6371008.8
# sample coordinates from the data/ XMP files (Tokyo)
TOKYO_LAT = "35,40.4617426011N"
TOKYO_LONG = "139,44.3986917318E"


# MARK: parse_long_lat
@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (TOKYO_LAT, 35 + 40.4617426011 / 60),
        (TOKYO_LONG, 139 + 44.3986917318 / 60),
        ("35,30.0S", -35.5),
        ("139,30.0W", -139.5),
        ("0,0.0N", 0.0),
        ("0,30.0S", -0.5),
        ("180,0.0E", 180.0),
    ],
)
def test_parse_long_lat(entry: str, expected: float) -> None:
    assert parse_long_lat(entry) == pytest.approx(expected)


@pytest.mark.parametrize(
    "entry",
    [
        "",
        "50,30N",  # minutes without decimal point
        "35.67",  # plain decimal
        "35,40.46n",  # lower case direction
        "35,40,27N",  # deg,min,sec
        " 35,40.46N",  # leading space
        "35,40.46N ",  # trailing space
        "35,40.46X",  # invalid direction
        "-35,40.46N",  # sign is not allowed
        "35,40.46NE",  # two directions
    ],
)
def test_parse_long_lat_invalid(entry: str) -> None:
    with pytest.raises(ValueError, match="Invalid long/lat entry"):
        parse_long_lat(entry)


# MARK: long_lat_reg
def test_long_lat_reg() -> None:
    result = long_lat_reg(longitude="139,30.0W", latitude="35,30.0S")
    assert result == {"longitude": pytest.approx(-139.5), "latitude": pytest.approx(-35.5)}


@pytest.mark.parametrize(("longitude", "latitude"), [("", TOKYO_LAT), (TOKYO_LONG, ""), ("", "")])
def test_long_lat_reg_invalid(longitude: str, latitude: str) -> None:
    with pytest.raises(ValueError):
        long_lat_reg(longitude=longitude, latitude=latitude)


# MARK: convert_dms_to_lat / convert_dms_to_long
def test_convert_dms_to_lat() -> None:
    assert convert_dms_to_lat("35,30.0N") == pytest.approx(35.5)
    assert convert_dms_to_lat("35,30.0S") == pytest.approx(-35.5)


def test_convert_dms_to_long() -> None:
    assert convert_dms_to_long("139,30.0E") == pytest.approx(139.5)
    assert convert_dms_to_long("139,30.0W") == pytest.approx(-139.5)


@pytest.mark.parametrize("function", [convert_dms_to_lat, convert_dms_to_long])
def test_convert_dms_invalid(function: Callable[[str], float]) -> None:
    with pytest.raises(ValueError):
        function("")


# MARK: convert_lat_long_to_dms
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (35.5, "35,30.0N"),
        (-35.5, "35,30.0S"),
        (0.0, "0,0.0N"),
        # between -1 and 0 (int() would truncate to 0)
        (-0.5, "0,30.0S"),
        (0.5, "0,30.0N"),
        (90.0, "90,0.0N"),
        (-90.0, "90,0.0S"),
    ],
)
def test_convert_lat_to_dms(value: float, expected: str) -> None:
    assert convert_lat_to_dms(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (139.5, "139,30.0E"),
        (-139.5, "139,30.0W"),
        (0.0, "0,0.0E"),
        (-0.5, "0,30.0W"),
        (0.5, "0,30.0E"),
        (180.0, "180,0.0E"),
        (-180.0, "180,0.0W"),
    ],
)
def test_convert_long_to_dms(value: float, expected: str) -> None:
    assert convert_long_to_dms(value) == expected


def test_convert_lat_long_to_dms_no_flag() -> None:
    assert convert_lat_long_to_dms(35.5) == "35,30.0(INVALID)"


def test_convert_lat_long_to_dms_latitude_wins() -> None:
    # latitude flag is checked first
    assert convert_lat_long_to_dms(-35.5, is_latitude=True, is_longitude=True) == "35,30.0S"


def test_convert_lat_long_to_dms_minutes_rounded() -> None:
    # minutes are rounded to 10 decimals
    degree, rest = convert_lat_to_dms(35.674362376685).split(",")
    assert degree == "35"
    assert len(rest.rstrip("NS").split(".")[1]) <= 10


@pytest.mark.parametrize("value", [35.674362376685, -35.674362376685, -0.25, 0.0001, 89.999])
def test_lat_round_trip(value: float) -> None:
    assert convert_dms_to_lat(convert_lat_to_dms(value)) == pytest.approx(value)


@pytest.mark.parametrize("value", [139.739978195530, -139.739978195530, -0.25, 0.0001, 179.999])
def test_long_round_trip(value: float) -> None:
    assert convert_dms_to_long(convert_long_to_dms(value)) == pytest.approx(value)


@pytest.mark.parametrize("dms", [TOKYO_LAT, "35,30.0S", "0,30.0S"])
def test_dms_round_trip_lat(dms: str) -> None:
    assert convert_lat_to_dms(convert_dms_to_lat(dms)) == dms


# MARK: get_distance
def test_get_distance_same_point() -> None:
    assert get_distance(TOKYO_LONG, TOKYO_LAT, TOKYO_LONG, TOKYO_LAT) == pytest.approx(0.0, abs=1e-6)


def test_get_distance_one_minute_latitude() -> None:
    # one minute of latitude (1/60 degree) on the sphere
    expected = EARTH_RADIUS * pi / 180 / 60
    assert get_distance("0,0.0E", "0,0.0N", "0,0.0E", "0,1.0N") == pytest.approx(expected)
    assert expected == pytest.approx(1853.25, abs=0.01)


def test_get_distance_one_minute_longitude_at_equator() -> None:
    expected = EARTH_RADIUS * pi / 180 / 60
    assert get_distance("0,0.0E", "0,0.0N", "0,1.0E", "0,0.0N") == pytest.approx(expected)


def test_get_distance_symmetric() -> None:
    there = get_distance(TOKYO_LONG, TOKYO_LAT, "135,30.0E", "34,41.0N")
    back = get_distance("135,30.0E", "34,41.0N", TOKYO_LONG, TOKYO_LAT)
    assert there == pytest.approx(back)


def test_get_distance_tokyo_osaka() -> None:
    # roughly 400km
    distance = get_distance(TOKYO_LONG, TOKYO_LAT, "135,30.0E", "34,41.0N")
    assert 390_000 < distance < 410_000


def test_get_distance_antipodal() -> None:
    # half the circumference, must not raise (haversine clamp)
    distance = get_distance("0,0.0E", "0,0.0N", "180,0.0E", "0,0.0N")
    assert distance == pytest.approx(EARTH_RADIUS * pi)


def test_get_distance_across_date_line() -> None:
    # 179°59'E to 179°59'W are 2 minutes apart, not 359°58'
    distance = get_distance("179,59.0E", "0,0.0N", "179,59.0W", "0,0.0N")
    assert distance == pytest.approx(EARTH_RADIUS * pi / 180 / 60 * 2)


def test_get_distance_across_equator() -> None:
    distance = get_distance("0,0.0E", "0,1.0S", "0,0.0E", "0,1.0N")
    assert distance == pytest.approx(EARTH_RADIUS * pi / 180 / 60 * 2)


def test_get_distance_invalid() -> None:
    with pytest.raises(ValueError):
        get_distance("", "", TOKYO_LONG, TOKYO_LAT)


# __END__
