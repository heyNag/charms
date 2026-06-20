#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="${1:-watch-video}"
SRC="$ROOT/packages/$PACKAGE"
PLUGIN="$ROOT/generated/claude/plugins/$PACKAGE"
CODEX="$ROOT/generated/codex/skills/$PACKAGE"

fail() {
  echo "error: $*" >&2
  exit 1
}

check_same_file() {
  local source_file="$1"
  local generated_file="$2"
  [[ -f "$source_file" ]] || fail "missing source file: ${source_file#$ROOT/}"
  [[ -f "$generated_file" ]] || fail "missing generated file: ${generated_file#$ROOT/}"
  if ! python3 - "$ROOT" "$source_file" "$generated_file" <<'PY'
import pathlib
import sys

BEGIN = "BEGIN GENERATED FROM SOURCE"
END = "END GENERATED FROM SOURCE"


def strip_notice(text: str, suffix: str) -> str:
    lines = text.splitlines(keepends=True)
    if suffix == ".md":
        starts = [0]
        if text.startswith("---\n"):
            marker = text.find("\n---\n", 4)
            if marker != -1:
                starts.append(marker + len("\n---\n"))
        for start in starts:
            line_index = len(text[:start].splitlines())
            if start == 0:
                line_index = 0
            if line_index < len(lines) and lines[line_index].startswith(f"<!-- {BEGIN}:"):
                end_index = None
                for index in range(line_index, min(len(lines), line_index + 6)):
                    if lines[index].startswith(f"<!-- {END}"):
                        end_index = index
                        break
                if end_index is not None:
                    remainder = lines[:line_index] + lines[end_index + 1 :]
                    if len(remainder) > line_index and remainder[line_index].strip() == "":
                        del remainder[line_index]
                    return "".join(remainder)
    if suffix == ".py":
        start_index = 1 if lines and lines[0].startswith("#!") else 0
        if len(lines) > start_index and lines[start_index].startswith(f"# {BEGIN}:"):
            end_index = None
            for index in range(start_index, min(len(lines), start_index + 6)):
                if lines[index].startswith(f"# {END}"):
                    end_index = index
                    break
            if end_index is not None:
                remainder = lines[:start_index] + lines[end_index + 1 :]
                if len(remainder) > start_index and remainder[start_index].strip() == "":
                    del remainder[start_index]
                return "".join(remainder)
    return text


def has_notice(text: str, suffix: str) -> bool:
    return strip_notice(text, suffix) != text


root = pathlib.Path(sys.argv[1])
source = pathlib.Path(sys.argv[2])
generated = pathlib.Path(sys.argv[3])
source_text = source.read_text(encoding="utf-8")
raw_generated_text = generated.read_text(encoding="utf-8")
if generated.suffix in {".md", ".py"} and not has_notice(raw_generated_text, generated.suffix):
    print(f"missing generated notice: {generated.relative_to(root)}", file=sys.stderr)
    raise SystemExit(1)
generated_text = strip_notice(raw_generated_text, generated.suffix)
if source_text != generated_text:
    raise SystemExit(1)
PY
  then
    echo "mismatch: ${generated_file#$ROOT/} differs from ${source_file#$ROOT/}" >&2
    return 1
  fi
}

