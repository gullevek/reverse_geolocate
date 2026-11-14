"""
integration tests for main() with the config file (~/.config/reverseGeolocate/reverse_geolocate.cfg)
HOME is a temporary folder (see conftest.py), the lookup is a fake that records the arguments
"""

import configparser
from collections.abc import Callable
from pathlib import Path

import pytest
from integration_helpers import FakeLookup, RunResult, write_xmp

Run = Callable[..., RunResult]


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """config file in the temporary HOME (tmp_path / "home", see conftest.py)"""
    return tmp_path / "home" / ".config" / "reverseGeolocate" / "reverse_geolocate.cfg"


def write_config(config_file: Path, **values: str) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[API]", *(f"{key} = {value}" for key, value in values.items())]
    config_file.write_text("\n".join(lines) + "\n", encoding="UTF-8")


def read_config(config_file: Path) -> dict[str, str]:
    config = configparser.ConfigParser()
    config.read(config_file, encoding="UTF-8")
    return dict(config["API"])


def test_google_api_key_from_config(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    write_config(config_file, googleapikey="CONFIG_KEY")
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src")
    assert lookup.calls[0]["map_type"] == "google"
    assert lookup.call_args[0].google_api_key == "CONFIG_KEY"


def test_email_from_config(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    write_config(config_file, openstreetmapemail="config@example.com")
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-o")
    assert lookup.calls[0]["map_type"] == "openstreetmap"
    assert lookup.call_args[0].email == "config@example.com"


def test_command_line_wins_over_config(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    write_config(config_file, googleapikey="CONFIG_KEY")
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-g", "ARG_KEY")
    assert lookup.call_args[0].google_api_key == "ARG_KEY"
    # without -w the config file is not changed
    assert read_config(config_file) == {"googleapikey": "CONFIG_KEY"}


def test_no_config_file(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src")
    assert lookup.call_args[0].google_api_key is None
    assert lookup.call_args[0].email is None
    assert not config_file.exists()


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["-g", "NEW_KEY"], {"googleapikey": "NEW_KEY"}),
        (["-o", "-e", "me@example.com"], {"openstreetmapemail": "me@example.com"}),
    ],
)
def test_write_settings(
    run_main: Run, tmp_path: Path, config_file: Path, argv: list[str], expected: dict[str, str]
) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "-w", *argv)
    assert result.exit_code is None
    assert read_config(config_file) == expected


def test_write_settings_used_in_next_run(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-w", "-g", "SAVED_KEY", "--test")
    write_xmp(tmp_path / "src2" / "b.xmp")
    run_main("-i", tmp_path / "src2")
    assert lookup.call_args[-1].google_api_key == "SAVED_KEY"


def test_write_settings_in_read_only_mode(run_main: Run, tmp_path: Path, config_file: Path) -> None:
    # the settings are written also in read only mode (no lookup)
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-r", "-i", tmp_path / "src", "-w", "-g", "KEY")
    assert read_config(config_file) == {"googleapikey": "KEY"}


def test_config_email_not_read_for_google(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    # only the setting for the used service is read
    write_config(config_file, googleapikey="CONFIG_KEY", openstreetmapemail="config@example.com")
    write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src")
    assert result.exit_code is None
    assert lookup.calls[0]["map_type"] == "google"
    assert lookup.call_args[0].google_api_key == "CONFIG_KEY"
    assert lookup.call_args[0].email is None


def test_config_key_not_read_for_openstreetmap(
    run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup
) -> None:
    write_config(config_file, googleapikey="CONFIG_KEY", openstreetmapemail="config@example.com")
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-o")
    assert lookup.call_args[0].google_api_key is None
    assert lookup.call_args[0].email == "config@example.com"


def test_config_invalid_email_not_used(run_main: Run, tmp_path: Path, config_file: Path, lookup: FakeLookup) -> None:
    # warning, the run continues without an email
    write_config(config_file, openstreetmapemail="foo")
    write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "-o")
    assert result.exit_code is None
    assert f"(!) Not a valid email for OpenStreetMap in the config file {config_file}: foo" in result.lines
    assert lookup.call_args[0].email is None
    assert result.statuses() == {"a.xmp": "UPDATED"}


def test_write_settings_keeps_other_service(run_main: Run, tmp_path: Path, config_file: Path) -> None:
    # -w with a new Google key keeps the stored email (and the other way around)
    write_config(config_file, openstreetmapemail="config@example.com")
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-w", "-g", "NEW_KEY", "--test")
    assert read_config(config_file) == {"openstreetmapemail": "config@example.com", "googleapikey": "NEW_KEY"}
    run_main("-i", tmp_path / "src", "-w", "-o", "-e", "new@example.com", "--test")
    assert read_config(config_file) == {"openstreetmapemail": "new@example.com", "googleapikey": "NEW_KEY"}


def test_config_debug_output(run_main: Run, tmp_path: Path, config_file: Path) -> None:
    write_config(config_file, googleapikey="CONFIG_KEY")
    write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "--debug")
    assert "### OVERRIDE API: G: CONFIG_KEY, O: None" in result.out


# __END__
