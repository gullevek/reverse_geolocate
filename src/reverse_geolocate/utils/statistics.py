"""
statistics of a run and the summary output at the end
"""

from dataclasses import dataclass, field


@dataclass
class RunStatistics:
    """counters for the summary at the end of a run"""

    # XMP files found (work files)
    found: int = 0
    # read only: files listed (after the unset filters)
    listed: int = 0
    # write mode
    changed: int = 0
    skipped: int = 0
    failed: int = 0
    # sources of the written data
    map: int = 0
    cache: int = 0
    fuzzy_cache: int = 0
    lightroom: int = 0
    lightroom_not_found: int = 0
    lightroom_many_found: int = 0
    # files that could not be updated, printed at the end
    failed_files: list[str] = field(default_factory=list[str])


def print_statistics(statistics: RunStatistics, read_only: bool, use_lightroom: bool) -> None:
    """
    prints the summary at the end of the run

    Args:
        statistics (RunStatistics): counters of the run
        read_only (bool): read only run (list) or write run
        use_lightroom (bool): Lightroom catalog was used, prints the Lightroom counters
    """
    print(f"{'=' * 44}")
    print(f"XMP Files found                  : {statistics.found:9,}")
    if read_only:
        print(f"XMP Files listed                 : {statistics.listed:9,}")
        return
    print(f"Updated                          : {statistics.changed:9,}")
    print(f"Skipped                          : {statistics.skipped:9,}")
    print(f"New GeoLocation from Map         : {statistics.map:9,}")
    print(f"GeoLocation from Cache           : {statistics.cache:9,}")
    print(f"GeoLocation from Fuzzy Cache     : {statistics.fuzzy_cache:9,}")
    print(f"Failed reverse GeoLocate         : {statistics.failed:9,}")
    if use_lightroom:
        print(f"GeoLocation from Lightroom       : {statistics.lightroom:9,}")
        print(f"No Lightroom data found          : {statistics.lightroom_not_found:9,}")
        print(f"More than one found in Lightroom : {statistics.lightroom_many_found:9,}")
    # if we have failed data
    if statistics.failed_files:
        print(f"{'-' * 44}")
        print("Files that failed to update:")
        print(f"{', '.join(statistics.failed_files)}")


# __END__
