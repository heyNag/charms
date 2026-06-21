#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skills_root="${HOME}/.claude/skills"
commands_target="${HOME}/.claude/commands"
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
    printf 'managed-by=agent-tools\npackage=%s\nsource=%s\n' "${package}" "${repo_root}/packages/${package}" > "${target}"
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

ensure_managed_file() {
  local target="$1"
  local package="$2"
  local command_marker="agent-tools-managed: ${package} command"
  if [[ ! -e "${target}" ]]; then
    return
  fi
  if grep -Fq "${command_marker}" "${target}" 2>/dev/null; then
    return
  fi
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[dry-run] real install would require FORCE=1 for unmanaged command file: %s\n' "${target}"
    return
  fi
  if [[ "${FORCE:-0}" == "1" ]]; then
    return
  fi

  cat >&2 <<EOF
Refusing to replace existing unmanaged command file:
  ${target}
fix: inspect that file, move it aside, or rerun with FORCE=1 if you really want to replace it.
EOF
  exit 2
}

copy_skill() {
  local package="$1"
  local package_dir="${repo_root}/packages/${package}"
  local skill_target="${skills_root}/${package}"
  local tmp_target="${skill_target}.tmp.$$"

  ensure_managed_dir "${skill_target}"
  run rm -rf "${tmp_target}"
  run mkdir -p "${tmp_target}"
  run cp "${package_dir}/SKILL.md" "${tmp_target}/SKILL.md"
  if [[ -d "${package_dir}/scripts" ]]; then
    run cp -R "${package_dir}/scripts" "${tmp_target}/scripts"
  fi
  if [[ -d "${package_dir}/references" ]]; then
    run cp -R "${package_dir}/references" "${tmp_target}/references"
  fi
  if [[ -d "${package_dir}/agents" ]]; then
    run cp -R "${package_dir}/agents" "${tmp_target}/agents"
  fi
  write_marker "${tmp_target}/${marker_name}" "${package}"
  run rm -rf "${skill_target}"
  run mv "${tmp_target}" "${skill_target}"
}

copy_commands() {
  local package="$1"
  local package_dir="${repo_root}/packages/${package}"
  [[ -d "${package_dir}/commands" ]] || return 0

  run mkdir -p "${commands_target}"
  shopt -s nullglob
  for command_file in "${package_dir}"/commands/*.md; do
    local target="${commands_target}/$(basename "${command_file}")"
    ensure_managed_file "${target}" "${package}"
    run cp "${command_file}" "${target}"
  done
  shopt -u nullglob
}

installed=0
shopt -s nullglob
for tool_json in "${repo_root}"/packages/*/tool.json; do
  if [[ "$(package_has_target "${tool_json}" claude)" != "true" ]]; then
    continue
  fi
  package="$(basename "$(dirname "${tool_json}")")"
  copy_skill "${package}"
  copy_commands "${package}"
  installed=1
  echo "Installed ${package} for Claude:"
  echo "  skill: ${skills_root}/${package}"
  if [[ -d "${repo_root}/packages/${package}/commands" ]]; then
    echo "  commands: ${commands_target}"
  fi
done
shopt -u nullglob

if [[ "${installed}" -eq 0 ]]; then
  echo "No public Claude-target packages found."
fi
