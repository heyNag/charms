#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_dir="${repo_root}/packages/watch-video"
skill_target="${HOME}/.claude/skills/watch-video"
legacy_skill_target="${HOME}/.claude/skills/watch-video"
commands_target="${HOME}/.claude/commands"
marker_name=".agent-tools-managed"
command_marker="agent-tools-managed: watch-video command"
legacy_command_marker="agent-tools-managed: watch-video command"

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

ensure_managed_dir() {
  local target="$1"
  if [[ ! -e "${target}" ]]; then
    return
  fi
  if [[ -f "${target}/${marker_name}" ]]; then
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
  if [[ ! -e "${target}" ]]; then
    return
  fi
  if grep -Fq "${command_marker}" "${target}" 2>/dev/null; then
    return
  fi
  if grep -Fq "${legacy_command_marker}" "${target}" 2>/dev/null; then
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
  local tmp_target
  tmp_target="${skill_target}.tmp.$$"

  ensure_managed_dir "${skill_target}"
  run rm -rf "${tmp_target}"
  run mkdir -p "${tmp_target}"
  run cp "${package_dir}/SKILL.md" "${tmp_target}/SKILL.md"
  run cp -R "${package_dir}/scripts" "${tmp_target}/scripts"
  write_marker "${tmp_target}/${marker_name}"
  run rm -rf "${skill_target}"
  run mv "${tmp_target}" "${skill_target}"
}

remove_legacy_skill() {
  if [[ "${legacy_skill_target}" == "${skill_target}" ]]; then
    return
  fi
  if [[ -f "${legacy_skill_target}/${marker_name}" ]]; then
    run rm -rf "${legacy_skill_target}"
  fi
}

copy_commands() {
  run mkdir -p "${commands_target}"
  for command_file in "${package_dir}"/commands/*.md; do
    ensure_managed_file "${commands_target}/$(basename "${command_file}")"
    run cp "${command_file}" "${commands_target}/$(basename "${command_file}")"
  done
}

remove_legacy_skill
copy_skill
copy_commands

echo "Installed watch-video for Claude:"
echo "  skill: ${skill_target}"
echo "  commands: ${commands_target}"
