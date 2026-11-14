"""
unit tests for reverse_geolocate.utils.geolocate
the network is never used, requests.get is replaced by a fake that records the calls
"""

from argparse import Namespace
from typing import Any, override

import pytest
import requests

from reverse_geolocate.utils import geolocate
from reverse_geolocate.utils.geolocate import (
    reverse_geolocate,
    reverse_geolocate_google,
    reverse_geolocate_open_street_map,
)

GOOGLE_URL = "https://geocode.googleapis.com/v4/geocode/location"
OSM_URL = "https://nominatim.openstreetmap.org/reverse.php?"
LOCATION_KEYS = ("CountryCode", "Country", "State", "City", "Location")


# MARK: fakes
class FakeResponse:
    """minimal stand in for requests.Response"""

    def __init__(
        self,
        json_data: Any = None,
        ok: bool = True,
        text: str = "",
        url: str = "https://fake.url/",
        json_error: Exception | None = None,
    ) -> None:
        self.json_data = json_data
        self.ok = ok
        self.text = text
        self.url = url
        self.json_error = json_error

    def json(self) -> Any:
        if self.json_error is not None:
            raise self.json_error
        return self.json_data

    @override
    def __repr__(self) -> str:
        return "<FakeResponse>"


class FakeGet:
    """replaces requests.get, records every call and returns the response or raises the error"""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response if response is not None else FakeResponse({})
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def fake_get(monkeypatch: pytest.MonkeyPatch) -> FakeGet:
    """default fake, tests replace the response or error as needed"""
    fake = FakeGet()
    monkeypatch.setattr(geolocate.requests, "get", fake)
    return fake


def make_args(
    debug: bool = False,
    verbose: int = 0,
    email: str | None = None,
    google_api_key: str | None = None,
) -> Namespace:
    return Namespace(debug=debug, verbose=verbose, email=email, google_api_key=google_api_key)


# MARK: Google response builders
def component(long_text: str, short_text: str, *types: str) -> dict[str, Any]:
    return {"longText": long_text, "shortText": short_text, "types": list(types)}


def result(types: list[str], *components: dict[str, Any]) -> dict[str, Any]:
    return {"types": types, "addressComponents": list(components)}


TOKYO_COMPONENTS = (
    component("Omotesando", "Omotesando", "route"),
    component("Jingumae", "Jingumae", "sublocality_level_1", "sublocality", "political"),
    component("Shibuya", "Shibuya", "locality", "political"),
    component("Tokyo", "Tokyo", "administrative_area_level_1", "political"),
    component("Japan", "JP", "country", "political"),
)


def google_ok(*results: dict[str, Any]) -> FakeResponse:
    return FakeResponse({"results": list(results)}, url=f"{GOOGLE_URL}/35.5,139.5?languageCode=en")


# MARK: reverse_geolocate (dispatch)
@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, float, float, Namespace]]:
    """replace both lookup functions, record which one was called with what"""
    calls: list[tuple[str, float, float, Namespace]] = []

    def fake_google(longitude: float, latitude: float, args: Namespace) -> dict[str, str]:
        calls.append(("google", longitude, latitude, args))
        return {"Country": "from google"}

    def fake_osm(longitude: float, latitude: float, args: Namespace) -> dict[str, str]:
        calls.append(("openstreetmap", longitude, latitude, args))
        return {"Country": "from openstreetmap"}

    monkeypatch.setattr(geolocate, "reverse_geolocate_google", fake_google)
    monkeypatch.setattr(geolocate, "reverse_geolocate_open_street_map", fake_osm)
    return calls


@pytest.mark.parametrize("map_type", ["google", "openstreetmap"])
def test_dispatch(lookups: list[tuple[str, float, float, Namespace]], map_type: str) -> None:
    args = make_args()
    result_data = reverse_geolocate(longitude="139,30.0W", latitude="35,30.0S", map_type=map_type, args=args)
    assert result_data == {"Country": f"from {map_type}"}
    # DMS strings are converted to decimal, long/lat order is kept
    assert lookups == [(map_type, -139.5, -35.5, args)]


@pytest.mark.parametrize("map_type", ["", "Google", "bing"])
def test_dispatch_invalid_map_type(lookups: list[tuple[str, float, float, Namespace]], map_type: str) -> None:
    result_data = reverse_geolocate(longitude="139,30.0E", latitude="35,30.0N", map_type=map_type, args=make_args())
    assert result_data == {"Country": "", "status": "ERROR", "error": "Map type not valid"}
    assert lookups == []


