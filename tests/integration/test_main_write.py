"""
integration tests for main() in write mode: lookup, writing, backups, field controls, cache, failures
the map lookup is a fake (see FakeLookup), the XMP files are read and written with Exempi
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from integration_helpers import TOKYO_LAT, TOKYO_LONG, FakeLookup, RunResult, read_xmp, write_xmp
from libxmp import XMPMeta, consts

Run = Callable[..., RunResult]
Snapshot = Callable[[Path], dict[Path, bytes]]

LOOKUP_FIELDS = {"Location": "Jingumae", "City": "Shibuya", "State": "Tokyo", "Country": "Japan", "CountryCode": "JP"}
EMPTY_FIELDS = dict.fromkeys(LOOKUP_FIELDS, "")
OSAKA = {"Location": "Namba", "City": "Osaka", "State": "Osaka", "Country": "Japan", "CountryCode": "JP"}
# latitudes for the fuzzy cache, 1 minute is about 1853m
NEAR_LAT = "35,40.4725N"  # about 20m from TOKYO_LAT
FAR_LAT = "35,41.5N"  # about 1.9km from TOKYO_LAT


def location(path: Path) -> dict[str, str]:
    """the five location fields of an XMP file"""
    data = read_xmp(path)
    return {key: data[key] for key in LOOKUP_FIELDS}


# MARK: writing
def test_write(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src")
    assert result.exit_code is None
    assert read_xmp(file) == {"GPSLatitude": TOKYO_LAT, "GPSLongitude": TOKYO_LONG, **LOOKUP_FIELDS}
    assert result.statuses() == {"a.xmp": "UPDATED"}
    assert result.stat("XMP Files found") == 1
    assert result.stat("Updated") == 1
    assert result.stat("Skipped") == 0
    assert result.stat("New GeoLocation from Map") == 1
    assert result.stat("Failed reverse GeoLocate") == 0
    assert len(lookup.calls) == 1


def test_lookup_arguments(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", GPSLatitude="33,51.0S", GPSLongitude="151,12.6E")
    run_main("-i", tmp_path / "src")
    # DMS strings as in the XMP file, google is the default
    assert lookup.calls == [{"longitude": "151,12.6E", "latitude": "33,51.0S", "map_type": "google"}]


@pytest.mark.parametrize("argv", [["-o"], ["--openstreetmap", "-e", "me@example.com"]])
def test_lookup_openstreetmap(run_main: Run, tmp_path: Path, lookup: FakeLookup, argv: list[str]) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", *argv)
    assert lookup.calls[0]["map_type"] == "openstreetmap"


def test_sample_files_other_data_kept(run_main: Run, sample_folder: Path) -> None:
    run_main("-i", sample_folder)
    for file in sorted(sample_folder.glob("*.xmp")):
        if ".BK." in file.name:
            continue
        assert location(file) == LOOKUP_FIELDS
        # unrelated data of the camera XMP is kept
        xmp = XMPMeta()
        xmp.parse_from_str(file.read_text(encoding="UTF-8"))
        assert xmp.get_property(consts.XMP_NS_TIFF, "Model") == "X-T3"
        assert xmp.get_property(consts.XMP_NS_EXIF, "GPSLatitude") == TOKYO_LAT


def test_values_not_carried_over_between_files(run_main: Run, tmp_path: Path) -> None:
    # the XMP object is reused for all files, written data must not show up in the next file
    write_xmp(tmp_path / "src" / "1.xmp")
    second = write_xmp(tmp_path / "src" / "2.xmp", **{**OSAKA, "Location": ""})
    run_main("-i", tmp_path / "src")
    assert location(second) == {**OSAKA, "Location": "Jingumae"}


def test_second_run_skips(run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src")
    after_first = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src", "-v")
    # nothing to do: no lookup, no write, no new backup
    assert len(lookup.calls) == 1
    assert snapshot(tmp_path / "src") == after_first
    assert result.statuses() == {"a.xmp": "SKIP"}
    assert result.stat("Updated") == 0
    assert result.stat("Skipped") == 1


def test_upper_case_extension(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.XMP")
    run_main("-i", tmp_path / "src")
    assert location(file) == LOOKUP_FIELDS
    # the backup keeps the extension case
    assert sorted(path.name for path in (tmp_path / "src").iterdir()) == ["a.BK.1.XMP", "a.XMP"]


def test_cjk_values_written(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    file = write_xmp(tmp_path / "写真" / "東京.xmp")
    lookup.result.update({"Location": "神宮前", "City": "渋谷区", "State": "東京都", "Country": "日本"})
    run_main("-i", tmp_path / "写真")
    assert location(file) == {
        "Location": "神宮前",
        "City": "渋谷区",
        "State": "東京都",
        "Country": "日本",
        "CountryCode": "JP",
    }


# MARK: backups
def test_backup_created(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    original = file.read_bytes()
    run_main("-i", tmp_path / "src")
    backup = tmp_path / "src" / "a.BK.1.xmp"
    assert backup.read_bytes() == original
    assert file.read_bytes() != original


def test_backup_counter_increases(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src")
    after_first = file.read_bytes()
    # second write with a changed value
    lookup.result = {**lookup.result, "City": "Minato"}
    run_main("-i", tmp_path / "src", "-f", "overwrite")
    assert (tmp_path / "src" / "a.BK.2.xmp").read_bytes() == after_first
    assert location(file)["City"] == "Minato"


def test_backup_counter_after_gap(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    for number in (1, 3):
        (tmp_path / "src" / f"a.BK.{number}.xmp").write_text("old backup", encoding="UTF-8")
    run_main("-i", tmp_path / "src")
    assert (tmp_path / "src" / "a.BK.4.xmp").is_file()
    # existing backups are not touched
    assert (tmp_path / "src" / "a.BK.3.xmp").read_text(encoding="UTF-8") == "old backup"


@pytest.mark.parametrize("flag", ["-n", "--nobackup"])
def test_no_backup(run_main: Run, tmp_path: Path, flag: str) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", flag)
    assert location(file) == LOOKUP_FIELDS
    assert [path.name for path in (tmp_path / "src").iterdir()] == ["a.xmp"]


# MARK: test mode
def test_test_mode_writes_nothing(run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src", "--test")
    assert snapshot(tmp_path / "src") == before
    # the lookup is done, the result is shown and counted
    assert len(lookup.calls) == 1
    assert "[TEST] Would write" in result.out
    assert "'City': 'Shibuya'" in result.out
    assert result.statuses() == {"a.xmp": "UPDATED"}
    assert result.stat("Updated") == 1


def test_test_mode_output_lines(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "--test")
    test_lines = [line for line in result.lines if "[TEST] Would write" in line]
    # the [TEST] line and the status are on separate lines
    assert len(test_lines) == 1
    assert test_lines[0].endswith(f" {file}")
    status_line = result.lines[result.lines.index(test_lines[0]) + 1]
    assert status_line.endswith("a.xmp: [UPDATED]")


# MARK: field controls
def test_partial_fill_keeps_existing(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Osaka", Country="Nippon")
    run_main("-i", tmp_path / "src")
    assert location(file) == {**LOOKUP_FIELDS, "City": "Osaka", "Country": "Nippon"}


def test_complete_file_skipped(run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **OSAKA)
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src")
    assert lookup.calls == []
    assert snapshot(tmp_path / "src") == before
    # the skip is only printed with -v
    assert result.statuses() == {}
    assert result.stat("Skipped") == 1


def test_overwrite_same_values_not_written(
    run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot
) -> None:
    # the lookup returns the values that are already set: nothing to write, no backup
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src", "-f", "overwrite", "-v")
    assert len(lookup.calls) == 1
    assert snapshot(tmp_path / "src") == before
    assert result.statuses() == {"a.xmp": "SKIP"}
    assert result.stat("Updated") == 0
    assert result.stat("Skipped") == 1
    assert result.stat("New GeoLocation from Map") == 0


def test_overwrite_only_changed_values(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    # one value differs: the file is written, the other values stay the same
    file = write_xmp(tmp_path / "src" / "a.xmp", **{**LOOKUP_FIELDS, "City": "Minato"})
    result = run_main("-i", tmp_path / "src", "-f", "overwrite")
    assert location(file) == LOOKUP_FIELDS
    assert (tmp_path / "src" / "a.BK.1.xmp").is_file()
    assert result.statuses() == {"a.xmp": "UPDATED"}


def test_overwrite_same_values_test_mode(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    result = run_main("-i", tmp_path / "src", "-f", "overwrite", "--test")
    assert "[TEST] Would write" not in result.out
    assert result.stat("Updated") == 0


def test_overwrite_selected_field_same_value(run_main: Run, tmp_path: Path, snapshot: Snapshot) -> None:
    write_xmp(tmp_path / "src" / "a.xmp", City="Shibuya")
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src", "-f", "city", "-f", "overwrite")
    assert snapshot(tmp_path / "src") == before
    assert result.stat("Skipped") == 1


def test_overwrite_empty_lookup_value_keeps_existing(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    # the lookup found no Location and State: the existing values are not cleared
    lookup.result = {**lookup.result, "Location": "", "State": ""}
    file = write_xmp(tmp_path / "src" / "a.xmp", **OSAKA)
    result = run_main("-i", tmp_path / "src", "-f", "overwrite")
    assert location(file) == {**LOOKUP_FIELDS, "Location": "Namba", "State": "Osaka"}
    assert result.statuses() == {"a.xmp": "UPDATED"}


def test_overwrite_only_empty_changes_not_written(
    run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot
) -> None:
    # the only differences are empty lookup values: nothing to write, no backup
    lookup.result = {**lookup.result, "Location": "", "City": ""}
    write_xmp(tmp_path / "src" / "a.xmp", **LOOKUP_FIELDS)
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src", "-f", "overwrite", "-v")
    assert snapshot(tmp_path / "src") == before
    assert result.statuses() == {"a.xmp": "SKIP"}


def test_overwrite_selected_field_empty_lookup_value(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    lookup.result = {**lookup.result, "City": ""}
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Osaka")
    result = run_main("-i", tmp_path / "src", "-f", "city", "-f", "overwrite")
    assert location(file) == {**EMPTY_FIELDS, "City": "Osaka"}
    assert result.stat("Skipped") == 1


def test_empty_lookup_values_not_written(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    # without overwrite: empty fields stay empty if the lookup has no value for them
    lookup.result = {**lookup.result, "Location": ""}
    file = write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src")
    assert location(file) == {**LOOKUP_FIELDS, "Location": ""}
    assert "Iptc4xmpCore:Location" not in file.read_text(encoding="UTF-8")


def test_repeated_overwrite_no_new_backups(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    for _ in range(3):
        run_main("-i", tmp_path / "src", "-f", "overwrite")
    # only the first run changed the file
    assert sorted(path.name for path in (tmp_path / "src").iterdir()) == ["a.BK.1.xmp", "a.xmp"]


@pytest.mark.parametrize("flag", ["-f", "--field"])
def test_overwrite_all(run_main: Run, tmp_path: Path, flag: str) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", **OSAKA)
    run_main("-i", tmp_path / "src", flag, "overwrite")
    assert location(file) == LOOKUP_FIELDS


def test_only_selected_field(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-f", "city")
    assert location(file) == {**EMPTY_FIELDS, "City": "Shibuya"}


def test_selected_fields_case_insensitive(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    run_main("-i", tmp_path / "src", "-f", "City", "-f", "COUNTRYCODE")
    assert location(file) == {**EMPTY_FIELDS, "City": "Shibuya", "CountryCode": "JP"}


def test_selected_field_already_set_skipped(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Osaka")
    result = run_main("-i", tmp_path / "src", "-f", "city")
    # City is set, other fields are not selected: nothing to do
    assert lookup.calls == []
    assert location(file) == {**EMPTY_FIELDS, "City": "Osaka"}
    assert result.stat("Skipped") == 1


def test_overwrite_selected_field(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp", City="Osaka", State="Osaka")
    run_main("-i", tmp_path / "src", "-f", "city", "-f", "overwrite")
    assert location(file) == {**EMPTY_FIELDS, "City": "Shibuya", "State": "Osaka"}


# MARK: cache
def test_exact_cache(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    first = write_xmp(tmp_path / "src" / "1.xmp")
    second = write_xmp(tmp_path / "src" / "2.xmp")
    result = run_main("-i", tmp_path / "src")
    assert len(lookup.calls) == 1
    assert location(first) == location(second) == LOOKUP_FIELDS
    assert result.statuses() == {"1.xmp": "UPDATED", "2.xmp": "UPDATED FROM CACHE"}
    assert result.stat("GeoLocation from Cache") == 1
    assert result.stat("GeoLocation from Fuzzy Cache") == 0
    assert result.stat("Updated") == 2


def test_map_count_only_lookups(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    write_xmp(tmp_path / "src" / "1.xmp")
    write_xmp(tmp_path / "src" / "2.xmp")
    write_xmp(tmp_path / "src" / "3.xmp", GPSLatitude=NEAR_LAT)
    write_xmp(tmp_path / "src" / "4.xmp", GPSLatitude=FAR_LAT)
    result = run_main("-i", tmp_path / "src", "-d", "100m")
    # 1 and 4 looked up, 2 exact cache, 3 fuzzy cache
    assert len(lookup.calls) == 2
    assert result.stat("New GeoLocation from Map") == 2
    assert result.stat("GeoLocation from Cache") == 2
    assert result.stat("GeoLocation from Fuzzy Cache") == 1
    assert result.stat("Updated") == 4


def test_no_fuzzy_cache_without_flag(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    write_xmp(tmp_path / "src" / "1.xmp")
    write_xmp(tmp_path / "src" / "2.xmp", GPSLatitude=NEAR_LAT)
    run_main("-i", tmp_path / "src")
    assert len(lookup.calls) == 2


@pytest.mark.parametrize("argv", [["-d", "100m"], ["-d"], ["--fuzzy-cache", "1km"]])
def test_fuzzy_cache_near(run_main: Run, tmp_path: Path, lookup: FakeLookup, argv: list[str]) -> None:
    # about 20m apart: inside 100m, 1km, but not inside the default 10m
    write_xmp(tmp_path / "src" / "1.xmp")
    second = write_xmp(tmp_path / "src" / "2.xmp", GPSLatitude=NEAR_LAT)
    lookup.by_latitude[NEAR_LAT] = {"City": "Near"}
    result = run_main("-i", tmp_path / "src", *argv)
    if argv == ["-d"]:
        # default 10m
        assert len(lookup.calls) == 2
        assert location(second)["City"] == "Near"
        return
    assert len(lookup.calls) == 1
    assert location(second) == LOOKUP_FIELDS
    assert result.statuses()["2.xmp"] == "UPDATED FROM CACHE"
    assert result.stat("GeoLocation from Fuzzy Cache") == 1
    assert result.stat("GeoLocation from Cache") == 1


def test_fuzzy_cache_far(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    write_xmp(tmp_path / "src" / "1.xmp")
    second = write_xmp(tmp_path / "src" / "2.xmp", GPSLatitude=FAR_LAT)
    lookup.by_latitude[FAR_LAT] = {"City": "Far"}
    result = run_main("-i", tmp_path / "src", "-d", "100m")
    assert len(lookup.calls) == 2
    assert location(second)["City"] == "Far"
    assert result.stat("GeoLocation from Fuzzy Cache") == 0


def test_fuzzy_cache_closest_match(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    # 1 and 2 are about 111m apart (both looked up), 3 is 74m from 1 and 37m from 2
    lookup.by_latitude = {"35,40.40N": {"City": "One"}, "35,40.46N": {"City": "Two"}}
    write_xmp(tmp_path / "src" / "1.xmp", GPSLatitude="35,40.40N")
    write_xmp(tmp_path / "src" / "2.xmp", GPSLatitude="35,40.46N")
    third = write_xmp(tmp_path / "src" / "3.xmp", GPSLatitude="35,40.44N")
    run_main("-i", tmp_path / "src", "-d", "100m")
    assert len(lookup.calls) == 2
    assert location(third)["City"] == "Two"


def test_fuzzy_match_is_cached(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    # 2 is a fuzzy match of 1, 3 has the same coordinates as 2: exact cache hit
    write_xmp(tmp_path / "src" / "1.xmp")
    write_xmp(tmp_path / "src" / "2.xmp", GPSLatitude=NEAR_LAT)
    write_xmp(tmp_path / "src" / "3.xmp", GPSLatitude=NEAR_LAT)
    result = run_main("-i", tmp_path / "src", "-d", "100m")
    assert len(lookup.calls) == 1
    assert result.stat("GeoLocation from Fuzzy Cache") == 1
    assert result.stat("GeoLocation from Cache") == 2


# MARK: failures
def test_missing_gps_fails_and_continues(run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot) -> None:
    write_xmp(tmp_path / "src" / "1_no_gps.xmp", GPSLatitude="", GPSLongitude="")
    second = write_xmp(tmp_path / "src" / "2.xmp")
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src")
    assert result.exit_code is None
    assert result.statuses() == {"1_no_gps.xmp": "FAILED", "2.xmp": "UPDATED"}
    assert "(!) No valid GPS data for geo location lookup" in result.out
    # only the file with GPS is looked up and written
    assert lookup.calls == [{"longitude": TOKYO_LONG, "latitude": TOKYO_LAT, "map_type": "google"}]
    assert (tmp_path / "src" / "1_no_gps.xmp").read_bytes() == before[tmp_path / "src" / "1_no_gps.xmp"]
    assert location(second) == LOOKUP_FIELDS
    assert result.stat("Failed reverse GeoLocate") == 1
    # failed files are listed at the end
    assert result.lines[result.lines.index("Files that failed to update:") + 1] == str(
        tmp_path / "src" / "1_no_gps.xmp"
    )


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [("35.674", "139.74"), ("35,40.46N", ""), ("", "139,44.39E"), ("95,0.0N", "139,44.39E")],
)
def test_invalid_gps_fails(run_main: Run, tmp_path: Path, lookup: FakeLookup, latitude: str, longitude: str) -> None:
    # 95,0.0N has a valid format: it is passed to the lookup, which returns the error
    if latitude == "95,0.0N":
        lookup.result = {**lookup.result, **EMPTY_FIELDS, "status": "ERROR"}
    write_xmp(tmp_path / "src" / "a.xmp", GPSLatitude=latitude, GPSLongitude=longitude)
    result = run_main("-i", tmp_path / "src")
    assert result.exit_code is None
    assert result.statuses() == {"a.xmp": "FAILED"}
    assert not (tmp_path / "src" / "a.BK.1.xmp").exists()


def test_lookup_without_country_fails(run_main: Run, tmp_path: Path, lookup: FakeLookup, snapshot: Snapshot) -> None:
    lookup.result = {**lookup.result, "Country": ""}
    write_xmp(tmp_path / "src" / "a.xmp")
    before = snapshot(tmp_path / "src")
    result = run_main("-i", tmp_path / "src")
    assert "(!) Could not geo loaction data" in result.out
    assert result.statuses() == {"a.xmp": "FAILED"}
    assert snapshot(tmp_path / "src") == before


def test_failed_lookup_is_cached(run_main: Run, tmp_path: Path, lookup: FakeLookup) -> None:
    lookup.result = {**lookup.result, "Country": ""}
    write_xmp(tmp_path / "src" / "1.xmp")
    write_xmp(tmp_path / "src" / "2.xmp")
    result = run_main("-i", tmp_path / "src")
    assert len(lookup.calls) == 1
    assert result.statuses() == {"1.xmp": "FAILED", "2.xmp": "FAILED"}
    assert result.stat("Failed reverse GeoLocate") == 2


def test_failed_and_updated_counts(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "1.xmp")
    write_xmp(tmp_path / "src" / "2.xmp", GPSLatitude="", GPSLongitude="")
    write_xmp(tmp_path / "src" / "3.xmp", **OSAKA)
    write_xmp(tmp_path / "src" / "4.xmp", GPSLatitude="", GPSLongitude="")
    result = run_main("-i", tmp_path / "src", "-v")
    assert result.statuses() == {"1.xmp": "UPDATED", "2.xmp": "FAILED", "3.xmp": "SKIP", "4.xmp": "FAILED"}
    assert result.stat("XMP Files found") == 4
    assert result.stat("Updated") == 1
    assert result.stat("Skipped") == 1
    assert result.stat("Failed reverse GeoLocate") == 2
    failed_line = result.lines[result.lines.index("Files that failed to update:") + 1]
    assert failed_line == f"{tmp_path / 'src' / '2.xmp'}, {tmp_path / 'src' / '4.xmp'}"


def test_no_failed_list_without_failures(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    assert "Files that failed to update:" not in run_main("-i", tmp_path / "src").out


# MARK: output
def test_write_mode_statistics(run_main: Run, tmp_path: Path) -> None:
    write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src")
    for name in (
        "Updated",
        "Skipped",
        "New GeoLocation from Map",
        "GeoLocation from Cache",
        "GeoLocation from Fuzzy Cache",
        "Failed reverse GeoLocate",
    ):
        assert name in result.out
    assert "XMP Files listed" not in result.out
    # lightroom statistics only with -l
    assert "Lightroom" not in result.out


def status_paths(result: RunResult) -> list[str]:
    """the printed file paths of the status lines"""
    return [line.rsplit(": [", 1)[0] for line in result.lines if line.endswith("]") and ": [" in line]


def test_display_path_relative_to_call_folder(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_xmp(tmp_path / "photos" / "2026" / "a.xmp")
    write_xmp(tmp_path / "photos" / "b.xmp")
    monkeypatch.chdir(tmp_path)
    result = run_main("-i", tmp_path / "photos")
    # given absolute, printed relative to the folder the script is called from
    assert status_paths(result) == ["photos/b.xmp", "photos/2026/a.xmp"]


def test_display_path_call_folder_is_source(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_xmp(tmp_path / "photos" / "a.xmp")
    monkeypatch.chdir(tmp_path / "photos")
    assert status_paths(run_main("-i", ".")) == ["a.xmp"]


def test_display_path_outside_call_folder(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = write_xmp(tmp_path / "photos" / "a.xmp")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    # outside of the call folder: the path as given, no "../" path (--test: both runs write nothing)
    assert status_paths(run_main("-i", tmp_path / "photos", "--test")) == [str(file)]
    assert status_paths(run_main("-i", "../photos", "--test")) == ["../photos/a.xmp"]


def test_display_path_failed_and_skipped(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_xmp(tmp_path / "photos" / "1.xmp", GPSLatitude="", GPSLongitude="")
    write_xmp(tmp_path / "photos" / "2.xmp", **OSAKA)
    monkeypatch.chdir(tmp_path)
    result = run_main("-i", tmp_path / "photos", "-v")
    assert status_paths(result) == ["(!) No valid GPS data for geo location lookup photos/1.xmp", "photos/2.xmp"]
    # the failed list at the end keeps the full path
    assert result.lines[result.lines.index("Files that failed to update:") + 1] == str(tmp_path / "photos" / "1.xmp")


def test_debug_output(run_main: Run, tmp_path: Path) -> None:
    file = write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src", "--debug")
    # tests run outside of tmp_path: the display path is the full path
    assert f"---> {file} -> {file}: " in result.out
    assert "### Map Location (google):" in result.out
    assert "### *** CACHE:" in result.out


# MARK: error exits
def test_argument_error_exit(run_main: Run) -> None:
    result = run_main()
    assert result.exit_code == 2
    assert "the following arguments are required" in result.err


def test_argument_combination_error_exit(run_main: Run, tmp_path: Path) -> None:
    result = run_main("-i", tmp_path, "-g", "KEY", "-o")
    assert result.exit_code == "Argument error, see above"


def test_exempi_not_available(run_main: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from libxmp import ExempiLoadError

    from reverse_geolocate import reverse_geolocate as reverse_geolocate_module

    def broken_xmp_meta() -> XMPMeta:
        raise ExempiLoadError("library missing")

    monkeypatch.setattr(reverse_geolocate_module, "XMPMeta", broken_xmp_meta)
    write_xmp(tmp_path / "src" / "a.xmp")
    result = run_main("-i", tmp_path / "src")
    assert result.exit_code == 1
    assert "(!) Exempi library not found or not working" in result.out


# __END__
