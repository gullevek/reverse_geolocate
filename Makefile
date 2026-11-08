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
