"""YouTube needs a JavaScript runtime in yt-dlp: doctor reports it, watch.py passes the opt-in."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))
sys.path.insert(0, str(TESTS_DIR))

import doctor  # noqa: E402
import network_guard  # noqa: E402
import timed_process  # noqa: E402
import unittest_backports  # noqa: E402, F401
import watch  # noqa: E402


YOUTUBE = "https://www.youtube.com/watch?v=qSuCPooR3E4"
OTHER_URL = "https://example.com/recording.mp4"
LOCAL_VIDEO = "/tmp/watch-video-fixture.mp4"
READY = {"runtimes": "deno-2.9.8", "libraries": "certifi-2026.10.23, yt_dlp_ejs-0.8.0"}
# Copied from yt-dlp 2026.10.26.
NO_RUNTIME_WARNING = (
    "WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by "
    "default; to use another runtime add  --js-runtimes RUNTIME[:PATH]  to your command/config. "
    "YouTube extraction without a JS runtime has been deprecated, and some formats may be missing. "
    "See  https://github.com/yt-dlp/yt-dlp/wiki/EJS  for details on installing one"
)
NO_SCRIPTS_WARNING = (
    "WARNING: [youtube] [jsc] Remote component challenge solver script (deno) was skipped. "
    "It may be required to solve JS challenges. You can enable the download with  "
    "--remote-components ejs:github  (recommended). For more information and alternatives, "
    "refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS"
)
DEBUG_HEADER = """[debug] Command-line config: ['--ignore-config', '--verbose']
[debug] yt-dlp version stable@2026.10.26 from yt-dlp/yt-dlp [c91f8de0b] (pip)
[debug] exe versions: ffmpeg 6.1.1 (setts), ffprobe 6.1.1
[debug] Optional libraries: certifi-2026.10.23, sqlite3-3.53.1, yt_dlp_ejs-0.8.0
[debug] JS runtimes: deno-2.9.8
[debug] Proxy map: {}

Usage: yt-dlp [OPTIONS] URL [URL...]

