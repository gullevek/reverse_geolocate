"""
shared fixtures for the main() integration tests

- XMP files are read/written with the real Exempi library (the tests are not collected if it is missing)
- the map lookup is replaced by a fake, no network access
- HOME points to a temporary folder (no real config file is read), the terminal width is fixed
"""

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from integration_helpers import SAMPLE_FILES, TERMINAL_COLUMNS, FakeLookup, RunResult


def exempi_available() -> bool:
    """the script needs the Exempi library, it is loaded on import of libxmp"""
    try:
        from libxmp import XMPMeta

        XMPMeta()
    except Exception:  # noqa: BLE001 - any load error means no Exempi
        return False
    return True


# without Exempi the script can not be imported, do not collect the tests
collect_ignore_glob = [] if exempi_available() else ["test_*.py"]


# MARK: environment
@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """no real user config, fixed terminal size"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("COLUMNS", str(TERMINAL_COLUMNS))
    monkeypatch.setenv("LINES", "50")


# MARK: fake lookup
@pytest.fixture(autouse=True)
def lookup(monkeypatch: pytest.MonkeyPatch) -> FakeLookup:
    # imported here, the script module needs Exempi
    from reverse_geolocate import reverse_geolocate as reverse_geolocate_module

    fake = FakeLookup()
    monkeypatch.setattr(reverse_geolocate_module, "reverse_geolocate", fake)
    return fake


# MARK: run main
@pytest.fixture
def run_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Callable[..., RunResult]:
    """runs main() with the given command line arguments, returns the output and exit code"""

    from reverse_geolocate import reverse_geolocate as reverse_geolocate_module

    def run(*argv: str | Path) -> RunResult:
        monkeypatch.setattr(sys, "argv", ["reverse-geolocate", *(str(arg) for arg in argv)])
        exit_code: int | str | None = None
        try:
            reverse_geolocate_module.main()
        except SystemExit as e:
            exit_code = e.code
        captured = capsys.readouterr()
        return RunResult(out=captured.out, err=captured.err, exit_code=exit_code, lines=captured.out.splitlines())

    return run


# MARK: files
@pytest.fixture
def sample_folder(tmp_path: Path) -> Path:
    """copy of the repository sample XMP files"""
    folder = tmp_path / "samples"
    folder.mkdir()
    for file in SAMPLE_FILES:
        shutil.copy(file, folder / file.name)
    return folder


@pytest.fixture
def snapshot() -> Callable[[Path], dict[Path, bytes]]:
    """content of all files below a folder, to check that nothing was changed or added"""

    def take(folder: Path) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}

    return take


# __END__
