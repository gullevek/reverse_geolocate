#!/usr/bin/env bash
# Release: check, set version, format/lint/test, build, commit, tag, push, publish
#
# Default is a dry run: everything is checked, tested and built, but nothing is committed,
# tagged, pushed or published, and pyproject.toml/uv.lock are restored at the end.
# Use --execute for the actual release.
set -euo pipefail

PACKAGE_FILE_NAME="reverse_geolocate"

usage() {
	cat <<EOF
Usage: $0 <new_version> [--execute] [--index <name>]
       $0 --current

  new_version     semantic version, e.g. 2.0.0, 2.1.0-rc.1, 2.1.0-beta.2
                  (pre-releases must be alpha, beta or rc, they are converted to the Python form: 2.1.0rc1)
  --execute       do the actual release, without it this is a dry run (nothing is changed)
  --index <name>  uv index from pyproject.toml to publish to: pypi (default) or test-pypi
  -c, --current   show the current version from pyproject.toml and exit
  -h, --help      show this help
EOF
}
error() {
	echo "[!] $*" >&2
	exit 1
}
step() {
	echo ""
	echo "==> $*"
}

# MARK: arguments
input_version=""
execute=0
index="pypi"
show_current=0
while [ "$#" -gt 0 ]; do
	case "$1" in
		--execute)
			execute=1
			;;
		-c | --current)
			show_current=1
			;;
		--index)
			[ "$#" -ge 2 ] || error "--index needs a value"
			index="$2"
			shift
			;;
		--index=*)
			index="${1#--index=}"
			;;
		-h | --help)
			usage
			exit 0
			;;
		-*)
			usage >&2
			error "Unknown option: $1"
			;;
		*)
			[ -z "$input_version" ] || error "Only one version can be given: '$input_version' and '$1'"
			input_version="$1"
			;;
	esac
	shift
done

# always run from the project folder
cd "$(dirname "$0")"

# MARK: current version
if [ "$show_current" -eq 1 ]; then
	if [ -n "$input_version" ] || [ "$execute" -eq 1 ]; then
		error "--current can not be used with a new version or --execute"
	fi
	for tool in uv jq; do
		command -v "$tool" >/dev/null 2>&1 || error "'$tool' not found"
	done
	uv version --output-format json | jq -r '.version'
	exit 0
fi

if [ -z "$input_version" ]; then
	usage >&2
	exit 1
fi
[ -n "$index" ] || error "--index can not be empty"
if [ "$execute" -eq 1 ]; then
	mode="RELEASE"
else
	mode="DRY RUN"
fi

echo "*** ${mode} ***"

# MARK: check tools
for tool in git uv jq make; do
	command -v "$tool" >/dev/null 2>&1 || error "'$tool' not found"
done

# MARK: check version
step "Check version"
# SemVer 2.0.0 (https://semver.org), bash ERE version of the official regex
semver_regex='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(\.(0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?(\+([0-9a-zA-Z-]+(\.[0-9a-zA-Z-]+)*))?$'
if ! [[ "$input_version" =~ $semver_regex ]]; then
	error "'$input_version' is not a valid semantic version"
fi
# build metadata is a local version in Python, PyPI does not accept those
if [[ "$input_version" == *+* ]]; then
	error "'$input_version': build metadata (+...) can not be published to PyPI"
fi
# also must be a valid Python version: get the normalized form (2.1.0-rc.1 -> 2.1.0rc1)
if ! new_version=$(uv version "$input_version" --dry-run --output-format json 2>/dev/null | jq -r '.version'); then
	error "'$input_version' is not a valid Python version, pre-releases must be alpha, beta or rc (e.g. 2.1.0-rc.1)"
fi
current_version=$(uv version --output-format json | jq -r '.version')
# PEP 440 comparison (pre-release order), packaging is installed with pytest
if ! uv run --no-sync python -c '
import sys
from packaging.version import Version
sys.exit(0 if Version(sys.argv[2]) > Version(sys.argv[1]) else 1)
' "$current_version" "$new_version"; then
	error "New version $new_version must be newer than the current version $current_version"
fi
tag="v${new_version}"
echo "Version: $current_version -> $new_version (tag: $tag, index: $index)"

# MARK: check git
step "Check git"
branch=$(git symbolic-ref --short HEAD 2>/dev/null) || error "Not on a branch (detached HEAD)"
remote=$(git config --get "branch.${branch}.remote") || error "Branch '$branch' has no upstream remote"
if [ -n "$(git status --porcelain)" ]; then
	git status --short
	error "Working tree is not clean, commit or stash all changes first"
