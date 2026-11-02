# Local audio and visual analysis

Use this workflow directly for local file/folder paths when local models are
configured, or when the user chooses local analysis. For YouTube visual/model
analysis with both Gemini and local configured, ask the route once unless it
was already chosen. Reuse that choice for follow-ups; do not ask a Gemini/local
question for local paths or speech-only transcript answers. A separate speech model transcribes the extracted audio; a
vision-language model receives timestamped ASR, sampled frames, and supporting
transcripts. The vision model does not directly hear audio, and this workflow
does not establish tone, speaker identity, or non-speech sounds from ASR alone.

## Set up another Mac

Install or update `watch-video` through your chosen
[installation channel](https://github.com/heyNag/charms/blob/main/docs/installing.md)
first. Marketplace installs use the published release; skill-only channels
follow `main`. Use one channel per host. Run the commands below from the
installed skill directory containing `SKILL.md` and `scripts/`: this is
`skills/watch-video` inside a plugin, or the standalone skill directory. Use
the host's installed skill path rather than a separate checkout or copied scripts.

The user can simply ask **“Set up watch-video on this Mac.”** Start by locating
the installed skill and running its read-only hardware/prerequisite check:

```sh
python3 scripts/setup_local.py --preflight --json
```

It reports the Mac chip, memory, macOS version, app/launcher and dependency
presence, and ordered setup steps without contacting oMLX or a provider. It
works when the app is absent or stopped. Select Splash M1 for detected M1/M2
hardware and official Splash for M3 or later. Unknown hardware or an unsupported
OS needs clarification or another compatible runtime, not a guessed installer.
Python 3.11+ and FFmpeg/ffprobe are required for the local flow; yt-dlp is optional
until a source needs downloading. The credential environment and local.env are
checked for presence only. The checker does not read the file or resolve secrets.

Briefly report what was detected and the next missing step. Reuse existing
choices; ask only for information that cannot be detected or is genuinely a
preference, such as which credential method/item to use or which sample video
to test. If the user wants manual steps, guide one stage at a time instead of
running installers. A setup request permits progressing within the host's
authorization rules; a request to analyze a video does not implicitly authorize
installing runtimes or downloading model weights.

Preflight completion means only that the offline prerequisites were found.
Runtime authentication, model discovery, memory settings, and inference still
need the checks below. Keep the selected model profile across Macs. Use detected
memory and available disk space to explain resource constraints and guide memory
settings, not to silently substitute another model. Do not claim that the model
fits from those values alone. Preserve existing port, model directory, and
runtime choices rather than overwriting them with defaults.

These steps use the same speech and vision models on each Mac. Install the
[native oMLX DMG](https://github.com/jundot/omlx#install), move it to Applications,
and open it once. It includes the app controls, precompiled kernels, and the
`~/.omlx/bin/omlx` CLI; a second Homebrew oMLX installation is unnecessary.

In oMLX, choose `~/.omlx/models` as the primary model directory, bind to
`127.0.0.1`, and set port `8147`. Keep the model files together in that directory;
oMLX manages the layout and presents them to Splash without another download.
Set the memory limit in the app for that Mac. The helper below does not change
server port, authentication, global memory limits, or server lifecycle.

Install a compatible Splash launcher before enabling the external engine:

| Mac | Launcher and installation |
| --- | --- |
| M1 or M2 | `splash-m1`, the community build from [Splash M1 releases](https://github.com/paperniuk/splash/releases); follow that release's `install-m1.sh` instructions and macOS requirements. |
| M3 or newer | Official `splash`: `brew install incoai/tap/splash`; check the [current macOS requirements](https://github.com/incoai/splash) first. |

The selected Qwen family needs Splash 1.3.0 or later. In oMLX, open
**Settings → Integrations → External engines** and confirm the appropriate
launcher is detected, or select its path. Follow the current
[oMLX Splash instructions](https://github.com/jundot/omlx/blob/main/docs/Splash.md)
if the integration reports a missing prerequisite. Splash handles the vision
model; Whisper uses oMLX's local speech endpoint.

The setup helper installs these repositories through oMLX's model downloader:

| Purpose | Repository | API identifier |
| --- | --- | --- |
| Original-audio ASR | `mlx-community/whisper-large-v3-asr-fp16` | `whisper-large-v3-asr-fp16` |
| Frames and text analysis | `mlx-community/Qwen3.6-35B-A3B-4bit` | Alias `mlx-community--Qwen3.6-35B-A3B-4bit` |
| Splash draft for Qwen | `incoai/Qwen3.6-35B-A3B-DFlash2` | Used by the vision model, not selected as an analyzer |

For authentication, guide the user to create or set an API key in oMLX's app.
The client must use the same key; a client configuration file does not set the
server's key. Reuse an existing method if the user already chose one. A secret
manager is optional, not a prerequisite.

The default onboarding creates a protected local template outside the plugin:

```sh
python3 scripts/setup_local.py --init-config
```

This creates `~/.config/watch-video/local.env` with mode `600` and refuses to
overwrite an existing file. `WATCH_VIDEO_CONFIG_DIR` relocates its directory.
Give the user its path and ask them to open it in a plain-text editor, enter the key
from oMLX, and save. Wait for them to finish before checking the connection.
Do not read the clipboard, display the file, or ask for the key in chat. The
template contains these settings, with an empty key for the user to fill:

```dotenv
WATCH_VIDEO_LOCAL_BASE_URL=http://127.0.0.1:8147/v1
WATCH_VIDEO_LOCAL_ASR_MODEL=whisper-large-v3-asr-fp16
WATCH_VIDEO_LOCAL_MODEL=mlx-community--Qwen3.6-35B-A3B-4bit
WATCH_VIDEO_LOCAL_API_KEY=
```

The local scripts automatically load the supported settings from this file;
environment variables override it, and explicit CLI options take precedence.
The parser treats values as data, never shell commands. Keep file permissions
private. Missing or invalid credentials should lead to a local configuration
fix, not disabling authentication. An empty key is appropriate only when the
user has chosen an unauthenticated loopback server.

From the skill directory, start the app-managed server and inspect setup:

```sh
~/.omlx/bin/omlx start
python3 scripts/setup_local.py --check
```

Review the check's proposed changes. When ready to download the weights and
configure Qwen's alias, Splash draft, context window, and idle TTL, run the
explicit setup operation. The target model must be unloaded before settings
can change; use the app to unload it when it is not serving another task.

```sh
python3 scripts/setup_local.py --configure --wait 600
```

If the user prefers a secret manager, inject the same environment variables
instead. For example, a user who chooses 1Password can place a secret reference
in the key field and invoke commands through its CLI:

```sh
op run --env-file ~/.config/watch-video/local.env -- python3 scripts/setup_local.py --check
```

That route needs the user's 1Password CLI integration and approval. An unresolved
`op://` reference is not an API key; ordinary commands reject it and explain the
need for environment injection. The skill never resolves it automatically.

The default model directory is `~/.omlx/models`; `--model-dir` must match oMLX's
configured primary directory. Missing models are queued through the native
downloader, without a Hugging Face CLI or separate model cache. Repeating the
command resumes setup without duplicating active downloads. If the bounded
wait expires, downloads may still be running in oMLX; inspect the app and rerun
setup when they finish. Exit code `2` means setup is still pending; `0` means
ready and `1` means an error. Failed or cancelled downloads need an explicit
retry in the app. The initial vision context is 16,384 tokens with a
300-second idle TTL, adjustable through `--context-window` and `--ttl-seconds`.
`--configure` applies those chosen values even if the model had different ones;
other model settings are preserved.
This setup does not prove inference quality or that all models fit simultaneously.

Verify dependencies and run a short original-audio/frames test before a meeting.
Use an absolute path for `sample.mp4` when it is outside the skill directory.
Keep any matching `sample.txt`, `sample.srt`, or `sample_transcript_grouped.txt`
beside the video so the same test also exercises supplementary transcript
discovery:

```sh
python3 scripts/doctor.py ./sample.mp4 --engine local --transcriber local --analyzer local --check
python3 scripts/watch.py ./sample.mp4 --engine local --transcriber local --analyzer local --duration 30 --detail balanced --frame-format png --resolution 1024 --question "Describe the speech and visible content, and flag uncertainty."
```

Check `local_analysis.json` for complete coverage and review the underlying
evidence. A successful setup check verifies configuration, not transcription or
visual accuracy. Stop a task-owned server afterward with the app or
`~/.omlx/bin/omlx stop`; leave a shared server alone.

## Connect a local runtime

Start the user's configured OpenAI-compatible inference server, such as oMLX,
using its native app or the host's server-management workflow. Analysis commands
do not install a runtime, download model weights, start a server, or modify model
memory settings. Only an explicit `setup_local.py --configure` requests model
downloads and model-specific setup. Reuse the user's configuration and authorization. Local model
identifiers must match what the server exposes; they can differ from repository
names.

| Environment variable | Default or meaning |
| --- | --- |
| `WATCH_VIDEO_LOCAL_BASE_URL` | `http://127.0.0.1:8147/v1` |
| `WATCH_VIDEO_LOCAL_API_KEY` | Required if local server authentication is enabled. Read from the protected local config, or supplied through the user's chosen environment injection. |
| `WATCH_VIDEO_LOCAL_ASR_MODEL` | `whisper-large-v3-asr-fp16` |
| `WATCH_VIDEO_LOCAL_MODEL` | `mlx-community--Qwen3.6-35B-A3B-4bit` |

`--local-model` and `--local-asr-model` override the corresponding environment
variables. `--local-timeout` sets the request timeout in seconds (default 600).
These defaults match the configured oMLX server, including its vision-model
alias. Models can share oMLX's configured model directory; separate Hugging Face
cache storage is not required. Other installations can expose different identifiers. Their model repositories are
`mlx-community/whisper-large-v3-asr-fp16` and
`mlx-community/Qwen3.6-35B-A3B-4bit`. The speech model must return timestamped
segments through `/v1/audio/transcriptions`; the vision model must support image
input through `/v1/chat/completions`. Changing the configured model identifier
does not make an incompatible endpoint or unsupported modality compatible.

The local clients accept only loopback endpoints, reject embedded credentials,
queries and redirects, and ignore proxy environment variables. Do not replace
the URL with a remote or hosted endpoint to work around a local error. There is
no automatic cloud fallback.

Doctor validates the endpoint and reports configuration prerequisites without
contacting the server, checking model availability, or validating the key:

```sh
python3 scripts/doctor.py ./meeting.mp4 --engine local \
  --transcriber local --analyzer local --check
```

## Run the complete local flow

```sh
python3 scripts/watch.py ./meeting.mp4 --engine local \
  --transcriber local --analyzer local --detail full \
  --frame-format png --resolution 1024 \
  --question "Explain the discussion, verify the shared diagrams against speech, and list unresolved points."
```

A folder path processes each supported video recursively with the same choices.
An individual video automatically discovers its neighboring matching TXT/SRT
transcripts. Existing filename matching and source-time rules still apply.
A public URL can use this same explicit local route; downloading it requires
yt-dlp, while processing an existing local video does not.

`--analyzer local` selects local ASR too when `--transcriber` was omitted.
An explicit `--transcriber none` is respected and must be described as a
frames/supplied-text review rather than a fresh audio review.
An explicitly chosen and authorized Groq or OpenAI transcriber also processes
original audio for local analysis, even when native captions cover the video.

`--transcriber local` analyzes original audio even when supplied captions cover
the entire video. The audio is converted to mono 16 kHz PCM WAV and divided into
bounded chunks for local speech recognition. The supplied transcript is not
used to prompt the speech model. Successful segments and failed intervals retain
their provenance. Native captions are retained separately in
`native_captions.json`; they do not fill local ASR gaps. Do not silently repair
uncertain recognition with sidecar
text and then call the result independent ASR. Local ASR supplies speech text,
not a guarantee that recognition is accurate.

`--analyzer local` compares original-audio ASR and selected frames with supplied
transcripts as supplementary evidence. Requests use bounded frame/text batches
and preserve source times. Each image batch has its own exact frame timestamps
and a separate nearby-speech context window. Speech outside those frames is
context, not evidence of what was visible then; unmatched and untimed text is
handled separately without inventing timestamps.

Visual responses must contain one structured observation per supplied frame.
The script validates the frame references and attaches timestamps from the
manifest. Invalid responses remain partial and are not counted as analyzed
coverage. Two consecutive invalid structured responses stop further requests.
This validates references and completeness, not the truth of descriptions.

For bounded inputs, final synthesis receives the original observations and
deduplicated source text directly. Larger inputs use bounded consolidation with
saved evidence ancestry. Speculative batch comparisons are kept in the batch
records for inspection rather than promoted into canonical source evidence.
Every validated visual observation remains in `local_analysis.json` and the
report's frame timeline, even if the prose synthesis misses or contradicts it.
Final findings must cite actual frame/text IDs. The script validates those
references and renders their original timestamps, rather than accepting model
time headings. The report states the first and last retained visual samples;
this span is not continuous coverage. A valid citation does not prove that the
associated claim is true.
Read `local_analysis.md` and `local_analysis.json`, which link the per-batch
results under `local_analysis/`. Complete results with matching request hashes
can be reused when running the standalone analyzer again against the same run
directory; failed or truncated results are not treated as complete.
If the server interrupts a response, the analysis stops with a partial/error
report and preserves completed chunks. After restoring the local server, resume
against the existing run with the same model, question, and configuration:

```sh
python3 scripts/local_analyze.py "<existing-run-dir>"
```

Supply the same credential environment as the original run and omit `--refresh`
to reuse matching completed chunks. This resumes only analysis and synthesis;
it does not repeat audio extraction, ASR, or frame extraction. Review the new
`local_analysis.json` and `local_analysis.md` for completion and coverage; the
original `watch.py` metadata/report is not rewritten by this standalone command.
Inspect recorded coverage, gaps, and truncation; a synthesis cannot recover
evidence omitted or unreadable in earlier stages. Sampled frames do not prove
that every transition or brief event was observed.
`status: complete` means processing completed; `quality.status` remains
`requires_source_review`. Verify consequential conclusions against the frame
observations and underlying media. Recorded `asr_gaps` describe transcription
failures, not ordinary pauses or gaps alleged by the language model.

Local ASR or analysis failure leaves available evidence and returns a nonzero
exit for the partial run; report the failed stage instead of treating the final
summary as complete. A reused ASR result must match the local provider, model,
media identity, and covered range; `--refresh-transcript` requests a fresh pass.

Keep the raw ASR, supporting transcript, frame observations, and model inference
distinct in the answer. Verify exact UI text, tiny toggles, numbers, and claims
that conflict between sources against targeted frames or audio. Supplied TXT
speaker names are not independently verified speaker recognition. Do not claim
word-level timing from grouped TXT blocks or infer timings for untimed text.

For speech-only tasks, omit the visual analyzer and use `--detail transcript`.
If a supplied transcript alone answers the question, local ASR is optional;
when original audio was explicitly requested, a sidecar does not replace it.

Keep runtime/model unloading under the user's app or supervisor controls.
Do not stop a shared server that was already running for another project.
