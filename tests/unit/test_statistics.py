"""
unit tests for reverse_geolocate.utils.statistics
"""

import pytest

from reverse_geolocate.utils.statistics import RunStatistics, print_statistics

WRITE_LINES = (
    "Updated",
    "Skipped",
    "New GeoLocation from Map",
    "GeoLocation from Cache",
    "GeoLocation from Fuzzy Cache",
    "Failed reverse GeoLocate",
)
LIGHTROOM_LINES = ("GeoLocation from Lightroom", "No Lightroom data found", "More than one found in Lightroom")


def test_defaults() -> None:
    statistics = RunStatistics()
    assert statistics.found == statistics.changed == statistics.lightroom == 0
    assert statistics.failed_files == []
    # own list for each instance
    RunStatistics().failed_files.append("x")
    assert RunStatistics().failed_files == []


def test_read_only(capsys: pytest.CaptureFixture[str]) -> None:
    print_statistics(RunStatistics(found=12, listed=5), read_only=True, use_lightroom=True)
    assert capsys.readouterr().out.splitlines() == [
        "=" * 44,
        "XMP Files found                  :        12",
        "XMP Files listed                 :         5",
    ]


def test_write(capsys: pytest.CaptureFixture[str]) -> None:
    statistics = RunStatistics(found=10, changed=6, skipped=2, failed=2, map=3, cache=2, fuzzy_cache=1)
    print_statistics(statistics, read_only=False, use_lightroom=False)
    assert capsys.readouterr().out.splitlines() == [
        "=" * 44,
        "XMP Files found                  :        10",
        "Updated                          :         6",
        "Skipped                          :         2",
        "New GeoLocation from Map         :         3",
        "GeoLocation from Cache           :         2",
        "GeoLocation from Fuzzy Cache     :         1",
        "Failed reverse GeoLocate         :         2",
    ]


def test_write_with_lightroom(capsys: pytest.CaptureFixture[str]) -> None:
    statistics = RunStatistics(lightroom=4, lightroom_not_found=2, lightroom_many_found=1)
    print_statistics(statistics, read_only=False, use_lightroom=True)
    lines = capsys.readouterr().out.splitlines()
    assert lines[-3:] == [
        "GeoLocation from Lightroom       :         4",
        "No Lightroom data found          :         2",
        "More than one found in Lightroom :         1",
    ]


def test_lightroom_only_in_write_mode(capsys: pytest.CaptureFixture[str]) -> None:
    print_statistics(RunStatistics(), read_only=True, use_lightroom=True)
    out = capsys.readouterr().out
    for name in (*WRITE_LINES, *LIGHTROOM_LINES):
        assert name not in out


def test_failed_files(capsys: pytest.CaptureFixture[str]) -> None:
    statistics = RunStatistics(failed=2, failed_files=["/a/1.xmp", "/b/2.xmp"])
    print_statistics(statistics, read_only=False, use_lightroom=False)
    assert capsys.readouterr().out.splitlines()[-3:] == [
        "-" * 44,
        "Files that failed to update:",
        "/a/1.xmp, /b/2.xmp",
    ]


def test_read_only_unreadable_files(capsys: pytest.CaptureFixture[str]) -> None:
    statistics = RunStatistics(found=3, listed=1, failed=2, failed_files=["/a/1.xmp", "/b/2.xmp"])
    print_statistics(statistics, read_only=True, use_lightroom=False)
    assert capsys.readouterr().out.splitlines() == [
        "=" * 44,
        "XMP Files found                  :         3",
        "XMP Files listed                 :         1",
        "XMP Files not readable           :         2",
        "-" * 44,
        "Files that could not be read:",
        "/a/1.xmp, /b/2.xmp",
    ]


def test_no_failed_files(capsys: pytest.CaptureFixture[str]) -> None:
    print_statistics(RunStatistics(), read_only=False, use_lightroom=False)
    assert "Files that failed to update:" not in capsys.readouterr().out


def test_thousands_separator(capsys: pytest.CaptureFixture[str]) -> None:
    print_statistics(RunStatistics(found=1234567), read_only=True, use_lightroom=False)
    assert "XMP Files found                  : 1,234,567" in capsys.readouterr().out


# __END__