@pytest.mark.parametrize(("longitude", "latitude"), [("", "35,30.0N"), ("139,30.0E", ""), ("139.5", "35.5")])
def test_dispatch_invalid_coordinates(
    lookups: list[tuple[str, float, float, Namespace]], longitude: str, latitude: str
) -> None:
    with pytest.raises(ValueError):
        reverse_geolocate(longitude=longitude, latitude=latitude, map_type="google", args=make_args())
    assert lookups == []


@pytest.mark.parametrize("map_type", ["google", "openstreetmap"])
def test_dispatch_out_of_range_no_request(fake_get: FakeGet, map_type: str) -> None:
    # valid DMS format, but latitude > 90: no request is made
    result_data = reverse_geolocate(longitude="139,30.0E", latitude="95,0.0N", map_type=map_type, args=make_args())
    assert result_data["status"] == "ERROR"
    assert fake_get.calls == []


# MARK: OpenStreetMap
def osm_response(address: dict[str, str]) -> FakeResponse:
    return FakeResponse({"place_id": 1, "address": address})


def test_osm_success(fake_get: FakeGet) -> None:
    fake_get.response = osm_response(
        {
            "road": "Omotesando",
            "suburb": "Jingumae",
            "city": "Shibuya",
            "state": "Tokyo",
            "country": "Japan",
            "country_code": "jp",
        }
    )
    geolocation = reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    assert geolocation == {
        # OpenStreetMap returns the country code in lower case
        "CountryCode": "jp",
        "Country": "Japan",
        "State": "Tokyo",
        "City": "Shibuya",
        "Location": "Jingumae",
        # NOTE: success does not set a status (Google sets "OK")
        "status": "",
        "error_message": "",
    }


def test_osm_request(fake_get: FakeGet) -> None:
    fake_get.response = osm_response({})
    reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    assert fake_get.calls == [
        {
            "url": OSM_URL,
            "params": {"format": "jsonv2", "lat": 35.5, "lon": 139.5, "accept-language": "en-US,en"},
            "timeout": 60,
        }
    ]


def test_osm_request_with_email(fake_get: FakeGet) -> None:
    fake_get.response = osm_response({})
    reverse_geolocate_open_street_map(139.5, 35.5, make_args(email="me@example.com"))
    assert fake_get.calls[0]["params"]["email"] == "me@example.com"


@pytest.mark.parametrize(
    ("address", "expected_city"),
    [
        ({"city": "A", "city_district": "B", "state_district": "C"}, "A"),
        ({"city_district": "B", "state_district": "C"}, "B"),
        ({"state_district": "C"}, "C"),
        ({}, ""),
    ],
)
def test_osm_city_fallback(fake_get: FakeGet, address: dict[str, str], expected_city: str) -> None:
    fake_get.response = osm_response(address)
    assert reverse_geolocate_open_street_map(139.5, 35.5, make_args())["City"] == expected_city


@pytest.mark.parametrize(
    ("address", "expected_location"),
    [
        (
            {
                "road": "6",
                "neighbourhood": "5",
                "hamlet": "4",
                "suburb": "3",
                "town": "2",
                "county": "1",
            },
            "1",
        ),
        ({"road": "6", "neighbourhood": "5", "hamlet": "4", "suburb": "3", "town": "2"}, "2"),
        ({"road": "6", "neighbourhood": "5", "hamlet": "4", "suburb": "3"}, "3"),
        ({"road": "6", "neighbourhood": "5", "hamlet": "4"}, "4"),
        ({"road": "6", "neighbourhood": "5"}, "5"),
        ({"road": "6"}, "6"),
        ({"house_number": "1"}, ""),
    ],
)
def test_osm_location_priority(fake_get: FakeGet, address: dict[str, str], expected_location: str) -> None:
    fake_get.response = osm_response(address)
    assert reverse_geolocate_open_street_map(139.5, 35.5, make_args())["Location"] == expected_location


def test_osm_empty_address(fake_get: FakeGet) -> None:
    fake_get.response = osm_response({})
    geolocation = reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    for key in LOCATION_KEYS:
        assert geolocation[key] == ""
    assert geolocation["status"] == ""


