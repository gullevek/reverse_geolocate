"""
unit tests for reverse_geolocate.utils.location_cache
1 minute of latitude is about 1853m
"""

import pytest

from reverse_geolocate.utils.location_cache import CacheHit, LocationCache

TOKYO_LONG = "139,44.3986917318E"
TOKYO_LAT = "35,40.4617426011N"
NEAR_LAT = "35,40.4725N"  # about 20m from TOKYO_LAT
FAR_LAT = "35,41.5N"  # about 1.9km from TOKYO_LAT
LOCATION = {"Country": "Japan", "City": "Shibuya"}


def test_key() -> None:
    assert LocationCache.key(TOKYO_LONG, TOKYO_LAT) == f"{TOKYO_LONG}#{TOKYO_LAT}"


def test_empty() -> None:
    assert LocationCache().get(TOKYO_LONG, TOKYO_LAT) is None
    assert LocationCache(100).get(TOKYO_LONG, TOKYO_LAT) is None


def test_exact() -> None:
    cache = LocationCache()
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    assert cache.get(TOKYO_LONG, TOKYO_LAT) == CacheHit(LOCATION, fuzzy=False)


def test_exact_before_fuzzy() -> None:
    cache = LocationCache(1000)
    cache.add(TOKYO_LONG, NEAR_LAT, {"City": "Near"})
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    assert cache.get(TOKYO_LONG, TOKYO_LAT) == CacheHit(LOCATION, fuzzy=False)


@pytest.mark.parametrize("fuzzy_distance", [None, 0, 0.0])
def test_no_fuzzy(fuzzy_distance: float | None) -> None:
    cache = LocationCache(fuzzy_distance)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    assert cache.get(TOKYO_LONG, NEAR_LAT) is None


def test_fuzzy_near() -> None:
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    assert cache.get(TOKYO_LONG, NEAR_LAT) == CacheHit(LOCATION, fuzzy=True)


def test_fuzzy_far() -> None:
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    assert cache.get(TOKYO_LONG, FAR_LAT) is None


def test_fuzzy_distance_limit() -> None:
    # about 20m: inside 25m, not inside 15m
    for fuzzy_distance, expected in ((25, True), (15, False)):
        cache = LocationCache(fuzzy_distance)
        cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
        assert (cache.get(TOKYO_LONG, NEAR_LAT) is not None) is expected


def test_fuzzy_closest_match() -> None:
    # 35,40.44N is 74m from 35,40.40N and 37m from 35,40.46N
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, "35,40.40N", {"City": "One"})
    cache.add(TOKYO_LONG, "35,40.46N", {"City": "Two"})
    hit = cache.get(TOKYO_LONG, "35,40.44N")
    assert hit is not None
    assert hit.location == {"City": "Two"}
    # same result with the other insert order
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, "35,40.46N", {"City": "Two"})
    cache.add(TOKYO_LONG, "35,40.40N", {"City": "One"})
    hit = cache.get(TOKYO_LONG, "35,40.44N")
    assert hit is not None
    assert hit.location == {"City": "Two"}


def test_fuzzy_match_is_cached() -> None:
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    cache.get(TOKYO_LONG, NEAR_LAT)
    # the next lookup for the same coordinates is an exact match
    assert cache.entries[LocationCache.key(TOKYO_LONG, NEAR_LAT)] == LOCATION
    assert cache.get(TOKYO_LONG, NEAR_LAT) == CacheHit(LOCATION, fuzzy=False)


def test_fuzzy_miss_not_cached() -> None:
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    cache.get(TOKYO_LONG, FAR_LAT)
    assert list(cache.entries) == [LocationCache.key(TOKYO_LONG, TOKYO_LAT)]


def test_add_replaces() -> None:
    cache = LocationCache()
    cache.add(TOKYO_LONG, TOKYO_LAT, {"City": "Old"})
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    hit = cache.get(TOKYO_LONG, TOKYO_LAT)
    assert hit is not None
    assert hit.location == LOCATION


def test_debug_output(capsys: pytest.CaptureFixture[str]) -> None:
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    cache.get(TOKYO_LONG, NEAR_LAT, debug=True)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"### *** CACHE: {TOKYO_LONG}#{NEAR_LAT}: NO"
    assert lines[1].startswith("### **= FUZZY CACHE: => distance: ")
    assert lines[2] == f"### ***= FUZZY CACHE: YES => Best match: {TOKYO_LONG}#{TOKYO_LAT}"
    cache.get(TOKYO_LONG, NEAR_LAT, debug=True)
    assert capsys.readouterr().out == f"### *** CACHE: {TOKYO_LONG}#{NEAR_LAT}: YES\n"


def test_no_output_without_debug(capsys: pytest.CaptureFixture[str]) -> None:
    cache = LocationCache(100)
    cache.add(TOKYO_LONG, TOKYO_LAT, LOCATION)
    cache.get(TOKYO_LONG, NEAR_LAT)
    assert capsys.readouterr().out == ""


# __END__
