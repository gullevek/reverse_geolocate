default:

# Makefile
format-check:
	uv run ruff format --check
format:
	uv run ruff format

lint:
	uv run ruff check
	uv run ty check

lint-all:
	uv run ruff check
	uv run ty check
	uv run pyright

lint-ruff:
	uv run ruff check

lint-ty:
	uv run ty check

lint-pyright:
	uv run pyright

lint-fix:
	uv run ruff check --fix
	uv run ty check --fix

lint-fix-ruff:
	uv run ruff check --fix

lint-fix-ty:
	uv run ty check --fix

test:
	uv run pytest

# MARK: test container
# full test suite in a container with the Exempi library (needed for the integration tests)
# docker or podman, the first one found, override with: make test-container CONTAINER=podman
# pytest arguments: make test-container TEST_ARGS="-x tests/integration"
CONTAINER ?= $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null)
CONTAINER_IMAGE ?= reverse-geolocate-test
CONTAINER_FILE = tests/container/Containerfile
TEST_ARGS ?=

test-container-build:
	@if [ -z "$(CONTAINER)" ]; then \
		echo "No container tool found: install docker or podman, or set CONTAINER=<tool>"; \
		exit 1; \
	fi
	$(CONTAINER) build --file $(CONTAINER_FILE) --tag $(CONTAINER_IMAGE) .

test-container: test-container-build
	$(CONTAINER) run --rm $(CONTAINER_IMAGE) $(TEST_ARGS)

.PHONY: default format-check format lint lint-all lint-ruff lint-ty lint-pyright lint-fix lint-fix-ruff lint-fix-ty test test-container-build test-container
