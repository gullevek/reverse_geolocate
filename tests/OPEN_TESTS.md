# Open tests and decisions

State of the test suite and what is still missing, so it can be picked up later.

## Current state

- 1520 tests (unit + integration), 100% line and branch coverage of `src/reverse_geolocate`
- `tests/unit`: no Exempi needed
- `tests/integration`: needs the Exempi library (`main()`, XMP read/write, command line);
  without Exempi these tests are not collected and pytest shows a hint
- `tests/helpers`: shared test helpers (`LightroomCatalogBuilder`: minimal Lightroom catalog)
- `tests/container`: test container with Exempi (prepared, never run, see below)

Run:

```sh
make test                 # uv run pytest
make test-container       # full suite in a container (docker or podman)
uv run pytest --cov=reverse_geolocate --cov-report=term-missing
```

Coverage only shows that every line and branch ran, not that every case is checked.
The points below are cases and environments that are not tested yet.

## 1. Never run

- [ ] **Test container**: `make test-container` was never run (no container tool installed when it was written).
      Check that the image builds (`python:3.14-slim-trixie`, `libexempi8`, uv 0.13),
      Exempi is found and all tests pass. The file permission tests run there (not root).
- [ ] **Linux**: only tested on macOS (APFS, case insensitive). Run the suite on Linux (container or native),
      especially file collection, backups (case sensitive file system) and Unicode (NFC/NFD) tests.
- [ ] **Windows**: never tested. Paths, drive letters (display path, exclude), symlinks, file permissions
      (permission tests are skipped on Windows), Exempi installation.

## 2. External systems, only simulated

- [ ] **Live map lookup tests**: Google and OpenStreetMap are always faked, the response formats are written
      from the API documentation. Add tests marked e.g. `@pytest.mark.live`, skipped by default, run only with
      an API key / email from environment variables. Would catch API format changes.
- [ ] **Real Lightroom catalog**: the tests use a synthetic catalog with the 11 tables/columns of the query.
      A test against a real catalog proves the schema still matches. Needed:
  - a fresh test catalog (`.lrcat`) from the used Lightroom Classic version (note the version)
  - 2-3 images: one with GPS and location fields, one with GPS only, one without both
  - ideally the same file name in two folders (strict mode)
  - the matching `.xmp` sidecar files and their folder paths (the image files are not needed)
- [ ] **Exempi versions**: only the locally installed Exempi was used.

## 3. Cases not tested yet

- [ ] **Lightroom open at the same time**: catalog locked / written by Lightroom while the script reads it
      (read only connection). Could be simulated with a second connection holding a write transaction.
- [ ] **XMP file changed during the run**: e.g. Lightroom writes a sidecar between reading and writing.
      The script writes its version back (last writer wins), check if that is acceptable.
- [ ] **Large folders / performance**: thousands of files with the fuzzy cache (`-d`). Every file is compared
      with every cached location (`LocationCache.get`), so the run gets slower with the cache size.
- [ ] **Mutation testing** (optional, e.g. `mutmut`): shows where asserts are too weak to notice a changed line.

## 4. Open decisions (behaviour only recorded with `NOTE` in the tests)

- [x] **Lightroom GPS 0.0 is "not set"**: fixed (`lightroom_gps` in `utils/lightroom.py`).
      Lightroom GPS is only used as a complete pair: `NULL` is not set, a half pair is not used,
      `0.0` is a valid coordinate (equator, prime meridian), both exactly `0.0` ("Null Island")
      is treated as a placeholder for missing GPS data.
- [ ] **OpenStreetMap vs. Google results** (`tests/unit/test_geolocate.py`):
      OpenStreetMap success leaves `status` empty (Google: `"OK"`), and returns the country code
      in lower case (`jp`, Google: `JP`). Decide if both should be the same (e.g. upper case country code).
- [ ] **Backup names on case sensitive file systems** (`tests/unit/test_backup.py`):
      the name is compared case insensitive, on Linux `A.xmp` and `a.xmp` share the backup numbers
      (a number can be skipped, nothing is overwritten). Probably fine, keep or limit to case insensitive systems.
- [ ] **A backup file given directly with `-i` is processed** (`tests/integration/test_main_file_collection.py`):
      only the folder search skips backups. Skip or warn for directly given backup files too?

## 5. Smaller points seen while testing

- [ ] `--debug` prints the Google API key in full (`### OVERRIDE API: G: ...`): mask it (e.g. `AIza…3xQ`)?
- [ ] Exempi prints `XML parsing failure` itself for a damaged XMP file (C library output, not suppressed).
- [ ] Google returns `status: OK` when results exist but none has a usable type (all fields empty);
      `main()` treats it as failed (no country), only the status is misleading.
- [ ] A file given directly with `-i` is used with any extension (e.g. a `.jpg`), it then fails as damaged XMP.
