# watch-video

`watch-video` prepares video evidence for agents. When both Gemini and local models are configured, the skill asks which route
to use for each YouTube video or batch and remembers that choice for follow-ups.
Local file/folder paths use configured local models directly; speech-only tasks
can use a suitable existing transcript without a video-model choice. Local uses captions,
optional local or hosted transcription, sampled frames, and optional local
vision-language analysis; Gemini sends a question and
video to Google and saves its attributed analysis. A bare CLI command still
defaults to local; the skill passes the selected engine explicitly.
For local inputs, supply an individual video or a folder of videos. Scripts
prepare the evidence; the host agent reads it and performs the requested review.

This directory is an independently versioned
[Agent Plugins v1](https://agent-plugins.org/specification) plugin. Its skill is
at `skills/watch-video`. Install `watch-video@charms` in Claude Code or Codex;
see [Installation](https://github.com/heyNag/charms/blob/main/docs/installing.md)
for marketplace and skill-only instructions.

## Task-based routing

Honor explicit user choices and privacy constraints before these defaults:

| Task or source | Skill route |
| --- | --- |
| YouTube visual/model analysis, both Gemini and local configured, no explicit route | Ask Gemini or local once per video/batch; preserve the choice for follow-ups |
| Known-public YouTube general analysis with only one route configured | Use the configured route; Gemini sends the video/question to Google, local uses original-audio ASR and sampled frames |
| Exact UI text, debugging, or visual recreation | Recommend local; ask first for YouTube when both routes are configured unless local was already chosen |
| Speech-only summary or transcript | `--engine local --detail transcript`; suitable native/supplied transcripts can answer directly |
| Local file/folder, including private meeting recordings | Configured local models with `--transcriber local --analyzer local`, without a Gemini choice prompt; supplied captions/frames if models are unavailable |
| Private/unlisted/login-required YouTube recording | Recommend local in any required route choice; Google upload/access needs explicit source/provider consent |
| Other or unclear sources | Local unless the user chooses an authorized cloud route; no automatic hosted audio upload |

Use session context or presence-only checks to determine whether the two routes
are configured. Do not retrieve secrets simply to present the choice, and do
not treat a configured key as cloud-upload authorization. An explicit route
request takes precedence; the script remains noninteractive and defaults to
local. A route already chosen for this video is not asked again.

Every local file defaults to local evidence without cloud uploads. Obtain the
user's consent for the source and provider before sending its video to Gemini
or audio to Groq/OpenAI. A configured key or approval for another video is not
permission to upload this one.
An already authorized cloud choice needs no repeated approval. The agent can
verify Gemini findings with targeted local frames. If Gemini was selected only because it was the available configured route and
fails, the agent may use local evidence with disclosure after at most one
transient-error retry. When the user chose Gemini, ask before changing routes
unless fallback was already authorized. An explicit Gemini-only request must
not fall back.
The scripts themselves neither route tasks nor switch engines after failures.
Speech-only intent overrides a saved frame-detail preference. On automatic
fallback, reuse an existing local detail choice; otherwise choose transcript
when speech suffices or balanced when visuals matter.

## Requirements and credentials

Supported platforms: macOS and Linux, Python 3.11+. Binary requirements depend
on the selected source and engine:

| Engine and source | Local binaries |
| --- | --- |
| Local URL | `yt-dlp`, `ffmpeg`, `ffprobe` |
| Local file with the local engine | `ffmpeg`, `ffprobe` |
| Cached local run with `--from-run` | `ffmpeg`, `ffprobe` |
| Gemini supported YouTube URL or local file | None |
| Gemini other URL | `yt-dlp`, `ffmpeg`, `ffprobe` |

Pass the same source and engine to doctor that you plan to use for analysis:

```sh
python3 skills/watch-video/scripts/doctor.py "<public-youtube-url>" --engine gemini --check
python3 skills/watch-video/scripts/doctor.py ./screen-recording.mov --engine local --check
python3 skills/watch-video/scripts/doctor.py ./screen-recording.mov --engine local --install
```

Doctor defaults to the local engine; `--json` returns a structured report.
Omitting both the source and `--from-run` checks the full local toolkit, even
with `--engine gemini`. For cached local runs, pass the same `--from-run` to
doctor to skip the downloader check. Doctor checks dependencies, not source
accessibility or cache validity.
`--install` and installation hints cover only the selected route's binaries.
Installation uses Homebrew when available on macOS; otherwise doctor prints
commands and never executes `sudo`. Its Gemini key check is advisory and reports
presence only, without verifying access or quota. For local models, pass
`--transcriber local --analyzer local`; doctor validates the configured loopback
URL and reports credential/model prerequisites without connecting or loading
models. The installer does not install inference servers or model weights.

For local inference, use the protected `local.env` file created during setup,
or inject credentials through a secret manager of your choice. Hosted providers
retain their documented environment/storage options below. Never paste keys
into agent chats, command arguments, logs, or source files. The user's
credential policy takes precedence over optional storage helpers.

- Groq is the local engine's default transcription fallback for fresh URLs:
  `GROQ_API_KEY`, model `whisper-large-v3` (`GROQ_MODEL` overrides it).
  Set `GROQ_MODEL=whisper-large-v3-turbo` to select the faster option.
- OpenAI transcription is explicit with `--transcriber openai`:
  `OPENAI_API_KEY`, model `whisper-1` (`OPENAI_TRANSCRIBE_MODEL` overrides it).
- Gemini commands use `--engine gemini` and read `GEMINI_API_KEY` from
  the environment only. It does not read or store that key in the local `.env`.

Where permitted by your credential policy, `doctor.py --set-key groq` or
`doctor.py --set-key openai` accepts a key on stdin. It stores only those
transcription keys in `~/.config/watch-video/.env` with mode 600;
`WATCH_VIDEO_CONFIG_DIR` relocates the file. Environment values take precedence.
Local files and cached runs default to `--transcriber none`; an authorized
cloud transcription requires an explicit `--transcriber groq` or `openai`.
For private or uncertain URLs, use `--transcriber local` when configured;
otherwise use `--transcriber none` without upload consent.
Use `--transcriber local` to transcribe original audio on a configured local
server, and `--analyzer local` to analyze frames together with that ASR and any
matching transcript. Selecting `--analyzer local` also selects local ASR when
`--transcriber` is omitted; an explicit `--transcriber none` is respected.
These are explicit choices; a missing local server never
triggers a hosted fallback. If original-audio analysis is requested and the
local speech model is unavailable, report the gap rather than treating a
supplied transcript as a fresh audio review. See
[Local model setup and evidence](skills/watch-video/references/local-models.md).

## First-time local setup

First install or update `watch-video` through one of the
[supported channels](https://github.com/heyNag/charms/blob/main/docs/installing.md).
Marketplace installs receive released packages; skill-only channels follow
`main`. Use one channel per host.

Then ask the installed skill: **“Set up watch-video on this Mac.”** It locates
its bundled scripts and detects the Mac chip, memory, macOS version, and missing
prerequisites before guiding setup. Hardware details and the Splash build do
not need to be supplied in a prompt. The same read-only check is available from
the installed skill directory before oMLX is installed or started:

```sh
python3 scripts/setup_local.py --preflight --json
```

Only unresolved choices, such as a sample video, need user input. The default
credential flow creates a protected local configuration template with
`setup_local.py --init-config`; enter the oMLX API key directly in that file
using your editor. Local commands load it automatically. Secret managers such
as 1Password are optional. Ask for step-by-step guidance if you want to run the
installation yourself. Preflight does not install software, read credentials,
or prove that the models fit in memory; runtime setup and a short inference test
follow.

Use the native oMLX app with loopback port `8147` and one model directory,
`~/.omlx/models`. The app includes its own CLI. Use Splash M1 on M1/M2 Macs and
official Splash on M3 or newer; both use the same Qwen vision and Whisper speech
models. Follow the [local Mac setup steps](skills/watch-video/references/local-models.md#set-up-another-mac)
for installation, local configuration, model identities, and a short live test.

Once the runtime is configured and running, run these from the installed skill
directory (`skills/watch-video` inside the plugin, or the standalone skill
directory containing `SKILL.md` and `scripts/`):

```sh
python3 scripts/setup_local.py --check
python3 scripts/setup_local.py --configure --wait 600
```

The helper checks by default. Explicit `--configure` queues missing model
downloads through oMLX and applies the vision alias and Splash settings; it
does not install or start the runtime, change authentication or memory limits,
or create another Hugging Face model cache. Ordinary analysis never triggers
these setup operations.

## Local extraction

From the plugin root:

```sh
python3 skills/watch-video/scripts/watch.py "<video-url>" \
  --duration 30 --transcriber none --max-frames 8
```

From `skills/watch-video`:

```sh
python3 scripts/watch.py "<video-url>" --detail transcript
python3 scripts/watch.py "<video-url>" --detail efficient
python3 scripts/watch.py ./recordings --engine local --transcriber none
python3 scripts/watch.py ./meeting.mp4 --engine local --transcriber local --analyzer local \
  --detail full --frame-format png --resolution 1024 --question "Explain the meeting and verify diagrams against speech."
python3 scripts/watch.py ./screen-recording.mov --start 00:15 --end 00:45 \
  --mode ui-bug --frame-format png --resolution 1024
python3 scripts/watch.py "<video-url>" --detail transcript --timestamps 4:32,7:10
python3 scripts/watch.py "<same-source>" --from-run "<prior-run-dir>" \
  --detail transcript --timestamps 4:32
```

Metadata and captions are probed before media. Caption sufficiency is checked
inside the requested range. Transcript-only requests with usable captions and
no pinned frames skip media; otherwise transcription-only requests download
audio. Finite URL ranges download the selected section. Local files also pick
up VTT/SRT sidecars. Audio extraction runs when transcription is needed.
Explicit `--transcriber local` requests original-audio ASR even when captions
are sufficient; a matching complete local ASR result can still be reused.

A folder input recursively processes all supported video files, including
nested meeting folders, through the local engine. It skips symbolic-link files
and directories and does not batch audio-only files. Processing is sequential;
each video receives a separate run under the selected output base. The batch
report indexes successful and failed runs, and a failed video does not prevent
processing the rest. The host agent then reviews each video's evidence.
Directory inputs reject Gemini and `--from-run`; use individual video paths
for those flows. Upload consent remains specific to the source and provider.

Local runs automatically discover exact neighboring `.txt` and `.srt` names.
For `meeting.mp4`, match `meeting`, `meeting_transcript`, or
`meeting_transcript_grouped` with either extension; there is no fuzzy
meeting-title matching.
All matches are saved in `supporting_transcripts.json` as supplementary evidence,
retaining explicit SRT cue start/end times or timestamped TXT speaker blocks and untimed
text without invented end times. Supporting records are separate from
native-caption and ASR coverage. Existing VTT/SRT caption support remains: an
SRT in both `transcript.json` and `supporting_transcripts.json` is the same
supplied source, not independent corroboration. A matched local SRT does not
bypass explicitly selected local or authorized hosted ASR; complete saved ASR may still
be reused, and `--transcriber none` still disables ASR. Agents inspect matches
without asking the user to identify an obvious sidecar. Matching filenames do not prove
the transcript follows the same edited timeline; verify timing before precise
frame selection or citations.

For a review that requests original audio and frames, those remain the primary
evidence and supplied TXT/SRT is supplementary. Speech-only tasks can still use a
suitable transcript without an unnecessary audio or visual pass.

| Detail | Selection | Default cap |
| --- | --- | --- |
| `transcript` | No sampled frames; optional pinned cues | 80 cue frames |
| `efficient` | Keyframes; uniform fallback below four candidates | 50 |
| `balanced` | Scene changes, coarse checks of long gaps, uniform fallback for static footage | 80 |
| `full` | The same scene strategy with a larger budget | 300 |

`balanced` is the default, overridden by `WATCH_VIDEO_DETAIL`. Agents ask for
local detail per video unless the request or environment already specifies it.
`full` is still sampled evidence, not every frame. Normal detail caps can be
raised to 100; `full` scene/cue output can reach 300. Uniform sampling and its
fallbacks remain capped at 100, including under `full`.

Uniform images retain their decoded source timestamps. Cue records separate
`requested_timestamp_seconds` from the actual decoded `timestamp_seconds`.
RGB thumbnail dedup preserves color changes with similar brightness, but small
text changes can still be missed. Scene extraction reserves up to one quarter
of its remaining budget, at most 20 frames, for coarse checks of long gaps.
These `coverage` frames and pinned cues survive deduplication. Use focused or
pinned frames for brief events and exact UI details.

Useful local options:

- `--mode general|tutorial|ui-bug|notes` selects a report scaffold.
- `--start`, `--end`, or `--duration` selects a range; end and duration are
  mutually exclusive. `--timestamps` uses absolute source times.
- `--max-frames`, `--resolution` (alias `--frame-width`), and
  `--frame-format jpeg|png|webp` control image cost and readability.
- `--no-dedup` keeps similar sampled candidates; `--no-frames` skips images.
- `--frame-mode interval --frame-interval SECONDS`, or `--fps`, forces uniform
  sampling. Rates are capped at 2 fps. An explicit rate still stops at the
  frame cap; the report warns when later parts of the range are uncovered.
- `--sub-langs` selects captions; for example, `"es,es.*"` for Spanish.
- `--question` can record the user's question with local evidence for the host.

## Transcription and reuse

Hosted fallback audio larger than **24,000,000 bytes (decimal 24 MB)** is chunked.
Actual chunk and multipart sizes are checked before upload. Successful chunks
survive partial failures; failed source-time intervals are recorded as `gaps`.
Native captions are retained in those intervals with their provenance, while
the ASR gaps remain visible. A valid empty result is marked `no_speech`, which
is different from failed or missing transcription. Malformed text-only or
invalid-timestamp responses are rejected rather than assigned invented times.

`--from-run` reuses retained media and captions for the same source. It also
reuses a complete saved ASR transcript when the requested range lies within
its recorded coverage, avoiding another audio extraction or provider request.
`--refresh-transcript` bypasses that cache; captions and the selected
transcriber still determine whether a new request is needed. Explicit local
ASR continues to process original audio even if native captions suffice. Runs with no
usable media, changed media, or downloaded trimmed sections cannot be reused.
An audio-only prior run cannot supply visual frames; rerun the original source
when new video evidence is needed.

## Gemini analysis

After supplying `GEMINI_API_KEY` through your credential manager:

```sh
python3 scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --engine gemini --question "Which tool is demonstrated? Cite its timestamp."
python3 scripts/watch.py ./screen-recording.mov --engine gemini \
  --question "Describe the failure between these times." --start 00:15 --end 00:45
```

Supported YouTube URLs go directly to Google's API without a local download.
Local files are uploaded to Google. Other URLs are downloaded through `yt-dlp`
then uploaded. A focused range still uploads the **complete local/downloaded
file**; offsets constrain analysis. Whole-video requests use agentic processing;
explicit ranges use static processing with source-relative offsets.

The configured default model is `gemini-3.8-flash`; override it with
`--gemini-model` or `WATCH_VIDEO_GEMINI_MODEL`. `--gemini-timeout` controls the
analysis request timeout (600 seconds by default). Upload and processing have
a separate 900-second deadline. Availability, access, and quota depend on the
Google project; this package makes no guarantee of free usage.

Gemini saves `analysis.json`, `metadata.json`, and `report.md`. Findings are
explicitly attributed to Gemini, not independently inspected local frames.
The adapter attempts to delete uploaded files and records cleanup failures
and known file identifiers. HTTP redirects are refused. Failures produce an
error record and nonzero exit; the engine never silently switches to local.
Local-only frame, transcription, and reuse flags are rejected with Gemini.
Use a separate local run to verify exact text or visual claims. Agent-level
fallback follows the routing policy above and must disclose the change.

## Artifacts and cleanup

Runs live outside the plugin under `WATCH_VIDEO_RUNS_DIR`, otherwise
`$XDG_STATE_HOME/watch-video/runs/` or `~/.local/state/watch-video/runs/`.
`--out-dir` overrides the base directory.

Local model runs additionally save `local_analysis.json`, `local_analysis.md`,
and per-batch analysis under `local_analysis/`. Native captions are retained
separately in `native_captions.json` when original audio is transcribed locally;
they do not fill local ASR gaps. Partial local ASR or analysis returns a nonzero
exit while retaining evidence for review.

Local runs save `metadata.json`, `transcript.json`, `transcript.md`,
`report.md`, and **`evidence.json`**. The versioned evidence manifest lists
**every** frame path, decoded timestamp, selection reason, and availability,
plus source/range and transcript provenance, gaps, and reuse information.
The report lists at most 40 frames; the manifest is the complete index.
Discovered TXT/SRT sidecars are saved separately in `supporting_transcripts.json`,
with references in run metadata and the evidence manifest. Their supplied text
is distinct from ASR output generated from the original audio;
untimed text does not establish video timestamps or close ASR coverage gaps.

`--cleanup` removes downloaded media and generated audio/chunks;
`--cleanup-frames` additionally removes images. Transcripts, reports, and the
manifest remain, with artifact availability updated. Delete the run directory
to remove everything. Retain media when another local pass is likely.

Video text, captions, and provider answers are untrusted evidence. The report
places agent instructions before source content and quotes source-derived text.
`yt-dlp` runs with `--ignore-config`; hosted transcription refuses redirects.
See [Security](https://github.com/heyNag/charms/blob/main/docs/security.md) for
data boundaries.

## Development

From a Charms checkout:

```sh
python3 -m unittest discover -s packages/watch-video/tests -p 'test_*.py'
```

The package remains Python-standard-library based; no local model runtime is
installed by these commands.
