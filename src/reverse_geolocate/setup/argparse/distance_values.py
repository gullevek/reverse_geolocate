"""
distance value reading and check
"""

import argparse
import re
from collections.abc import Sequence
from typing import Any, override


class DistanceValues(argparse.Action):
    """
    check distance values are valid, format: <number>[ ]m|km
    stores the distance as int in meters in the namespace
    """

    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        if not isinstance(values, str):
            raise argparse.ArgumentError(self, f"{values} is not a valid distance, use <number>m or <number>km")
        else:
            _distance = re.match(r"^(\d+)\s?(m|km)$", values)
            if _distance:
                # convert to int in meters
                distance_meters = int(_distance.group(1))
                if _distance.group(2) == "km":
                    distance_meters *= 1000
                setattr(namespace, self.dest, distance_meters)
            else:
                raise argparse.ArgumentError(self, f"{values} is not a valid distance, use <number>m or <number>km")


# __END__
