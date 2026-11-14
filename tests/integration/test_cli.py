"""
smoke tests: the installed reverse-geolocate command as a real process
(entry point, packaging, real exit codes and output)

no network access: only runs that need no map lookup (read only, complete files, data from Lightroom),
any request would go to an unreachable proxy and fail
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers.lightroom_catalog_builder import LightroomCatalogBuilder
from integration_helpers import SAMPLE_FILES, read_xmp, write_xmp

# console script next to the Python executable of the virtual environment
COMMAND = shutil.which("reverse-geolocate", path=str(Path(sys.executable).parent))
pytestmark = pytest.mark.skipif(COMMAND is None, reason="reverse-geolocate command not installed")

LOCATION = {"Location": "Namba", "City": "Osaka", "State": "Osaka", "Country": "Japan", "CountryCode": "JP"}


def run_command(tmp_path: Path, *argv: str | Path, module: bool = False) -> subprocess.CompletedProcess[str]:
    """runs the command in tmp_path, with a temporary HOME and without network"""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "COLUMNS": "200",
        # any request fails, no real lookup (requests uses these proxies)
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
    }
    command = [sys.executable, "-m", "reverse_geolocate.reverse_geolocate"] if module else [str(COMMAND)]
    return subprocess.run(
        [*command, *(str(arg) for arg in argv)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def samples(tmp_path: Path) -> Path:
    folder = tmp_path / "samples"
    folder.mkdir()
    for file in SAMPLE_FILES:
        shutil.copy(file, folder / file.name)
    return folder


# MARK: arguments
def test_help(tmp_path: Path) -> None:
    result = run_command(tmp_path, "--help")
    assert result.returncode == 0
    assert "Reverse Geoencoding" in result.stdout


def test_missing_include(tmp_path: Path) -> None:
    result = run_command(tmp_path)
    assert result.returncode == 2
    assert "the following arguments are required: -i/--include-source" in result.stderr


def test_argument_combination_error(tmp_path: Path) -> None:
    result = run_command(tmp_path, "-i", tmp_path, "-g", "KEY", "-o")
    assert result.returncode == 1
    assert "You cannot set a Google API key and use OpenStreetMap at the same time" in result.stdout
    assert "Argument error, see above" in result.stderr


# MARK: read only
def test_read_only(tmp_path: Path, samples: Path) -> None:
    before = {path.name: path.read_bytes() for path in samples.iterdir()}
    result = run_command(tmp_path, "-r", "-i", "samples")
    assert result.returncode == 0, result.stderr
    assert "> Page 1/1" in result.stdout
    for file in SAMPLE_FILES:
        assert file.name in result.stdout
    assert "XMP Files found                  :         3" in result.stdout
    assert "XMP Files listed                 :         3" in result.stdout
    # nothing written
    assert {path.name: path.read_bytes() for path in samples.iterdir()} == before


def test_module_run(tmp_path: Path, samples: Path) -> None:
    # python -m reverse_geolocate.reverse_geolocate works the same
    result = run_command(tmp_path, "-r", "-i", "samples", module=True)
    assert result.returncode == 0, result.stderr
    assert "XMP Files listed                 :         3" in result.stdout


def test_read_only_damaged_file(tmp_path: Path, samples: Path) -> None:
    (samples / "broken.xmp").write_text("just text", encoding="UTF-8")
    result = run_command(tmp_path, "-r", "-i", "samples")
    assert result.returncode == 0
    assert "(!) Could not read XMP data (no valid XMP" in result.stdout
    assert "XMP Files not readable           :         1" in result.stdout


# MARK: write
def test_write_complete_files_skipped(tmp_path: Path) -> None:
    # complete files: no lookup needed, nothing written
    file = write_xmp(tmp_path / "src" / "a.xmp", **LOCATION)
    before = file.read_bytes()
    result = run_command(tmp_path, "-i", "src", "-v")
    assert result.returncode == 0, result.stderr
    assert "src/a.xmp: [SKIP]" in result.stdout
    assert "Skipped                          :         1" in result.stdout
    assert file.read_bytes() == before


def test_write_from_lightroom(tmp_path: Path) -> None:
    # all data from Lightroom: written without a lookup
    file = write_xmp(tmp_path / "src" / "a.xmp", GPSLatitude="", GPSLongitude="")
    LightroomCatalogBuilder(tmp_path / "lightroom").add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LOCATION)
    result = run_command(tmp_path, "-i", "src", "-l", "lightroom")
    assert result.returncode == 0, result.stderr
    assert "src/a.xmp: [UPDATED]" in result.stdout
    assert "GeoLocation from Lightroom       :         1" in result.stdout
    assert read_xmp(file) == {"GPSLatitude": "35,30.0N", "GPSLongitude": "139,30.0E", **LOCATION}
    assert (tmp_path / "src" / "a.BK.1.xmp").is_file()


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="file permissions are not enforced (Windows or root)",
)
def test_write_protected_file_exit_code(tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", GPSLatitude="", GPSLongitude="")
    LightroomCatalogBuilder(tmp_path / "lightroom").add_image(file, gps_latitude=35.5, gps_longitude=139.5, **LOCATION)
    file.chmod(0o444)
    try:
        result = run_command(tmp_path, "-i", "src", "-l", "lightroom")
    finally:
        file.chmod(0o644)
    assert result.returncode == 1
    assert "(!!!) CRITICAL: Could not write the XMP file src/a.xmp: no write permission" in result.stdout
    # the summary is printed
    assert "XMP Files found                  :         1" in result.stdout


def test_no_lightroom_catalog_exit_code(tmp_path: Path, samples: Path) -> None:
    (tmp_path / "lightroom").mkdir()
    result = run_command(tmp_path, "-i", "samples", "-l", "lightroom")
    assert result.returncode == 1
    assert "(!) We could not find a lrcat file in the given lightroom folder" in result.stdout


# __END__
