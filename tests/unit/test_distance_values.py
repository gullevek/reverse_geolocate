"""
unit tests for reverse_geolocate.setup.argparse.distance_values
"""

import argparse

import pytest

from reverse_geolocate.setup.argparse.distance_values import DistanceValues


def make_action() -> DistanceValues:
    return DistanceValues(option_strings=["-d"], dest="fuzzy_distance")


def make_parser() -> argparse.ArgumentParser:
    # same setup as in ArgumentSetup
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--fuzzy-cache",
        type=str.lower,
        action=DistanceValues,
        nargs="?",
        const="10m",
        dest="fuzzy_distance",
    )
    return parser


# MARK: direct call
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10m", 10),
        ("0m", 0),
        ("10 m", 10),
        ("1km", 1000),
        ("5km", 5000),
        ("5 km", 5000),
        ("123456m", 123456),
    ],
)
def test_valid_distance(value: str, expected: int) -> None:
    namespace = argparse.Namespace()
    make_action()(argparse.ArgumentParser(), namespace, value)
    assert namespace.fuzzy_distance == expected
    assert isinstance(namespace.fuzzy_distance, int)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "10",
        "m",
        "km",
        "1.5km",
        "-10m",
        "10mi",
        "10 km ",
        " 10m",
        "10  m",
        # upper case is only valid through the parser (type=str.lower)
        "10M",
        "10KM",
    ],
)
def test_invalid_distance(value: str) -> None:
    namespace = argparse.Namespace()
    with pytest.raises(argparse.ArgumentError, match="is not a valid distance"):
        make_action()(argparse.ArgumentParser(), namespace, value)
    assert not hasattr(namespace, "fuzzy_distance")


@pytest.mark.parametrize("value", [None, ["10m"], []])
def test_non_string_value(value: list[str] | None) -> None:
    with pytest.raises(argparse.ArgumentError):
        make_action()(argparse.ArgumentParser(), argparse.Namespace(), value)


# MARK: through the argument parser
def test_parser_not_set() -> None:
    assert make_parser().parse_args([]).fuzzy_distance is None


def test_parser_default_const() -> None:
    assert make_parser().parse_args(["-d"]).fuzzy_distance == 10


@pytest.mark.parametrize(("value", "expected"), [("25m", 25), ("2KM", 2000), ("3Km", 3000), ("40M", 40)])
def test_parser_value(value: str, expected: int) -> None:
    assert make_parser().parse_args(["--fuzzy-cache", value]).fuzzy_distance == expected


def test_parser_invalid_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        make_parser().parse_args(["-d", "abc"])
    assert "is not a valid distance" in capsys.readouterr().err


# __END__