check_same_dir() {
  local source_dir="$1"
  local generated_dir="$2"
  [[ -d "$source_dir" ]] || return 0
  [[ -d "$generated_dir" ]] || fail "missing generated directory: ${generated_dir#$ROOT/}"
  python3 - "$ROOT" "$source_dir" "$generated_dir" <<'PY'
import filecmp
import pathlib
import sys

BEGIN = "BEGIN GENERATED FROM SOURCE"
END = "END GENERATED FROM SOURCE"
root = pathlib.Path(sys.argv[1])
source_dir = pathlib.Path(sys.argv[2])
generated_dir = pathlib.Path(sys.argv[3])
ignored_dirs = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def files_under(directory: pathlib.Path) -> dict[str, pathlib.Path]:
    files: dict[str, pathlib.Path] = {}
    for path in directory.rglob("*"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if path.is_file():
            files[str(path.relative_to(directory))] = path
    return files


def strip_notice(text: str, suffix: str) -> str:
    lines = text.splitlines(keepends=True)
    if suffix == ".md":
        starts = [0]
        if text.startswith("---\n"):
            marker = text.find("\n---\n", 4)
            if marker != -1:
                starts.append(marker + len("\n---\n"))
        for start in starts:
            line_index = len(text[:start].splitlines())
            if start == 0:
                line_index = 0
            if line_index < len(lines) and lines[line_index].startswith(f"<!-- {BEGIN}:"):
                end_index = None
                for index in range(line_index, min(len(lines), line_index + 6)):
                    if lines[index].startswith(f"<!-- {END}"):
                        end_index = index
                        break
                if end_index is not None:
                    remainder = lines[:line_index] + lines[end_index + 1 :]
                    if len(remainder) > line_index and remainder[line_index].strip() == "":
                        del remainder[line_index]
                    return "".join(remainder)
    if suffix == ".py":
        start_index = 1 if lines and lines[0].startswith("#!") else 0
        if len(lines) > start_index and lines[start_index].startswith(f"# {BEGIN}:"):
            end_index = None
            for index in range(start_index, min(len(lines), start_index + 6)):
                if lines[index].startswith(f"# {END}"):
                    end_index = index
                    break
            if end_index is not None:
                remainder = lines[:start_index] + lines[end_index + 1 :]
                if len(remainder) > start_index and remainder[start_index].strip() == "":
                    del remainder[start_index]
                return "".join(remainder)
    return text


def has_notice(text: str, suffix: str) -> bool:
    return strip_notice(text, suffix) != text


source_files = files_under(source_dir)
generated_files = files_under(generated_dir)
errors: list[str] = []

for rel in sorted(set(source_files) - set(generated_files)):
    errors.append(f"missing generated file: {generated_dir.relative_to(root) / rel}")
for rel in sorted(set(generated_files) - set(source_files)):
    errors.append(f"unexpected generated file: {generated_dir.relative_to(root) / rel}")
for rel in sorted(set(source_files) & set(generated_files)):
    if source_files[rel].suffix in {".md", ".py"}:
        source_text = source_files[rel].read_text(encoding="utf-8")
        raw_generated_text = generated_files[rel].read_text(encoding="utf-8")
        if not has_notice(raw_generated_text, generated_files[rel].suffix):
            errors.append(f"missing generated notice: {generated_dir.relative_to(root) / rel}")
            continue
        generated_text = strip_notice(raw_generated_text, generated_files[rel].suffix)
        same = source_text == generated_text
    else:
        same = filecmp.cmp(source_files[rel], generated_files[rel], shallow=False)
    if not same:
        errors.append(
            f"mismatch: {generated_dir.relative_to(root) / rel} differs from "
            f"{source_dir.relative_to(root) / rel}"
        )

if errors:
    for error in errors:
        print(error, file=sys.stderr)
    raise SystemExit(1)
PY
}

[[ -d "$SRC" ]] || fail "missing source package: packages/$PACKAGE"

status=0

[[ -f "$ROOT/.claude-plugin/GENERATED.md" ]] || {
  echo "missing generated marker: .claude-plugin/GENERATED.md" >&2
  status=1
}
[[ -f "$ROOT/.claude-plugin/marketplace.json" ]] || {
  echo "missing generated marketplace: .claude-plugin/marketplace.json" >&2
  status=1
}

check_same_file "$SRC/README.md" "$CODEX/README.md" || status=1
check_same_file "$SRC/SKILL.md" "$CODEX/SKILL.md" || status=1
check_same_dir "$SRC/scripts" "$CODEX/scripts" || status=1
[[ -f "$CODEX/GENERATED.md" ]] || {
  echo "missing generated marker: generated/codex/skills/$PACKAGE/GENERATED.md" >&2
  status=1
}

check_same_file "$SRC/README.md" "$PLUGIN/README.md" || status=1
check_same_file "$SRC/SKILL.md" "$PLUGIN/skills/$PACKAGE/SKILL.md" || status=1
check_same_file "$SRC/plugin/plugin.json" "$PLUGIN/.claude-plugin/plugin.json" || status=1
check_same_dir "$SRC/scripts" "$PLUGIN/skills/$PACKAGE/scripts" || status=1
check_same_dir "$SRC/commands" "$PLUGIN/commands" || status=1
[[ -f "$PLUGIN/GENERATED.md" ]] || {
  echo "missing generated marker: generated/claude/plugins/$PACKAGE/GENERATED.md" >&2
  status=1
}

if [[ "$status" -ne 0 ]]; then
  echo "generated outputs are out of sync; run make rebuild-generated" >&2
  exit "$status"
fi

echo "generated outputs match packages/$PACKAGE"
