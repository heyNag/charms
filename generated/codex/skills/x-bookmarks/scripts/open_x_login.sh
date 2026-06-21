#!/bin/sh
# BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/scripts/open_x_login.sh
# Do not edit directly; edit the source path and run make rebuild-generated.
# END GENERATED FROM SOURCE

set -eu

url="${1:-https://x.com}"

case "$(uname -s)" in
  Darwin)
    exec /usr/bin/open "$url"
    ;;
  Linux)
    if command -v xdg-open >/dev/null 2>&1; then
      exec xdg-open "$url"
    fi
    ;;
esac

printf '%s\n' "$url"
printf '%s\n' "fix: open the URL above in a browser where you use X, then sign in to x.com" >&2
exit 1
