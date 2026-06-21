#!/usr/bin/env bash
# BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/scripts/fetch_bookmarks_bird.sh
# Do not edit directly; edit the source path and run make rebuild-generated.
# END GENERATED FROM SOURCE

# Fetch X bookmarks via Bird and output JSON.

set -euo pipefail

if ! command -v bird >/dev/null 2>&1; then
  printf '%s\n' 'error: bird is not installed' >&2
  printf '%s\n' 'fix: install Bird from https://bird.fast/ or use your managed toolchain' >&2
  exit 127
fi

cmd=(bird bookmarks --json --plain)

if [[ $# -eq 0 ]]; then
  cmd+=(-n 25)
else
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --count)
        [[ $# -ge 2 ]] || {
          printf '%s\n' 'error: --count requires a value' >&2
          exit 2
        }
        cmd+=(-n "$2")
        shift 2
        ;;
      --count=*)
        cmd+=(-n "${1#--count=}")
        shift
        ;;
      *)
        cmd+=("$1")
        shift
        ;;
    esac
  done
fi

exec "${cmd[@]}"
