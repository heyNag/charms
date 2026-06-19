#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_dir="${repo_root}/packages/watch-video"
skill_target="${HOME}/.codex/skills/watch-video"
legacy_skill_target="${HOME}/.codex/skills/watch-video"
marker_name=".agent-tools-managed"

run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

write_marker() {
  local target="$1"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[dry-run] write managed marker %q\n' "${target}"
  else
    printf 'managed-by=agent-tools\npackage=watch-video\nsource=%s\n' "${repo_root}" > "${target}"
  fi
}

if [[ -e "${skill_target}" && ! -f "${skill_target}/${marker_name}" && "${FORCE:-0}" != "1" ]]; then
  cat >&2 <<EOF
Refusing to replace existing unmanaged directory:
  ${skill_target}
fix: inspect that directory, move it aside, or rerun with FORCE=1 if you really want to replace it.
EOF
  exit 2
fi

if [[ "${legacy_skill_target}" != "${skill_target}" && -f "${legacy_skill_target}/${marker_name}" ]]; then
  run rm -rf "${legacy_skill_target}"
fi

tmp_target="${skill_target}.tmp.$$"

run rm -rf "${tmp_target}"
run mkdir -p "${tmp_target}"
run cp "${package_dir}/SKILL.md" "${tmp_target}/SKILL.md"
run cp -R "${package_dir}/scripts" "${tmp_target}/scripts"
write_marker "${tmp_target}/${marker_name}"
run rm -rf "${skill_target}"
run mv "${tmp_target}" "${skill_target}"

echo "Installed watch-video for Codex:"
echo "  skill: ${skill_target}"
