# Options and evidence

The detail behind [SKILL.md](../SKILL.md): the flags of `watch.py` and
`doctor.py`, credentials, how captions, transcripts and frames are chosen, and
where runs are kept. Whether a run may upload anything is decided by
[Uploads need consent](../SKILL.md#uploads-need-consent), and nothing here
widens that rule. [Local models](local-models.md) covers the local speech and
vision models.

## Local controls

- `--detail transcript|efficient|balanced|full` sets how many images are
  sampled; SKILL.md describes the levels.
- `--mode general|tutorial|ui-bug|notes` selects a report scaffold.
- `--transcriber local|groq|openai|none` selects original-audio local ASR or
  hosted fallback. Without a local analyzer, the CLI defaults to none for every
  source, including fresh URLs. Groq and OpenAI upload the audio, so they come
  under the consent rule; a configured key is not consent.
- `--analyzer local` analyzes extracted frames and transcript evidence through a
  local vision-language model; it defaults an omitted transcriber to local.
  An explicit `--transcriber none` remains respected. The default analyzer
  `none` prepares evidence for the host.
- `--start`, `--end`, or `--duration` selects a range. End and duration are
  mutually exclusive; cue timestamps remain absolute source times.
- `--timestamps` pins images at absolute source times, separated by commas.
  Cues use the frame budget first; if too many are requested, an evenly spaced
  subset is retained.
- `--max-frames` overrides the cap: up to 100 normally, 300 for full scene/cue
  output. Uniform sampling and its fallbacks stay capped at 100 even in full.
- `--resolution` (alias `--frame-width`) and `--frame-format jpeg|png|webp`
  control images. `--no-dedup` retains similar candidates; `--no-frames` skips
  images.
- `--frame-mode interval --frame-interval SECONDS`, or `--fps`, forces uniform
  sampling at up to 2 fps. Explicit rates stop at the cap; read coverage warnings
  when the later part of the range is uncovered.
- `--sub-langs` selects captions; for example `"es,es.*"` for Spanish.
- `--max-download-duration TIME` is the longest span a URL run downloads
  (default 4:00:00). A longer source is refused before any download: select a
  range, use `--detail transcript`, or raise it when the user wants the whole
  recording.
- `--js-runtime node|quickjs|bun` lets yt-dlp run YouTube's player JavaScript
  in a runtime it leaves off by default. yt-dlp needs a JavaScript runtime for
  full YouTube support and enables only Deno by itself, so Deno needs no flag.
  Pass it only when doctor reports no usable runtime and the user agrees.
- `--process-timeout SECONDS` limits each yt-dlp or FFmpeg step (default 1800),
  so a stalled download ends with a message instead of holding the run open.
  A step that passes it is stopped and reported. Narrow the range first; raise
  the limit only for a step that is known to be slow.
- `--from-run DIR` and `--refresh-transcript` reuse an earlier run; see
  [Reusing a run](#reusing-a-run).
- `--out-dir`, `--cleanup` and `--cleanup-frames` are described under
  [Run folders and cleanup](#run-folders-and-cleanup).
- `--question` records the task with local evidence for the host agent.
- `--version` prints the plugin version.
- Spell every flag in full. Abbreviations such as `--det` are rejected.

## Doctor

Match doctor's source and engine to the intended run. Local files need FFmpeg
and ffprobe; fresh local URL runs also need yt-dlp. Doctor defaults to local;
without a source or `--from-run` it checks the full local toolkit, even with
`--engine gemini`.
Use `--json` for structured results. When reusing media, pass the same
`--from-run "<prior-run-dir>"` to doctor so it skips the downloader check.
Doctor checks dependencies, not source accessibility or cache validity. Pass
`--transcriber local --analyzer local` for local-model configuration checks;
these validate the loopback URL without contacting the server or loading models.
Its Gemini key check is advisory and presence-only; it does not validate access
or quota.

## Captions and transcription

The script probes URL captions first and judges their coverage inside the
requested range. Hosted transcription is opt-in for every source: without
`--transcriber groq` or `openai`, no audio is uploaded, whatever keys exist.
When captions leave speech uncovered and no transcriber was chosen, the report
warns and names the flags that would add it. A chosen transcriber downloads
audio for a transcript-only run; finite local-engine URL ranges download only
that section. Local files discover VTT/SRT sidecars. Audio is extracted when
transcription is needed. Explicit `--transcriber local` requests fresh
original-audio ASR even when captions are available, unless a matching complete
local ASR result is reused.

## Supplied transcripts

Local runs also discover exact neighboring `.txt` and `.srt` names. For
`meeting.mp4`, match `meeting`, `meeting_transcript`, or
`meeting_transcript_grouped` with either extension.
Matches are saved separately in `supporting_transcripts.json` and referenced
in run metadata and the evidence manifest. SRT retains explicit cue start and
end times; TXT retains timestamped speaker blocks or untimed text, without
invented end times. These supporting records are separate from native-caption
and ASR coverage. Existing VTT/SRT caption support remains available: an SRT
appearing in both `transcript.json` and `supporting_transcripts.json` is the
same supplied source, not independent corroboration. A matched local SRT does
not bypass explicitly selected local or authorized hosted ASR; a complete saved
ASR result may still be reused, and `--transcriber none` still disables ASR.

## Frame selection

Scene/keyframe candidates use RGB thumbnail dedup before thinning to their
cap; uniform sampling applies its rate/cap before dedup. Color-only changes
survive RGB comparison, but small text changes can still be missed. Scene
selection reserves at most one quarter of its remaining budget, no more than
20 frames, for coarse checks of long gaps. These `coverage` images and pinned
`transcript-cue` images survive dedup. This is not exhaustive event detection.

Sampled image timestamps come from decoded source frames. Cue records include
both requested and actual decoded times. Use the actual `timestamp_seconds`
in `evidence.json` for citations; filenames and display labels round to seconds.

## Reusing a run

`--from-run` reuses retained media/captions and a complete saved ASR transcript
covering the new range, avoiding another transcription request.
`--refresh-transcript` bypasses that ASR cache; it does not force hosted
transcription when native captions suffice. An explicit local transcriber still
reviews original audio; use refresh to bypass its ASR cache. Source/media
identity must match. Runs without usable media and trimmed URL downloads are
rejected; rerun the original source in those cases. An audio-only run cannot
supply new visual frames.

## Hosted transcription

Both providers receive the audio, so use them only with the user's consent for
that source.

- Groq: `GROQ_API_KEY`; default model `whisper-large-v3`, overridden by
  `GROQ_MODEL`. Use `GROQ_MODEL=whisper-large-v3-turbo` for the faster option.
- OpenAI: `OPENAI_API_KEY`; default `whisper-1`, overridden by
  `OPENAI_TRANSCRIBE_MODEL`. Timestamped segments are required.
- Where the user's credential policy permits local storage,
  `python3 scripts/doctor.py --set-key groq` or `--set-key openai` reads stdin
  and writes `~/.config/watch-video/.env` with mode 600. `WATCH_VIDEO_CONFIG_DIR`
  relocates it; environment values win. This helper does not store Gemini keys.

The CLI never selects a hosted transcriber itself, and a selected one without
its key stops the run before anything is downloaded.

Hosted fallback audio above **24,000,000 bytes (decimal 24 MB)** is chunked. Actual
chunk and multipart sizes are checked before upload. Partial failures preserve
successful segments and record failed or skipped intervals as `gaps`. Provider
access failures and exhausted rate-limit retries stop remaining uploads.
Available native captions fill those intervals with their provenance; the failed
ASR coverage remains marked. `no_speech` means a valid completed empty response,
not failed or missing transcription. Do not infer speech or invent timestamps in
gaps.

## Gemini settings

`GEMINI_API_KEY` must be supplied in the environment; it is not loaded from the
stored transcription-key file. Supported YouTube URLs and local files need no
local binaries; other URLs need yt-dlp, FFmpeg, and ffprobe for downloading.
The model defaults to `gemini-3.8-flash`, with
`--gemini-model` or `WATCH_VIDEO_GEMINI_MODEL` overrides. Analysis timeout is
600 seconds by default (`--gemini-timeout`); upload/processing has a separate
900-second deadline (`--gemini-upload-timeout`). Answers are limited to 8,192
tokens (`--gemini-max-output-tokens`).

Supported YouTube URLs go directly to Google. Local videos are uploaded;
non-YouTube URLs are downloaded then uploaded. Even a focused request uploads
the complete local/downloaded file. Whole-video analysis uses agentic
processing; explicit ranges use static processing with source-time offsets.
Local-only extraction, transcription, and reuse flags are rejected for Gemini.
The adapter refuses redirects and attempts deletion of known uploaded files;
check recorded cleanup warnings/file identifiers if deletion fails.

## Run folders and cleanup

Run artifacts live outside the plugin under `WATCH_VIDEO_RUNS_DIR`, otherwise
`$XDG_STATE_HOME/watch-video/runs/` or `~/.local/state/watch-video/runs/`.
`--out-dir` overrides the base. New run folders are private to the current
user (mode 700). Keep media while follow-ups need it.
`--cleanup` removes downloaded media and generated audio/chunks;
`--cleanup-frames` additionally removes images. Reports, transcripts, and the
local evidence manifest remain, with availability updated. Delete the run
directory to remove everything. Never put private run artifacts in a repository.

Directory runs process videos sequentially, skip symbolic-link files and
directories, and exclude audio-only files. Each video gets its own run under
the selected output base; a batch report indexes successes and failures, and a
per-video failure does not stop the remaining files.

Old runs are not removed on their own. `python3 scripts/doctor.py --prune`
lists the run folders unchanged for 7 days with their sizes and deletes
nothing; `--older-than 12h`, `3d` or `2w` changes the age. Show the list to the
user and add `--delete` only after they agree. It removes only folders it
recognises as watch-video runs, and takes `--out-dir` for runs written
somewhere else.

## Network endpoints

Local downloads use `yt-dlp --ignore-config`. Groq sends fallback audio to
`api.groq.com`; OpenAI sends it to `api.openai.com`; both refuse redirects.
Gemini requests use `generativelanguage.googleapis.com`, with validated upload
URLs and refused redirects. The local engine's name refers to evidence
extraction: an explicitly selected hosted transcriber still sends audio off
the machine.
`--transcriber local` and `--analyzer local` use only the configured loopback
endpoint, refuse redirects, and ignore proxy environment variables. They do
not install models, start a server, or choose a cloud fallback. The separate
`setup_local.py --configure` helper uses oMLX's native downloader and configures
the local vision model only when setup is explicitly requested.
