"""
unit tests for reverse_geolocate.utils.geolocate
(only reverse_geolocate_init, everything else calls the network)
"""

import pytest

from reverse_geolocate.utils.geolocate import reverse_geolocate_init

EMPTY_KEYS = ("CountryCode", "Country", "State", "City", "Location")


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (139.74, 35.67),
        (0.0, 0.0),
        (-139.74, -35.67),
        # limits are valid
        (180.0, 90.0),
        (-180.0, -90.0),
        # ints and numeric strings are accepted via float()
        (139, 35),
        ("139.74", "35.67"),
    ],
)
def test_valid(longitude: float, latitude: float) -> None:
    geolocation = reverse_geolocate_init(longitude, latitude)
    assert geolocation == {
        "CountryCode": "",
        "Country": "",
        "State": "",
        "City": "",
        "Location": "",
        "status": "",
        "error_message": "",
    }


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (0.0, 90.1),
        (0.0, -90.1),
        (180.1, 0.0),
        (-180.1, 0.0),
        # swapped long/lat: latitude out of range
        (35.67, 139.74),
        (float("nan"), 0.0),
        (0.0, float("inf")),
        # not numbers
        (None, 0.0),
        ("abc", 0.0),
        (0.0, ""),
    ],
)
def test_invalid(longitude: float, latitude: float) -> None:
    geolocation = reverse_geolocate_init(longitude, latitude)
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == f"Latitude {latitude} or Longitude {longitude} are not valid"
    for key in EMPTY_KEYS:
        assert geolocation[key] == ""


def test_returns_new_dict() -> None:
    first = reverse_geolocate_init(0.0, 0.0)
    first["Country"] = "Japan"
    assert reverse_geolocate_init(0.0, 0.0)["Country"] == ""


# __END__
