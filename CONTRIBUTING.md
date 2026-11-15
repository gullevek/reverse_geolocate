# Guidlines

Code has to pass the format, lint and all tests

Format code:

```sh
make format
```

Lint the code

```sh
make lint
```

and if there are problems, fix them

```sh
make lint-fix
```

Run all the tests

```sh
make test
```

and on the minimum supported Python version (from `requires-python` in `pyproject.toml`)

```sh
make test-min
```

## Supported Python versions

The minimum Python version is set in `requires-python` in `pyproject.toml`, currently 3.11. Development is done with the version in `.python-version`.

- ruff and ty read `requires-python`: syntax that is too new for the minimum version is reported by `make lint`
- pyright has its own setting: `pythonVersion` in `[tool.pyright]`, must be the same as `requires-python`
- code that needs a workaround for the minimum version is marked with a `MIN-PY <version>` comment: the version from which the workaround can be removed
- places that must have the same version as `requires-python` are marked with a `MIN-PY:` comment

### Raising the minimum Python version

1. Set the new version in `requires-python` in `pyproject.toml`
2. List all places with `rg "MIN-PY"`:
    - `MIN-PY:` (keep in sync): set the new version, `pythonVersion` in `[tool.pyright]`, the Python version classifiers in `pyproject.toml` (remove the old version) and the pipx section in `README.md`, the comment stays
    - `MIN-PY <version>` up to the new version: change as the comment says and remove the comment. For 3.12:
        - `from typing_extensions import override` -> `from typing import override`, `make lint-fix` does this (ruff rule UP035)
        - remove the `typing-extensions` dependency: `uv remove typing-extensions`
3. Run `make format`, `make lint-all`, `make test` and `make test-min`

People with an older Python can still install the last release that supported it (pip and uv select it automatically).