yt-dlp: error: You must provide at least one URL.
"""


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def installed(*names: str):
    """A shutil.which that finds only the named programs."""
    return lambda name: f"/fixture/{name}" if name in names else None


class RoutingTests(unittest.TestCase):
    def test_the_runtime_matters_only_where_yt_dlp_reads_youtube(self) -> None:
        cases = [
            (("local", YOUTUBE, None), True),
            (("local", "https://youtu.be/qSuCPooR3E4", None), True),
            (("local", "https://music.youtube.com/watch?v=qSuCPooR3E4", None), True),
            (("local", "https://www.youtube-nocookie.com/embed/qSuCPooR3E4", None), True),
            (("local", "https://www.youtube.com/playlist?list=PL123", None), True),
            # No source is the full toolkit check, whatever the engine.
            (("local", None, None), True),
            (("gemini", None, None), True),
            # Gemini reads YouTube itself; other sites have no such player.
            (("gemini", YOUTUBE, None), False),
            (("gemini", OTHER_URL, None), False),
            (("local", OTHER_URL, None), False),
            (("local", "https://www.youtube.com.example.com/watch?v=qSuCPooR3E4", None), False),
            (("local", "https://notyoutube.com/watch?v=qSuCPooR3E4", None), False),
            (("local", LOCAL_VIDEO, None), False),
            (("local", YOUTUBE, "/tmp/watch-video-prior-run"), False),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertIs(doctor.needs_js_runtime(*arguments), expected)

    def test_the_check_is_advisory(self) -> None:
        # Captions and some formats still work without a runtime, so --check
        # must not stop a run over it.
        self.assertIn("js-runtime", doctor.ADVISORY_CHECKS)


class SelfReportTests(unittest.TestCase):
    def report(self, completed=None, failure=None, **kwargs):
        with mock.patch.object(
            doctor.subprocess, "run", return_value=completed, side_effect=failure,
        ) as run:
            return doctor.yt_dlp_self_report(**kwargs), run

    def test_yt_dlp_is_asked_without_a_url_or_the_users_config(self) -> None:
        completed = subprocess.CompletedProcess(["yt-dlp"], 2, "", DEBUG_HEADER)
        report, run = self.report(completed)

        self.assertEqual(report, {
            "runtimes": "deno-2.9.8",
            "libraries": "certifi-2026.10.23, sqlite3-3.53.1, yt_dlp_ejs-0.8.0",
        })
        command = run.call_args.args[0]
        self.assertEqual(command, ["yt-dlp", "--ignore-config", "--verbose"])
        self.assertFalse(any("://" in argument for argument in command))
        self.assertEqual(run.call_args.kwargs["timeout"], doctor.YT_DLP_REPORT_TIMEOUT)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_an_opted_in_runtime_is_part_of_the_question(self) -> None:
        completed = subprocess.CompletedProcess(["yt-dlp"], 2, "[debug] JS runtimes: node-22.23.4\n", "")
        report, run = self.report(completed, js_runtime="node")

        self.assertEqual(report, {"runtimes": "node-22.23.4"})
        self.assertEqual(
            run.call_args.args[0], ["yt-dlp", "--ignore-config", "--verbose", "--js-runtimes", "node"],
        )

    def test_a_yt_dlp_that_cannot_answer_reads_as_unknown(self) -> None:
        old = subprocess.CompletedProcess(["yt-dlp"], 2, "", "[debug] yt-dlp version 2024.01.01\n")
        self.assertEqual(self.report(old)[0], {})
        for failure in (FileNotFoundError("yt-dlp"), subprocess.TimeoutExpired(["yt-dlp"], 20)):
            with self.subTest(failure=type(failure).__name__):
                self.assertIsNone(self.report(failure=failure)[0])


class CheckTests(unittest.TestCase):
    def check(self, report, *programs: str, platform: str = "macOS", js_runtime=None):
        with mock.patch.object(doctor, "yt_dlp_self_report", return_value=report) as ask, \
                mock.patch.object(doctor.shutil, "which", side_effect=installed("yt-dlp", *programs)), \
                mock.patch.object(doctor, "current_platform", return_value=platform):
            result = doctor.check_js_runtime(js_runtime)
        ask.assert_called_once_with(js_runtime)
        return result

    def test_a_runtime_with_its_solver_scripts_passes(self) -> None:
        result = self.check(READY)

        self.assertEqual(
            result, {"name": "js-runtime", "ok": True, "problem": None,
                     "message": "deno-2.9.8 (reported by yt-dlp)"},
        )

    def test_nothing_is_asked_before_yt_dlp_is_installed(self) -> None:
        with mock.patch.object(doctor, "yt_dlp_self_report") as ask, \
                mock.patch.object(doctor.shutil, "which", return_value=None):
            result = doctor.check_js_runtime()

        ask.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "not checked until yt-dlp is installed")

    def test_a_yt_dlp_that_cannot_answer_is_not_reported_as_broken(self) -> None:
        for report in (None, {}, {"libraries": "yt_dlp_ejs-0.8.0"}):
            with self.subTest(report=report):
                result = self.check(report)
                self.assertTrue(result["ok"])
                self.assertIn("not checked", result["message"])

    def test_no_runtime_at_all_names_the_install_for_the_platform(self) -> None:
        mac = self.check({"runtimes": "none", "libraries": ""})
        self.assertFalse(mac["ok"])
        self.assertEqual(mac["problem"], "runtime")
        self.assertEqual(
            mac["message"],
            "yt-dlp found no JavaScript runtime, so YouTube formats may be missing or downloads may fail",
        )
        self.assertEqual(mac["fix"], "brew install deno")

        linux = self.check({"runtimes": "none", "libraries": ""}, platform="Linux")
        self.assertIn("pipx inject yt-dlp deno", linux["fix"])
        self.assertIn(doctor.DENO_INSTALL_PAGE, linux["fix"])
        self.assertNotIn("--js-runtime", linux["fix"])
        self.assertNotIn("curl", linux["fix"])

    def test_a_runtime_yt_dlp_leaves_off_is_offered_as_the_users_choice(self) -> None:
        result = self.check({"runtimes": "none", "libraries": ""}, "node", "bun")

        self.assertEqual(result["problem"], "runtime")
        self.assertIn("enables only Deno by itself", result["message"])
        self.assertIn("leaves node, bun off for security reasons", result["message"])
        self.assertTrue(result["fix"].startswith("brew install deno; or, when the user agrees,"))
        self.assertIn("--js-runtime node (or WATCH_VIDEO_JS_RUNTIME=node)", result["fix"])

    def test_quickjs_is_found_by_its_program_name(self) -> None:
        result = self.check({"runtimes": "none", "libraries": ""}, "qjs")
        self.assertIn("--js-runtime quickjs", result["fix"])

    def test_a_selected_runtime_yt_dlp_cannot_use_is_reported(self) -> None:
        missing = self.check({"runtimes": "none"}, js_runtime="node")
        self.assertEqual(missing["problem"], "runtime")
        self.assertTrue(missing["message"].startswith("yt-dlp could not use the selected runtime node, so"))

        old = self.check({"runtimes": "node-18.0.0 (unsupported)"}, "node", js_runtime="node")
        self.assertIn("yt-dlp reported node-18.0.0 (unsupported)", old["message"])
        # The selected runtime is not offered again as the way out.
        self.assertEqual(old["fix"], "brew install deno")

    def test_runtimes_yt_dlp_rejects_do_not_count(self) -> None:
        for listed in ("deno-1.40.0 (unsupported)", "deno (unknown)", "none (disabled)"):
            with self.subTest(listed=listed):
                result = self.check({"runtimes": listed, "libraries": "yt_dlp_ejs-0.8.0"})
                self.assertFalse(result["ok"])
                self.assertEqual(result["problem"], "runtime")
        rejected = self.check({"runtimes": "deno-1.40.0 (unsupported)"})
        self.assertTrue(rejected["message"].startswith("yt-dlp cannot use deno-1.40.0 (unsupported), so"))

    def test_a_runtime_without_the_solver_scripts_is_a_different_fix(self) -> None:
        result = self.check({"runtimes": "deno-2.9.8", "libraries": "certifi-2026.10.23, sqlite3-3.53.1"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["problem"], "scripts")
        self.assertIn("without its challenge solver scripts (yt-dlp-ejs)", result["message"])
        self.assertIn('pipx install --force "yt-dlp[default,deno]"', result["fix"])
        self.assertNotIn("brew install deno", result["fix"])

    def test_the_linux_install_hint_brings_the_scripts_and_a_runtime(self) -> None:
        self.assertEqual(
            doctor.install_hints(["yt-dlp", "ffmpeg"])["Linux"],
            ["sudo apt install ffmpeg", 'pipx install "yt-dlp[default,deno]"'],
        )


class DoctorCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        for function, name in (
            ("check_platform", "platform"), ("check_python_version", "python"),
            ("check_gemini_key", "GEMINI_API_KEY"), ("check_config_file", "whisper-config"),
            ("check_run_artifacts", "run-artifacts"), ("check_run_privacy", "run-privacy"),
            ("check_env_local", ".env.local"),
        ):
            self.enterContext(mock.patch.object(
                doctor, function, return_value={"name": name, "ok": True, "message": "fixture"},
            ))
        self.enterContext(mock.patch.object(
            doctor, "check_whisper_key",
            side_effect=lambda provider: {"name": f"{provider.upper()}_API_KEY", "ok": True, "message": "fixture"},
        ))
        self.platform = self.enterContext(mock.patch.object(doctor, "current_platform", return_value="macOS"))
        self.programs = {"yt-dlp", "ffmpeg", "ffprobe", "brew"}
        self.enterContext(mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: f"/fixture/{name}" if name in self.programs else None,
        ))
        self.reports: list[dict[str, str] | None] = [{"runtimes": "none", "libraries": ""}]
        self.asked: list[str | None] = []

        def report(js_runtime=None):
            self.asked.append(js_runtime)
            return self.reports[0] if len(self.reports) == 1 else self.reports.pop(0)

        self.enterContext(mock.patch.object(doctor, "yt_dlp_self_report", side_effect=report))
        self.brew = self.enterContext(mock.patch.object(
            doctor.subprocess, "run", return_value=subprocess.CompletedProcess(["brew"], 0),
        ))

    def cli(self, *args: str):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["doctor.py", *args]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = doctor.main()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_a_missing_runtime_is_shown_but_does_not_fail_the_check(self) -> None:
        code, output, errors = self.cli(YOUTUBE, "--check")
        self.assertEqual((code, output, errors), (0, "", ""))

        code, output, _ = self.cli(YOUTUBE)
        self.assertEqual(code, 0)
        self.assertIn("- warn: js-runtime - yt-dlp found no JavaScript runtime", output)
        self.assertIn("  fix: brew install deno", output)

        code, output, _ = self.cli(YOUTUBE, "--json")
        status = json.loads(output)
        self.assertEqual(code, 0)
        self.assertTrue(status["ok"])
        check = next(item for item in status["checks"] if item["name"] == "js-runtime")
        self.assertEqual((check["ok"], check["problem"]), (False, "runtime"))

    def test_other_sources_are_not_asked_about_a_runtime(self) -> None:
        for arguments in ((OTHER_URL,), (LOCAL_VIDEO,), (YOUTUBE, "--engine", "gemini"),
                          (YOUTUBE, "--from-run", "/tmp/watch-video-prior-run")):
            with self.subTest(arguments=arguments):
                code, output, _ = self.cli(*arguments, "--json")
                self.assertEqual(code, 0)
                names = [item["name"] for item in json.loads(output)["checks"]]
                self.assertNotIn("js-runtime", names)
        self.assertEqual(self.asked, [])

    def test_the_selected_runtime_comes_from_the_flag_or_the_environment(self) -> None:
        self.cli(YOUTUBE, "--js-runtime", "node")
        with mock.patch.dict(os.environ, {watch.JS_RUNTIME_ENV: "bun"}):
            self.cli(YOUTUBE)
            self.cli(YOUTUBE, "--js-runtime", "quickjs")
        with mock.patch.dict(os.environ, {watch.JS_RUNTIME_ENV: "deno"}):
            self.cli(YOUTUBE)
        self.assertEqual(self.asked, ["node", "bun", "quickjs", None])

        with mock.patch.dict(os.environ, {watch.JS_RUNTIME_ENV: "python"}):
            code, _, errors = self.cli(YOUTUBE)
        self.assertEqual(code, 2)
        self.assertIn("WATCH_VIDEO_JS_RUNTIME must be one of: node, quickjs, bun", errors)
        code, _, errors = self.cli(YOUTUBE, "--js-runtime", "deno")
        self.assertEqual(code, 2)

    def test_install_adds_deno_for_a_yt_dlp_that_has_no_runtime(self) -> None:
        self.reports = [{"runtimes": "none", "libraries": ""}, READY]

        code, output, _ = self.cli(YOUTUBE, "--install")

        self.assertEqual(code, 0)
        self.assertEqual(self.brew.call_args.args[0], ["brew", "install", "deno"])
        self.assertIn("installed via brew: deno", output)

    def test_install_reports_a_runtime_that_is_still_unusable(self) -> None:
        code, output, _ = self.cli(YOUTUBE, "--install")

        self.assertEqual(code, 2)
        self.brew.assert_called_once()
        self.assertIn("yt-dlp found no JavaScript runtime", output)
        self.assertIn("  fix: brew install deno", output)

    def test_install_does_not_guess_how_to_reinstall_yt_dlp(self) -> None:
        self.reports = [{"runtimes": "deno-2.9.8", "libraries": ""}]

        code, output, _ = self.cli(YOUTUBE, "--install")

        self.assertEqual(code, 2)
        self.brew.assert_not_called()
        self.assertIn("without its challenge solver scripts", output)
        self.assertIn('  fix: install yt-dlp with its default extras', output)

    def test_install_prints_the_runtime_fix_where_there_is_no_homebrew(self) -> None:
        self.platform.return_value = "Linux"

        code, output, _ = self.cli(YOUTUBE, "--install")

        self.assertEqual(code, 2)
        self.brew.assert_not_called()
        self.assertIn("pipx inject yt-dlp deno", output)

    def test_install_asks_the_freshly_installed_yt_dlp(self) -> None:
        self.programs.discard("yt-dlp")
        self.reports = [READY]

        def install(command, **_kwargs):
            self.assertEqual(command, ["brew", "install", "yt-dlp"])
            self.assertEqual(self.asked, [], "asked before yt-dlp existed")
            self.programs.add("yt-dlp")
            return subprocess.CompletedProcess(command, 0)

        self.brew.side_effect = install
        code, output, _ = self.cli(YOUTUBE, "--install")

        self.assertEqual(code, 0)
        self.assertEqual(self.asked, [None])
        self.assertIn("installed via brew: yt-dlp", output)

    def test_install_has_nothing_to_do_when_yt_dlp_is_ready(self) -> None:
        self.reports = [READY]

        code, output, _ = self.cli(YOUTUBE, "--install")

        self.assertEqual((code, output), (0, "all required binaries are already installed\n"))
        self.brew.assert_not_called()

    def test_install_for_another_site_never_asks_about_a_runtime(self) -> None:
        code, output, _ = self.cli(OTHER_URL, "--install")

        self.assertEqual((code, output), (0, "all required binaries are already installed\n"))
        self.assertEqual(self.asked, [])


class WatchOptInTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.addCleanup(timed_process.configure, None)
        self.enterContext(mock.patch.dict(os.environ))
        for name in (watch.JS_RUNTIME_ENV, "WATCH_VIDEO_DETAIL", "GROQ_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(name, None)
        os.environ["WATCH_VIDEO_CONFIG_DIR"] = str(self.root / "config")

    def test_the_default_comes_from_the_environment(self) -> None:
        self.assertIsNone(watch.default_js_runtime())
        for value, expected in (("node", "node"), (" bun ", "bun"), ("quickjs", "quickjs"),
                                ("deno", None), ("", None)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {watch.JS_RUNTIME_ENV: value}):
                self.assertEqual(watch.default_js_runtime(), expected)
        with mock.patch.dict(os.environ, {watch.JS_RUNTIME_ENV: "/usr/local/bin/node"}):
            with self.assertRaises(ValueError) as caught:
                watch.default_js_runtime()
        self.assertIn("WATCH_VIDEO_JS_RUNTIME must be one of: node, quickjs, bun", str(caught.exception))

    def commands(self, **kwargs) -> list[list[str]]:
        media = self.root / "media"
        calls: list[list[str]] = []

        def fake_run(cmd, **_options):
            calls.append(cmd)
            if "--skip-download" not in cmd:
                (media / "video.mp4").write_bytes(b"stub")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(watch, "require_tool"), \
                mock.patch.object(watch, "run_command", side_effect=fake_run):
            watch.probe_url(YOUTUBE, media, **kwargs)
            watch.download_media(YOUTUBE, media, **kwargs)
            watch.download_media(YOUTUBE, media, audio_only=True, download_section="*00:00-00:30", **kwargs)
        return calls

    def test_yt_dlp_keeps_its_own_default_unless_the_user_opts_in(self) -> None:
        for cmd in self.commands():
            self.assertNotIn("--js-runtimes", cmd)

    def test_an_opted_in_runtime_reaches_every_yt_dlp_command(self) -> None:
        calls = self.commands(js_runtime="node")

        self.assertEqual(len(calls), 3)
        for cmd in calls:
            options = cmd[: cmd.index("--")]
            self.assertEqual(options[options.index("--js-runtimes") + 1], "node")
            # Only the name: yt-dlp also accepts NAME:PATH, which is never passed.
            self.assertNotIn(":", options[options.index("--js-runtimes") + 1])

    def run_main(self, *flags: str, info=None):
        media = self.root / "source.mp4"
        media.write_bytes(b"fixture")
        caption = self.root / "native.vtt"
        caption.write_text("WEBVTT\n\n00:00:00.000 --> 00:01:00.000\nhello\n", encoding="utf-8")
        with contextlib.ExitStack() as stack:
            probe = stack.enter_context(mock.patch.object(
                watch, "probe_url", return_value=({"path": str(caption)}, dict(info or {"duration": 60})),
            ))
            download = stack.enter_context(
                mock.patch.object(watch, "download_media", return_value=(media, None))
            )
            stack.enter_context(mock.patch.object(
                watch, "ffprobe_metadata", return_value={"duration_seconds": 60, "has_audio": True},
            ))
            stack.enter_context(mock.patch.object(
                sys, "argv", ["watch", YOUTUBE, "--out-dir", str(self.root / "runs"), *flags],
            ))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            try:
                outcome: object = watch.main()
            except SystemExit as exc:
                outcome = exc
        return outcome, probe, download

    def test_the_flag_and_the_environment_reach_the_probe_and_the_download(self) -> None:
        outcome, probe, download = self.run_main("--js-runtime", "node")
        self.assertEqual(outcome, 0)
        self.assertEqual(probe.call_args.kwargs["js_runtime"], "node")
        self.assertEqual(download.call_args.kwargs["js_runtime"], "node")

        os.environ[watch.JS_RUNTIME_ENV] = "bun"
        _, probe, download = self.run_main()
        self.assertEqual(probe.call_args.kwargs["js_runtime"], "bun")
        self.assertEqual(download.call_args.kwargs["js_runtime"], "bun")
        _, probe, _ = self.run_main("--js-runtime", "quickjs")
        self.assertEqual(probe.call_args.kwargs["js_runtime"], "quickjs")

        del os.environ[watch.JS_RUNTIME_ENV]
        _, probe, download = self.run_main()
        self.assertIsNone(probe.call_args.kwargs["js_runtime"])
        self.assertIsNone(download.call_args.kwargs["js_runtime"])

    def test_an_unknown_runtime_stops_the_run_before_the_source_is_read(self) -> None:
        os.environ[watch.JS_RUNTIME_ENV] = "python"
        outcome, probe, _ = self.run_main()
        self.assertIsInstance(outcome, SystemExit)
        self.assertIn("WATCH_VIDEO_JS_RUNTIME must be one of", str(outcome.code))
        probe.assert_not_called()

        del os.environ[watch.JS_RUNTIME_ENV]
        # Deno needs no flag, and a path is not a runtime name.
        for value in ("deno", "/usr/local/bin/node", "node:/usr/local/bin/node"):
            with self.subTest(value=value):
                outcome, probe, _ = self.run_main("--js-runtime", value)
                self.assertEqual(outcome.code, 2)
                probe.assert_not_called()

    def test_the_gemini_download_of_another_site_gets_the_opt_in_too(self) -> None:
        result = {"answer": "ok", "source_kind": "uploaded_file", "processing": "agentic",
                  "usage": {"total_tokens": 1}, "warnings": []}
        os.environ["GEMINI_API_KEY"] = "test-only"
        media = self.root / "source.mp4"
        media.write_bytes(b"fixture")
        with mock.patch.object(watch, "download_media", return_value=(media, None)) as download, \
                mock.patch.object(watch.gemini, "analyze_video", return_value=result), \
                mock.patch.object(sys, "argv", [
                    "watch", OTHER_URL, "--engine", "gemini", "--js-runtime", "node",
                    "--out-dir", str(self.root / "runs"),
                ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(watch.main(), 0)
        self.assertEqual(download.call_args.kwargs["js_runtime"], "node")


class ReportAdviceTests(unittest.TestCase):
    def test_yt_dlp_warnings_become_advice_that_names_the_doctor(self) -> None:
        missing = watch.youtube_support_notes(f"[youtube] abc: Downloading webpage\n{NO_RUNTIME_WARNING}\n")
        self.assertEqual(missing, [
            "yt-dlp found no JavaScript runtime it may use, so YouTube formats may be missing or "
            "the download may fail. Run scripts/doctor.py with this URL for the fix."
        ])

        scripts = watch.youtube_support_notes(NO_SCRIPTS_WARNING)
        self.assertEqual(len(scripts), 1)
        self.assertIn("without its challenge solver scripts (yt-dlp-ejs)", scripts[0])

        self.assertEqual(watch.youtube_support_notes("[youtube] abc: Downloading webpage\n"), [])
        self.assertEqual(watch.youtube_support_notes(""), [])

    def probe(self, stderr: str):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "media"

            def fake_run(cmd, **_options):
                (media / "video.info.json").write_text(json.dumps({"id": "abc", "duration": 60}))
                return subprocess.CompletedProcess(cmd, 0, "", stderr)

            with mock.patch.object(watch, "require_tool"), \
                    mock.patch.object(watch, "run_command", side_effect=fake_run):
                return watch.probe_url(YOUTUBE, media)[1]

    def test_the_probe_hands_the_advice_to_the_run(self) -> None:
        self.assertEqual(len(self.probe(NO_RUNTIME_WARNING)["yt_dlp_notes"]), 1)
        self.assertNotIn("yt_dlp_notes", self.probe("[youtube] abc: Downloading webpage\n"))

    def test_the_run_reports_the_advice_once_and_keeps_it_out_of_the_source_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "native.vtt"
            caption.write_text("WEBVTT\n\n00:00:00.000 --> 00:01:00.000\nhello\n", encoding="utf-8")
            info = {"duration": 60, "yt_dlp_notes": watch.youtube_support_notes(NO_RUNTIME_WARNING)}
            with mock.patch.dict(os.environ, {"WATCH_VIDEO_CONFIG_DIR": str(root / "config")}), \
                    mock.patch.object(watch, "probe_url", return_value=({"path": str(caption)}, info)), \
                    mock.patch.object(sys, "argv", [
                        "watch", YOUTUBE, "--detail", "transcript", "--out-dir", str(root / "runs"),
                    ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(watch.main(), 0)
            run = next((root / "runs").iterdir())
            metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
            report = (run / "report.md").read_text(encoding="utf-8")

        advice = [error for error in metadata["errors"] if "JavaScript runtime" in error]
        self.assertEqual(len(advice), 1)
        self.assertIn("Run scripts/doctor.py with this URL for the fix.", advice[0])
        self.assertNotIn("yt_dlp_notes", metadata["source_info"])
        self.assertIn("yt-dlp found no JavaScript runtime it may use", report)


if __name__ == "__main__":
    unittest.main()
