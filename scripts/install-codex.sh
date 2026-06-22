#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skills_root="${HOME}/.codex/skills"
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

package_has_target() {
  local tool_json="$1"
  local target="$2"
  python3 - "$tool_json" "$target" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
targets = data.get("targets") or []
print("true" if data.get("public") is True and sys.argv[2] in targets else "false")
PY
}

write_marker() {
  local target="$1"
  local package="$2"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[dry-run] write managed marker %q\n' "${target}"
  else
    printf 'managed-by=agent-tools\npackage=%s\nsource=%s\n' "${package}" "${repo_root}/packages/${package}/skills/${package}" > "${target}"
  fi
}

ensure_managed_dir() {
  local target="$1"
  if [[ ! -e "${target}" ]]; then
    return
  fi
  if [[ -f "${target}/${marker_name}" ]]; then
    return
  fi
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[dry-run] real install would require FORCE=1 for unmanaged directory: %s\n' "${target}"
    return
  fi
  if [[ "${FORCE:-0}" == "1" ]]; then
    return
  fi

  cat >&2 <<EOF
Refusing to replace existing unmanaged directory:
  ${target}
fix: inspect that directory, move it aside, or rerun with FORCE=1 if you really want to replace it.
EOF
  exit 2
}

copy_skill() {
  local package="$1"
  local package_dir="${repo_root}/packages/${package}"
  local source_skill="${package_dir}/skills/${package}"
  local skill_target="${skills_root}/${package}"
  local tmp_target="${skill_target}.tmp.$$"

  [[ -f "${source_skill}/SKILL.md" ]] || {
    echo "error: missing source skill: ${source_skill}/SKILL.md" >&2
    exit 1
  }

  ensure_managed_dir "${skill_target}"
  run rm -rf "${tmp_target}"
  run mkdir -p "${tmp_target}"
  run cp -R "${source_skill}/." "${tmp_target}/"
  write_marker "${tmp_target}/${marker_name}" "${package}"
  run rm -rf "${skill_target}"
  run mv "${tmp_target}" "${skill_target}"
}

installed=0
shopt -s nullglob
for tool_json in "${repo_root}"/packages/*/tool.json; do
  if [[ "$(package_has_target "${tool_json}" codex)" != "true" ]]; then
    continue
  fi
  package="$(basename "$(dirname "${tool_json}")")"
  copy_skill "${package}"
  installed=1
  echo "Installed ${package} for Codex:"
  echo "  skill: ${skills_root}/${package}"
done
shopt -u nullglob

if [[ "${installed}" -eq 0 ]]; then
  echo "No public Codex-target packages found."
fi
