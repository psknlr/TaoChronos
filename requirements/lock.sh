#!/usr/bin/env bash
# Regenerates the hashed lockfiles from pyproject.toml (requirements/README.md).  Needs uv (https://docs.astral.sh/uv/).
# Every file is universal (Linux, macOS, Windows; Python 3.11 and up) and pins every package, with the sha256 of every
# file of it on PyPI, so `pip install --require-hashes -r requirements/<file>.txt` installs exactly these.
#   requirements/lock.sh                  after a change to pyproject.toml or constraints.in: the pins kept where they still fit
#   requirements/lock.sh --upgrade        every package re-resolved to the newest release the ranges and constraints.in allow
#   requirements/lock.sh --upgrade NAME…  only the packages named (a pin an advisory names: `filelock`, or to one release:
#                                         `pypdf==6.21.4`), to the newest release allowed; every other pin kept
#   requirements/lock.sh --check          fails if a lockfile does not match pyproject.toml and constraints.in (changes nothing)
set -euo pipefail
cd "$(dirname "$0")/.."
mode=keep
named=()  # --upgrade NAME…: uv's --upgrade-package for each
case "${1:-}" in
  "") ;;
  --upgrade)
    shift
    if [ $# -eq 0 ]; then mode=upgrade; else for package in "$@"; do named+=(--upgrade-package "$package"); done; fi ;;
  --check) mode=check ;;
  *) echo "usage: requirements/lock.sh [--upgrade [NAME…] | --check]" >&2; exit 2 ;;
esac
export UV_CUSTOM_COMPILE_COMMAND="requirements/lock.sh"
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT

lock() { # name, then the sources and extras uv pip compile takes
  local name=$1; shift
  # an existing output file is uv's preference: its pins stay unless they no longer satisfy the ranges
  if [ "$mode" != upgrade ] && [ -f "requirements/$name.txt" ]; then cp "requirements/$name.txt" "$out/$name.txt"; fi
  uv pip compile --quiet --universal --python-version 3.11 --generate-hashes --no-strip-markers \
    --constraint requirements/constraints.in ${named[@]+"${named[@]}"} --output-file "$out/$name.txt" "$@"
  if [ "$mode" = check ]; then
    diff -u "requirements/$name.txt" "$out/$name.txt" || { echo "requirements/$name.txt is out of date: run requirements/lock.sh" >&2; return 1; }
  else
    cp "$out/$name.txt" "requirements/$name.txt"
  fi
}

lock runtime pyproject.toml                                        # the package itself: the image, the site's build, the workflows
lock build requirements/build.in                                   # what builds it (pyproject.toml's [build-system])
lock dev pyproject.toml --extra dev --extra anthropic              # the tests, as CI runs them
lock litellm pyproject.toml --extra litellm                        # the LiteLLM provider
lock ingest pyproject.toml --extra pdf --extra parquet             # the PDF and Parquet corpus ingesters
lock audit requirements/audit.in                                   # pip-audit, for the audit workflow
lock native requirements/native.in                                 # maturin, which builds TaoCore's extension (rust/)
if [ "$mode" = check ]; then echo "the lockfiles match pyproject.toml"; else echo "requirements/*.txt written"; fi
