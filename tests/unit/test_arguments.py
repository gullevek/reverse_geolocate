"""
unit tests for reverse_geolocate.setup.arguments.ArgumentSetup
arguments are passed with get_args(argv), folders are temporary folders
"""

import argparse
from pathlib import Path

import pytest

from reverse_geolocate.setup.arguments import ArgumentSetup

ALL_ATTRIBUTES = (
    "xmp_sources",
    "exclude_sources",
    "lightroom_folder",
    "lightroom_strict",
    "field_controls",
    "fuzzy_distance",
    "google_api_key",
    "use_openstreetmap",
    "email",
    "config_write",
    "read_only",
    "unset_only",
    "unset_gps_only",
    "no_autoadjust",
    "compact_view",
    "no_xmp_backup",
    "verbose",
    "debug",
    "test",
)
ARGUMENT_ERROR = "Argument error, see above"


@pytest.fixture
def source(tmp_path: Path) -> str:
    """a writable folder for -i"""
    folder = tmp_path / "xmp"
    folder.mkdir()
    return str(folder)


def get_args(*argv: str) -> argparse.Namespace:
    return ArgumentSetup().get_args(list(argv))


# MARK: defaults
def test_defaults(source: str) -> None:
    args = get_args("-i", source)
    assert args.xmp_sources == [source]
    # set by the post check
    assert args.exclude_sources == []
    assert args.verbose == 0
    assert args.unset_only == 0
    # not set
    for name in ("lightroom_folder", "field_controls", "fuzzy_distance", "google_api_key", "email"):
        assert getattr(args, name) is None, name
    for name in (
        "lightroom_strict",
        "use_openstreetmap",
        "config_write",
        "read_only",
        "unset_gps_only",
        "no_autoadjust",
        "compact_view",
        "no_xmp_backup",
        "debug",
        "test",
    ):
        assert getattr(args, name) is False, name


def test_all_attributes_exist(source: str) -> None:
    args = get_args("-i", source)
    for name in ALL_ATTRIBUTES:
        assert hasattr(args, name), name


def test_args_stored_on_object(source: str) -> None:
    setup = ArgumentSetup()
    args = setup.get_args(["-i", source])
    assert setup.args is args


# MARK: calling more than once
def test_get_args_twice(source: str, tmp_path: Path) -> None:
    setup = ArgumentSetup()
    first = setup.get_args(["-i", source])
    second = setup.get_args(["-i", str(tmp_path), "-r"])
    assert first.xmp_sources == [source]
    assert first.read_only is False
    assert second.xmp_sources == [str(tmp_path)]
    assert second.read_only is True


def test_get_args_reads_sys_argv(source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["reverse-geolocate", "-i", source, "-n"])
    args = ArgumentSetup().get_args()
    assert args.xmp_sources == [source]
    assert args.no_xmp_backup is True


# MARK: include / exclude / lightroom
def test_include_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-r")
    assert exc_info.value.code == 2
    assert "the following arguments are required: -i/--include-source" in capsys.readouterr().err


def test_include_multiple(tmp_path: Path) -> None:
    folders = [tmp_path / name for name in ("a", "b", "c")]
    for folder in folders:
        folder.mkdir()
    args = get_args("-i", str(folders[0]), str(folders[1]), "--include-source", str(folders[2]))
    assert args.xmp_sources == [str(folder) for folder in folders]


def test_include_file(tmp_path: Path) -> None:
    file = tmp_path / "a.xmp"
    file.touch()
    assert get_args("-i", str(file)).xmp_sources == [str(file)]


def test_exclude(source: str, tmp_path: Path) -> None:
    args = get_args("-i", source, "-x", str(tmp_path), "--exclude-source", source)
    assert args.exclude_sources == [str(tmp_path), source]


@pytest.mark.parametrize("flag", ["-i", "-x"])
def test_include_exclude_not_existing(source: str, tmp_path: Path, flag: str) -> None:
    argv = ["-i", source] if flag == "-x" else []
    with pytest.raises(SystemExit) as exc_info:
        get_args(*argv, flag, str(tmp_path / "missing"))
    assert exc_info.value.code == 2