fi
git fetch --quiet --tags "$remote"
# not behind the remote branch (ahead is ok, it is pushed with the release)
if [ "$(git rev-list --count "HEAD..@{upstream}")" -ne 0 ]; then
	error "Branch '$branch' is behind '$remote', pull first"
fi
if git rev-parse --quiet --verify "refs/tags/${tag}" >/dev/null; then
	error "Tag $tag already exists"
fi
echo "Branch: $branch, remote: $remote"

# MARK: set version
# until the release commit (dry run: always) restore the version files and remove the build folder
version_set=0
released=0
build_dir=""
cleanup() {
	local status=$?
	if [ -n "$build_dir" ]; then
		rm -rf "$build_dir"
	fi
	if [ "$version_set" -eq 1 ] && [ "$released" -eq 0 ]; then
		if [ "$status" -ne 0 ]; then
			echo "[!] Failed, restoring pyproject.toml and uv.lock" >&2
		else
			echo "Restoring pyproject.toml and uv.lock"
		fi
		git checkout -- pyproject.toml uv.lock
		uv sync --quiet || true
	fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

step "Set version $new_version"
version_set=1
uv version "$new_version"

# MARK: format, lint, test
step "Format check"
make format-check
step "Lint"
make lint-all
# tests on the development Python (.python-version) and on the minimum supported Python (requires-python)
dev_python=$(uv run --no-sync python -c 'import platform; print(platform.python_version())')
min_python=$(make -s min-python)
step "Test on Python ${dev_python} (development version)"
make test
step "Test on Python ${min_python} (minimum supported version)"
make test-min

# MARK: build
step "Build"
build_dir=$(mktemp -d)
uv build --no-sources --out-dir "$build_dir"
wheel="${build_dir}/${PACKAGE_FILE_NAME}-${new_version}-py3-none-any.whl"
sdist="${build_dir}/${PACKAGE_FILE_NAME}-${new_version}.tar.gz"
for file in "$wheel" "$sdist"; do
	[ -s "$file" ] || error "Build file missing: $file"
done
# the installed wheel must run and report the new version
installed_version=$(uv run --isolated --no-project --with "$wheel" reverse-geolocate --version)
if [ "$installed_version" != "reverse-geolocate ${new_version}" ]; then
	error "Built package reports '$installed_version', expected 'reverse-geolocate ${new_version}'"
fi
echo "Build ok: $installed_version"

# MARK: dry run
if [ "$execute" -eq 0 ]; then
	step "[DRY RUN] Push check: $branch to $remote"
	git push --dry-run "$remote" "$branch"
	step "[DRY RUN] Publish check: $index"
	uv publish --dry-run --index "$index" "$wheel" "$sdist" </dev/null
	step "[DRY RUN] Skipped"
	echo "git commit -m \"Release ${new_version}\" (pyproject.toml, uv.lock)"
	echo "git tag -a $tag"
	echo "git push $remote $branch $tag"
	echo "uv publish --index $index ${PACKAGE_FILE_NAME}-${new_version}-py3-none-any.whl ${PACKAGE_FILE_NAME}-${new_version}.tar.gz"
	echo "(the publish check does not verify the credentials)"
	step "[DRY RUN] All checks passed, nothing was changed. Release with:"
	echo "$0 $input_version --execute --index $index"
	exit 0
fi

# MARK: release
# keep the release files in dist/
mkdir -p dist
cp "$wheel" "$sdist" dist/
wheel="dist/$(basename "$wheel")"
sdist="dist/$(basename "$sdist")"

step "Commit and tag $tag"
git add pyproject.toml uv.lock
git commit --quiet -m "Release ${new_version}"
git tag -a "$tag" -m "Release ${new_version}"
released=1

step "Push $branch and $tag to $remote"
git push "$remote" "$branch" "refs/tags/${tag}" ||
	error "Push failed, commit and tag are local. Push: git push $remote $branch $tag, then publish: uv publish --index $index $wheel $sdist"

step "Publish to $index"
uv publish --index "$index" "$wheel" "$sdist" ||
	error "Publish failed, retry with: uv publish --index $index $wheel $sdist"

if [ -n "$(git status --porcelain)" ]; then
	git status --short
	error "Working tree is not clean after the release"
fi

step "Released $new_version ($tag)"