def test_osm_error_response(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = FakeResponse({"error": "Unable to geocode"})
    geolocation = reverse_geolocate_open_street_map(0.0, 0.0, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == "Unable to geocode"
    assert geolocation["Country"] == ""
    assert "Error in request: Unable to geocode" in capsys.readouterr().out


@pytest.mark.parametrize(("longitude", "latitude"), [(181.0, 0.0), (0.0, -91.0)])
def test_osm_invalid_coordinates_no_request(fake_get: FakeGet, longitude: float, latitude: float) -> None:
    geolocation = reverse_geolocate_open_street_map(longitude, latitude, make_args())
    assert geolocation["status"] == "ERROR"
    assert fake_get.calls == []


def test_osm_no_output_without_debug(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = osm_response({"country": "Japan"})
    reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    assert capsys.readouterr().out == ""


def test_osm_debug_output(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = osm_response({"country": "Japan"})
    reverse_geolocate_open_street_map(139.5, 35.5, make_args(debug=True, verbose=1))
    out = capsys.readouterr().out
    assert "OpenStreetMap search for Lat: 35.5, Long: 139.5" in out
    assert "OpenStreetMap response" not in out


def test_osm_debug_verbose_output(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = osm_response({"country": "Japan"})
    reverse_geolocate_open_street_map(139.5, 35.5, make_args(debug=True, verbose=2))
    assert "OpenStreetMap response: <FakeResponse> => JSON: {" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("no network"),
        requests.exceptions.Timeout("timed out"),
        requests.exceptions.RequestException("generic"),
    ],
)
def test_osm_network_error(fake_get: FakeGet, capsys: pytest.CaptureFixture[str], error: Exception) -> None:
    fake_get.error = error
    geolocation = reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == str(error)
    for key in LOCATION_KEYS:
        assert geolocation[key] == ""
    assert f"Error in request: ERROR {error}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [ValueError("invalid json"), requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)],
)
def test_osm_invalid_json(fake_get: FakeGet, error: Exception) -> None:
    fake_get.response = FakeResponse(json_error=error)
    geolocation = reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == str(error)


def test_osm_network_error_no_debug_output(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    # on error the function returns before the debug output
    fake_get.error = requests.exceptions.ConnectionError("no network")
    reverse_geolocate_open_street_map(139.5, 35.5, make_args(debug=True, verbose=2))
    assert "OpenStreetMap search" not in capsys.readouterr().out


def test_osm_other_errors_not_caught(fake_get: FakeGet) -> None:
    # only request and JSON errors are handled
    fake_get.error = RuntimeError("unexpected")
    with pytest.raises(RuntimeError):
        reverse_geolocate_open_street_map(139.5, 35.5, make_args())


@pytest.mark.parametrize("json_data", [{"place_id": 1}, {"address": None}, {}])
def test_osm_response_without_address(fake_get: FakeGet, json_data: dict[str, Any]) -> None:
    fake_get.response = FakeResponse(json_data)
    geolocation = reverse_geolocate_open_street_map(139.5, 35.5, make_args())
    for key in LOCATION_KEYS:
        assert geolocation[key] == ""
    assert geolocation["status"] == ""


def test_osm_json_read_once(fake_get: FakeGet) -> None:
    # the response body is parsed only once
    class CountingResponse(FakeResponse):
        count = 0

        @override
        def json(self) -> Any:
            CountingResponse.count += 1
            return super().json()

    fake_get.response = CountingResponse({"address": {"country": "Japan"}})
    reverse_geolocate_open_street_map(139.5, 35.5, make_args(debug=True, verbose=2))
    assert CountingResponse.count == 1


# MARK: Google
def test_google_success(fake_get: FakeGet) -> None:
    fake_get.response = google_ok(result(["street_address"], *TOKYO_COMPONENTS))
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation == {
        "CountryCode": "JP",
        "Country": "Japan",
        "State": "Tokyo",
        "City": "Shibuya",
        # sublocality_level_1 before route
        "Location": "Jingumae",
        "status": "OK",
        "error_message": "",
    }


def test_google_request(fake_get: FakeGet) -> None:
    fake_get.response = google_ok()
    reverse_geolocate_google(-139.5, -35.5, make_args())
    assert fake_get.calls == [
        {
            # lat,long order in the path
            "url": f"{GOOGLE_URL}/-35.5,-139.5",
            "params": {"languageCode": "en"},
            "headers": {},
            "timeout": 60,
        }
    ]


def test_google_api_key_only_in_header(fake_get: FakeGet) -> None:
    fake_get.response = google_ok()
    reverse_geolocate_google(139.5, 35.5, make_args(google_api_key="SECRET_KEY"))
    call = fake_get.calls[0]
    assert call["headers"] == {"X-Goog-Api-Key": "SECRET_KEY"}
    assert "SECRET_KEY" not in call["url"]
    assert "SECRET_KEY" not in str(call["params"])


@pytest.mark.parametrize("result_type", ["premise", "route", "street_address", "sublocality"])
def test_google_used_result_types(fake_get: FakeGet, result_type: str) -> None:
    fake_get.response = google_ok(result([result_type, "political"], *TOKYO_COMPONENTS))
    assert reverse_geolocate_google(139.5, 35.5, make_args())["Country"] == "Japan"


@pytest.mark.parametrize("result_type", ["plus_code", "locality", "country", "postal_code"])
def test_google_ignored_result_types(fake_get: FakeGet, result_type: str) -> None:
    fake_get.response = google_ok(result([result_type], *TOKYO_COMPONENTS))
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    for key in LOCATION_KEYS:
        assert geolocation[key] == ""
    # results were returned, so the status is OK even if nothing could be used
    assert geolocation["status"] == "OK"


def test_google_first_matching_result_wins(fake_get: FakeGet) -> None:
    fake_get.response = google_ok(
        result(["plus_code"], component("Ignored", "IG", "country")),
        result(["premise"], component("Japan", "JP", "country")),
        result(["route"], component("Other", "OT", "country"), component("Shibuya", "Shibuya", "locality")),
    )
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["Country"] == "Japan"
    assert geolocation["CountryCode"] == "JP"
    # empty fields are still filled from later results
    assert geolocation["City"] == "Shibuya"


@pytest.mark.parametrize(
    ("components", "key", "expected"),
    [
        # State: level 1 before level 2
        (
            [
                component("L2", "L2", "administrative_area_level_2"),
                component("L1", "L1", "administrative_area_level_1"),
            ],
            "State",
            "L1",
        ),
        ([component("L2", "L2", "administrative_area_level_2")], "State", "L2"),
        # City: locality before administrative_area_level_3
        (
            [component("Admin3", "A3", "administrative_area_level_3"), component("Locality", "LO", "locality")],
            "City",
            "Locality",
        ),
        ([component("Admin3", "A3", "administrative_area_level_3")], "City", "Admin3"),
        # Location: sublocality_level_1, then _2, then route
        (
            [
                component("Route", "R", "route"),
                component("Sub2", "S2", "sublocality_level_2"),
                component("Sub1", "S1", "sublocality_level_1"),
            ],
            "Location",
            "Sub1",
        ),
        ([component("Route", "R", "route"), component("Sub2", "S2", "sublocality_level_2")], "Location", "Sub2"),
        ([component("Route", "R", "route")], "Location", "Route"),
    ],
)
def test_google_priority(fake_get: FakeGet, components: list[dict[str, Any]], key: str, expected: str) -> None:
    fake_get.response = google_ok(result(["premise"], *components))
    assert reverse_geolocate_google(139.5, 35.5, make_args())[key] == expected


def test_google_country_code_short_country_long(fake_get: FakeGet) -> None:
    fake_get.response = google_ok(result(["premise"], component("Austria", "AT", "country")))
    geolocation = reverse_geolocate_google(16.3, 48.2, make_args())
    assert geolocation["CountryCode"] == "AT"
    assert geolocation["Country"] == "Austria"


def test_google_non_latin_only_as_fallback(fake_get: FakeGet) -> None:
    fake_get.response = google_ok(
        result(
            ["premise"],
            # higher priority, but not latin
            component("東京都", "東京都", "administrative_area_level_1"),
            # lower priority, latin -> used
            component("Tokyo", "Tokyo", "administrative_area_level_2"),
            # only non latin -> used as fallback
            component("渋谷区", "渋谷区", "locality"),
            component("日本", "日本", "country"),
        )
    )
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["State"] == "Tokyo"
    assert geolocation["City"] == "渋谷区"
    assert geolocation["Country"] == "日本"
    assert geolocation["CountryCode"] == "日本"


def test_google_first_non_latin_fallback_wins(fake_get: FakeGet) -> None:
    fake_get.response = google_ok(
        result(
            ["premise"],
            component("渋谷区", "渋谷区", "locality"),
            component("東京", "東京", "administrative_area_level_3"),
        )
    )
    assert reverse_geolocate_google(139.5, 35.5, make_args())["City"] == "渋谷区"


def test_google_latin_with_accents(fake_get: FakeGet) -> None:
    fake_get.response = google_ok(result(["premise"], component("Österreich", "AT", "country")))
    assert reverse_geolocate_google(16.3, 48.2, make_args())["Country"] == "Österreich"


def test_google_component_without_list(fake_get: FakeGet) -> None:
    # a matching result without addressComponents gives empty fields
    fake_get.response = google_ok({"types": ["premise"]})
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["Country"] == ""
    assert geolocation["status"] == "OK"


@pytest.mark.parametrize("json_data", [{"results": []}, {}])
def test_google_zero_results(fake_get: FakeGet, json_data: dict[str, Any]) -> None:
    fake_get.response = FakeResponse(json_data)
    geolocation = reverse_geolocate_google(0.0, 0.0, make_args())
    assert geolocation["status"] == "ZERO_RESULTS"
    for key in LOCATION_KEYS:
        assert geolocation[key] == ""


def test_google_error_response(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = FakeResponse(
        {"error": {"code": 403, "message": "API key not valid", "status": "PERMISSION_DENIED"}},
        ok=False,
        text="raw error text",
    )
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["status"] == "PERMISSION_DENIED"
    assert geolocation["error_message"] == "API key not valid"
    assert geolocation["Country"] == ""
    assert "Error in request: PERMISSION_DENIED API key not valid" in capsys.readouterr().out


def test_google_error_in_ok_response(fake_get: FakeGet) -> None:
    # "error" in the body is an error even with a 2xx status
    fake_get.response = FakeResponse({"error": {"message": "broken", "status": "INTERNAL"}, "results": []})
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["status"] == "INTERNAL"
    assert geolocation["error_message"] == "broken"


def test_google_error_without_error_block(fake_get: FakeGet) -> None:
    fake_get.response = FakeResponse({}, ok=False, text="502 Bad Gateway")
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == "502 Bad Gateway"


def test_google_error_block_partial(fake_get: FakeGet) -> None:
    fake_get.response = FakeResponse({"error": {"code": 500}}, ok=False, text="server error")
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == "server error"


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("no network"),
        requests.exceptions.Timeout("timed out"),
        requests.exceptions.RequestException("generic"),
    ],
)
def test_google_network_error(fake_get: FakeGet, capsys: pytest.CaptureFixture[str], error: Exception) -> None:
    fake_get.error = error
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == str(error)
    assert f"Error in request: ERROR {error}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [ValueError("invalid json"), requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)],
)
def test_google_invalid_json(fake_get: FakeGet, error: Exception) -> None:
    fake_get.response = FakeResponse(json_error=error, ok=True)
    geolocation = reverse_geolocate_google(139.5, 35.5, make_args())
    assert geolocation["status"] == "ERROR"
    assert geolocation["error_message"] == str(error)


def test_google_other_errors_not_caught(fake_get: FakeGet) -> None:
    # only request and JSON errors are handled
    fake_get.error = RuntimeError("unexpected")
    with pytest.raises(RuntimeError):
        reverse_geolocate_google(139.5, 35.5, make_args())


@pytest.mark.parametrize(("longitude", "latitude"), [(181.0, 0.0), (0.0, -91.0)])
def test_google_invalid_coordinates_no_request(fake_get: FakeGet, longitude: float, latitude: float) -> None:
    geolocation = reverse_geolocate_google(longitude, latitude, make_args())
    assert geolocation["status"] == "ERROR"
    assert fake_get.calls == []


def test_google_no_output_without_debug(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = google_ok(result(["premise"], *TOKYO_COMPONENTS))
    reverse_geolocate_google(139.5, 35.5, make_args())
    assert capsys.readouterr().out == ""


def test_google_debug_output(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = google_ok()
    reverse_geolocate_google(139.5, 35.5, make_args(debug=True, verbose=1))
    out = capsys.readouterr().out
    assert f"Google search for Lat: 35.5, Long: 139.5 with {GOOGLE_URL}/35.5,139.5?languageCode=en" in out
    assert "Google response" not in out


def test_google_debug_verbose_output(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = google_ok()
    reverse_geolocate_google(139.5, 35.5, make_args(debug=True, verbose=2))
    assert "Google response: <FakeResponse> => JSON: {'results': []}" in capsys.readouterr().out


def test_google_debug_does_not_print_api_key(fake_get: FakeGet, capsys: pytest.CaptureFixture[str]) -> None:
    fake_get.response = google_ok()
    reverse_geolocate_google(139.5, 35.5, make_args(debug=True, verbose=2, google_api_key="SECRET_KEY"))
    assert "SECRET_KEY" not in capsys.readouterr().out


# __END__