@pytest.mark.parametrize("flag", ["-l", "--lightroom"])
def test_lightroom(source: str, tmp_path: Path, flag: str) -> None:
    args = get_args("-i", source, flag, str(tmp_path))
    assert args.lightroom_folder == str(tmp_path)


def test_lightroom_not_existing(source: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-i", source, "-l", str(tmp_path / "missing"))
    assert exc_info.value.code == 2
    assert "is not an existing directory" in capsys.readouterr().err


# MARK: field controls
def test_field_controls_lower_case_and_collected(source: str) -> None:
    args = get_args("-i", source, "-f", "City", "--field", "OVERWRITE", "-f", "countryCode")
    assert args.field_controls == ["city", "overwrite", "countrycode"]


@pytest.mark.parametrize("value", ["overwrite", "location", "city", "state", "country", "countrycode"])
def test_field_controls_choices(source: str, value: str) -> None:
    assert get_args("-i", source, "-f", value).field_controls == [value]


def test_field_controls_invalid(source: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-i", source, "-f", "street")
    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


# MARK: fuzzy distance
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["-d"], 10),
        (["--fuzzy-cache"], 10),
        (["-d", "25m"], 25),
        (["-d", "2KM"], 2000),
        (["-d", "3 km"], 3000),
    ],
)
def test_fuzzy_distance(source: str, argv: list[str], expected: int | None) -> None:
    assert get_args("-i", source, *argv).fuzzy_distance == expected


