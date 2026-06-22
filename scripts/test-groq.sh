#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${GROQ_API_KEY:-}" ]]; then
  echo "GROQ_API_KEY is not set."
  echo "fix: export GROQ_API_KEY=..."
  exit 2
fi

if [[ $# -ne 1 ]]; then
  echo "usage: $0 path/to/audio.mp3"
  exit 2
fi

audio_file="$1"
if [[ ! -f "${audio_file}" ]]; then
  echo "audio file not found: ${audio_file}"
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_json="$(mktemp -t watch-video-groq.XXXXXX.json)"
trap 'rm -f "${tmp_json}"' EXIT

python3 "${repo_root}/packages/watch-video/skills/watch-video/scripts/groq_transcribe.py" \
  "${audio_file}" \
  --out "${tmp_json}" \
  --model "${GROQ_MODEL:-whisper-large-v3-turbo}" \
  --quiet

if command -v jq >/dev/null 2>&1; then
  jq . "${tmp_json}"
else
  cat "${tmp_json}"
fi
