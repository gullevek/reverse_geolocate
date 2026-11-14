"""
unit tests for reverse_geolocate.setup.configurate.read_config
HOME is pointed to a temporary folder, so the real user config is never read or written
"""

import configparser
import os
from argparse import Namespace
from pathlib import Path

import pytest

from reverse_geolocate.setup.configurate import read_config


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """temporary home folder, read_config uses ~/.config/reverseGeolocate/"""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Windows uses USERPROFILE for "~"
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def config_file(home: Path) -> Path:
    return home / ".config" / "reverseGeolocate" / "reverse_geolocate.cfg"


def write_config(home: Path, content: str) -> Path:
    file = config_file(home)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="UTF-8")
    return file


def read_back(home: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(config_file(home), encoding="UTF-8")
    return config


def make_args(
    google_api_key: str | None = None,
    email: str | None = None,
    config_write: bool = False,
    debug: bool = False,
    use_openstreetmap: bool = False,
) -> Namespace:
    return Namespace(
        google_api_key=google_api_key,
        email=email,
        config_write=config_write,
        debug=debug,
        use_openstreetmap=use_openstreetmap,
    )


# MARK: read
def test_no_config_file(home: Path) -> None:
    args = read_config(make_args())
    assert args.google_api_key is None
    assert args.email is None
    assert not config_file(home).exists()


def test_returns_same_namespace(home: Path) -> None:
    args = make_args()
    assert read_config(args) is args


def test_read_google_api_key(home: Path) -> None:
    write_config(home, "[API]\ngoogleapikey = KEY123\n")
    args = read_config(make_args())
    assert args.google_api_key == "KEY123"
    assert args.email is None


def test_read_email(home: Path) -> None:
    write_config(home, "[API]\nopenstreetmapemail = me@example.com\n")
    args = read_config(make_args(use_openstreetmap=True))
    assert args.email == "me@example.com"
    assert args.google_api_key is None


def test_read_only_google_key_for_google(home: Path) -> None:
    # only the setting for the used service is read
    write_config(home, "[API]\ngoogleapikey = KEY123\nopenstreetmapemail = me@example.com\n")
    args = read_config(make_args())
    assert args.google_api_key == "KEY123"
    assert args.email is None


def test_read_only_email_for_openstreetmap(home: Path) -> None:
    write_config(home, "[API]\ngoogleapikey = KEY123\nopenstreetmapemail = me@example.com\n")
    args = read_config(make_args(use_openstreetmap=True))
    assert args.google_api_key is None
    assert args.email == "me@example.com"


@pytest.mark.parametrize("email", ["foo", "me@example", "@example.com", "me@example.c0m"])
def test_read_invalid_email_not_used(home: Path, capsys: pytest.CaptureFixture[str], email: str) -> None:
    file = write_config(home, f"[API]\nopenstreetmapemail = {email}\n")
    args = read_config(make_args(use_openstreetmap=True))
    assert args.email is None
    assert capsys.readouterr().out == f"(!) Not a valid email for OpenStreetMap in the config file {file}: {email}\n"


def test_read_invalid_email_ignored_for_google(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # not read for Google: no warning
    write_config(home, "[API]\nopenstreetmapemail = foo\n")
    args = read_config(make_args())
    assert args.email is None
    assert capsys.readouterr().out == ""


def test_key_names_are_case_insensitive(home: Path) -> None:
    write_config(home, "[API]\nGoogleApiKey = KEY123\n")
    assert read_config(make_args()).google_api_key == "KEY123"


def test_arguments_win_over_config(home: Path) -> None:
    write_config(home, "[API]\ngoogleapikey = CONFIG_KEY\nopenstreetmapemail = config@example.com\n")
    assert read_config(make_args(google_api_key="ARG_KEY")).google_api_key == "ARG_KEY"
    assert read_config(make_args(email="arg@example.com", use_openstreetmap=True)).email == "arg@example.com"


def test_config_without_api_section(home: Path) -> None:
    write_config(home, "[OTHER]\ngoogleapikey = KEY123\n")
    args = read_config(make_args())
    assert args.google_api_key is None
    assert args.email is None


def test_empty_config_file(home: Path) -> None:
    write_config(home, "")
    assert read_config(make_args()).google_api_key is None


def test_config_folder_without_file(home: Path) -> None:
    config_file(home).parent.mkdir(parents=True)
    assert read_config(make_args()).google_api_key is None


# MARK: write
def test_write_without_flag_does_nothing(home: Path) -> None:
    read_config(make_args(google_api_key="KEY123"))
    assert not config_file(home).exists()


def test_write_flag_without_values_does_nothing(home: Path) -> None:
    read_config(make_args(config_write=True))
    assert not config_file(home).exists()


def test_write_creates_folder_and_file(home: Path) -> None:
    read_config(make_args(google_api_key="KEY123", config_write=True))
    assert config_file(home).is_file()
    assert read_back(home)["API"]["googleapikey"] == "KEY123"
    assert "openstreetmapemail" not in read_back(home)["API"]


def test_write_email(home: Path) -> None:
    read_config(make_args(email="me@example.com", config_write=True))
    assert read_back(home)["API"]["openstreetmapemail"] == "me@example.com"


def test_write_adds_to_existing_config(home: Path) -> None:
    write_config(home, "[API]\nopenstreetmapemail = me@example.com\n\n[OTHER]\nkeep = yes\n")
    args = read_config(make_args(google_api_key="KEY123", config_write=True))
    config = read_back(home)
    assert config["API"]["googleapikey"] == "KEY123"
    assert config["API"]["openstreetmapemail"] == "me@example.com"
    # other sections are kept
    assert config["OTHER"]["keep"] == "yes"
    # the email is kept in the config, but not read for Google
    assert args.email is None


def test_write_adds_api_section(home: Path) -> None:
    write_config(home, "[OTHER]\nkeep = yes\n")
    read_config(make_args(google_api_key="KEY123", config_write=True))
    config = read_back(home)
    assert config["API"]["googleapikey"] == "KEY123"
    assert config["OTHER"]["keep"] == "yes"


def test_write_changed_value(home: Path) -> None:
    write_config(home, "[API]\ngoogleapikey = OLD_KEY\n")
    args = read_config(make_args(google_api_key="NEW_KEY", config_write=True))
    assert args.google_api_key == "NEW_KEY"
    assert read_back(home)["API"]["googleapikey"] == "NEW_KEY"


def test_write_unchanged_value_does_not_rewrite(home: Path) -> None:
    content = "[API]\ngoogleapikey = KEY123\n"
    file = write_config(home, content)
    # set an old modification time, a rewrite would change it
    os.utime(file, (1_000_000_000, 1_000_000_000))
    read_config(make_args(google_api_key="KEY123", config_write=True))
    assert file.stat().st_mtime == 1_000_000_000
    assert file.read_text(encoding="UTF-8") == content


def test_write_value_only_from_config_does_not_rewrite(home: Path) -> None:
    # -w without new values: the values read from the config are the same, nothing to write
    content = "[API]\ngoogleapikey = KEY123\n"
    file = write_config(home, content)
    os.utime(file, (1_000_000_000, 1_000_000_000))
    read_config(make_args(config_write=True))
    assert file.stat().st_mtime == 1_000_000_000


def test_write_then_read(home: Path) -> None:
    read_config(make_args(google_api_key="KEY123", config_write=True))
    assert read_config(make_args()).google_api_key == "KEY123"


# MARK: debug
def test_debug_output(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    read_config(make_args(google_api_key="KEY123", debug=True))
    assert "### OVERRIDE API: G: KEY123, O: None" in capsys.readouterr().out


def test_no_output_without_debug(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    read_config(make_args(google_api_key="KEY123"))
    assert capsys.readouterr().out == ""


# __END__