def test_fuzzy_distance_invalid(source: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-i", source, "-d", "abc")
    assert exc_info.value.code == 2


# MARK: verbose
@pytest.mark.parametrize(("argv", "expected"), [([], 0), (["-v"], 1), (["-vvv"], 3), (["-v", "--verbose"], 2)])
def test_verbose(source: str, argv: list[str], expected: int) -> None:
    assert get_args("-i", source, *argv).verbose == expected


# MARK: short / long flags
@pytest.mark.parametrize(
    ("short", "long", "dest"),
    [
        ("-s", "--strict", "lightroom_strict"),
        ("-o", "--openstreetmap", "use_openstreetmap"),
        ("-w", "--write-settings", "config_write"),
        ("-r", "--read-only", "read_only"),
        ("-p", "--unset-gps-only", "unset_gps_only"),
        ("-a", "--no-autoadjust", "no_autoadjust"),
        ("-c", "--compact", "compact_view"),
        ("-n", "--nobackup", "no_xmp_backup"),
    ],
)
def test_bool_flags(source: str, short: str, long: str, dest: str) -> None:
    assert getattr(get_args("-i", source), dest) is False
    assert getattr(get_args("-i", source, short), dest) is True
    assert getattr(get_args("-i", source, long), dest) is True


@pytest.mark.parametrize("flag", ["-u", "--unset-only"])
def test_unset_only(source: str, flag: str) -> None:
    assert get_args("-i", source, flag).unset_only is True


@pytest.mark.parametrize("flag", ["--debug", "--test"])
def test_long_only_flags(source: str, flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert getattr(get_args("-i", source, flag), flag.lstrip("-")) is True
    capsys.readouterr()


@pytest.mark.parametrize(("short", "long"), [("-g", "--google"), ("-e", "--email")])
def test_value_flags(source: str, short: str, long: str) -> None:
    value = "me@example.com"
    extra = ["-o"] if short == "-e" else []
    dest = "google_api_key" if short == "-g" else "email"
    assert getattr(get_args("-i", source, *extra, short, value), dest) == value
    assert getattr(get_args("-i", source, *extra, long, value), dest) == value


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-h")
    assert exc_info.value.code == 0
    assert "Reverse Geoencoding" in capsys.readouterr().out


# MARK: argument combinations
def test_valid_openstreetmap_with_email(source: str) -> None:
    args = get_args("-i", source, "-o", "-e", "me@example.com")
    assert args.use_openstreetmap is True
    assert args.email == "me@example.com"


def test_valid_google_key(source: str) -> None:
    assert get_args("-i", source, "-g", "KEY").google_api_key == "KEY"


@pytest.mark.parametrize(
    ("argv", "messages"),
    [
        (["-g", "KEY", "-o"], ["You cannot set a Google API key and use OpenStreetMap at the same time"]),
        (["-e", "me@example.com"], ["You cannot set an OpenStreetMap email and not use OpenStreetMap"]),
        (["-o", "-e", "foo"], ["Not a valid email for OpenStreetMap: foo"]),
        (
            ["-g", "KEY", "-e", "me@example.com"],
            [
                "You cannot set a Google API key and OpenStreetMap email at the same time",
                "You cannot set an OpenStreetMap email and not use OpenStreetMap",
            ],
        ),
        # all errors are printed before the exit
        (
            ["-g", "KEY", "-o", "-e", "foo"],
            [
                "You cannot set a Google API key and use OpenStreetMap at the same time",
                "You cannot set a Google API key and OpenStreetMap email at the same time",
                "Not a valid email for OpenStreetMap: foo",
            ],
        ),
    ],
)
def test_invalid_combinations(
    source: str, capsys: pytest.CaptureFixture[str], argv: list[str], messages: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-i", source, *argv)
    assert exc_info.value.code == ARGUMENT_ERROR
    out = capsys.readouterr().out
    for message in messages:
        assert message in out
    assert out.count("\n") == len(messages)


@pytest.mark.parametrize("email", ["me@example.com", "first.last@sub.example.org", "a@b.c"])
def test_email_valid(source: str, email: str) -> None:
    assert get_args("-i", source, "-o", "-e", email).email == email


@pytest.mark.parametrize("email", ["foo", "me@example", "@example.com", "me@.com", "me@example.c0m", "me@example."])
def test_email_invalid(source: str, email: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_args("-i", source, "-o", "-e", email)
    assert exc_info.value.code == ARGUMENT_ERROR
    assert f"Not a valid email for OpenStreetMap: {email}" in capsys.readouterr().out


# MARK: debug output
def test_debug_output(source: str, capsys: pytest.CaptureFixture[str]) -> None:
    get_args("-i", source, "--debug", "-r", "-vv")
    out = capsys.readouterr().out
    assert out.startswith("### ARGUMENT VARS: ")
    assert f"I: ['{source}']" in out
    assert "R: True" in out
    assert "V: 2" in out


def test_no_output_without_debug(source: str, capsys: pytest.CaptureFixture[str]) -> None:
    get_args("-i", source, "-r")
    assert capsys.readouterr().out == ""


# MARK: internal checks
def test_argument_type_error_becomes_system_exit(source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # argparse turns type errors into exit code 2 itself, this guards errors raised outside of it
    setup = ArgumentSetup()

    def raise_type_error(argv: list[str] | None = None) -> argparse.Namespace:
        raise argparse.ArgumentTypeError("broken")

    monkeypatch.setattr(setup.parser, "parse_args", raise_type_error)
    with pytest.raises(SystemExit) as exc_info:
        setup.get_args(["-i", source])
    assert exc_info.value.code == "Argument error: broken"


def test_check_without_parse_raises() -> None:
    setup = ArgumentSetup()
    with pytest.raises(ValueError, match="Could not setup"):
        setup._ArgumentSetup__arguments_check()  # type: ignore


def test_check_fills_missing_attributes() -> None:
    # a namespace without any attributes gets all of them, with the defaults
    setup = ArgumentSetup()
    setup.args = argparse.Namespace()
    setup._ArgumentSetup__arguments_check()  # type: ignore
    for name in ALL_ATTRIBUTES:
        assert hasattr(setup.args, name), name
    assert setup.args.verbose == 0
    assert setup.args.exclude_sources == []
    assert setup.args.unset_only == 0
    assert setup.args.xmp_sources is None


# __END__
