"""
cache for the map lookup results, by exact coordinates and optional by distance (fuzzy)
"""

from dataclasses import dataclass

from reverse_geolocate.utils.long_lat import get_distance


@dataclass(frozen=True)
class CacheHit:
    """a cached location"""

    location: dict[str, str]
    # True if found by distance, not by the exact coordinates
    fuzzy: bool = False


class LocationCache:
    """
    map lookup results by GPS coordinates (DMS strings as in the XMP file)
    with a fuzzy distance, the closest cached location inside the distance is used
    """

    def __init__(self, fuzzy_distance: float | None = None) -> None:
        """
        Args:
            fuzzy_distance (float | None, optional): maximum distance in meters for a fuzzy match,
                None or 0 for exact matches only. Defaults to None.
        """
        self.fuzzy_distance = fuzzy_distance
        # key: "<longitude>#<latitude>", value: location from the map lookup
        self.entries: dict[str, dict[str, str]] = {}

    @staticmethod
    def key(longitude: str, latitude: str) -> str:
        """cache key for coordinates"""
        return f"{longitude}#{latitude}"

    def add(self, longitude: str, latitude: str, location: dict[str, str]) -> None:
        """
        stores a location for coordinates

        Args:
            longitude (str): longitude in DMS format
            latitude (str): latitude in DMS format
            location (dict[str, str]): location from the map lookup
        """
        self.entries[self.key(longitude, latitude)] = location

    def get(self, longitude: str, latitude: str, debug: bool = False) -> CacheHit | None:
        """
        finds a cached location: exact coordinates first, then the closest inside the fuzzy distance
        a fuzzy match is also stored for the coordinates, so the next lookup is an exact match

        Args:
            longitude (str): longitude in DMS format
            latitude (str): latitude in DMS format
            debug (bool, optional): print the cache checks. Defaults to False.

        Returns:
            CacheHit | None: the cached location or None if not found
        """
        cache_key = self.key(longitude, latitude)
        if debug:
            print(f"### *** CACHE: {cache_key}: {'NO' if cache_key not in self.entries else 'YES'}")
        if cache_key in self.entries:
            return CacheHit(self.entries[cache_key])
        # no fuzzy matching (None or 0)
        if self.fuzzy_distance is None or self.fuzzy_distance <= 0:
            return None
        # check the distance to all cached entries, keep the closest inside the fuzzy distance
        shortest_distance = float(self.fuzzy_distance)
        best_match = ""
        for entry_key in self.entries:
            to_longitude, to_latitude = entry_key.split("#")
            distance = get_distance(
                from_longitude=longitude,
                from_latitude=latitude,
                to_longitude=to_longitude,
                to_latitude=to_latitude,
            )
            if debug:
                print(f"### **= FUZZY CACHE: => distance: {distance} (m), shortest: {shortest_distance}")
            if distance <= shortest_distance:
                shortest_distance = distance
                best_match = entry_key
                if debug:
                    print(f"### ***= FUZZY CACHE: YES => Best match: {best_match}")
        if not best_match:
            return None
        # cache this one, because the next one will match this one too
        location = self.entries[best_match]
        self.entries[cache_key] = location
        return CacheHit(location, fuzzy=True)


# __END__
