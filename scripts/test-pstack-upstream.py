#!/usr/bin/env python3
"""Run pstack's upstream helper tests without writing to either bundled target.

Dependency installation is explicit and confined to a temporary directory.
The ordinary repository checks remain offline; this is a separate CI target.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def identity(root: Path) -> dict[str, tuple[str, int]]:
    return {
        p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                       p.stat().st_mode & 0o777)
        for p in root.rglob("*") if p.is_file()
    }


def run(command: list[str], cwd: Path, env: dict[str, str], timeout: int = 900) -> None:
    supervised = sys.platform.startswith("linux")
    actual = command
    if supervised:
        helper = ROOT / "integrations/pstack/codex/providers/process_supervisor.py"
        if not helper.is_file():
            raise RuntimeError("the owned-process supervisor is missing")
        actual = [sys.executable, str(helper), "--", *command]
    with subprocess.Popen(actual, cwd=cwd, env=env, start_new_session=True) as process:
        try:
            status = process.wait(timeout=timeout)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        if status:
            raise subprocess.CalledProcessError(status, command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--install", action="store_true",
                        help="Install pinned test dependencies in a disposable directory.")
    parser.add_argument("--toolchain", type=Path,
                        help="Use an existing test-toolchain node_modules directory instead.")
    parser.add_argument("--tlc", type=Path, help="Run TLC integration cases using this original jar.")
    args = parser.parse_args()
    root = args.root.resolve()
    bundle = root / "packages/pstack"
    if not bundle.is_dir():
        parser.error("generate packages/pstack before running its tests")
    if args.install == bool(args.toolchain):
        parser.error("select exactly one of --install or --toolchain")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("STATECHART_UPDATE", None)
    env.pop("TLA2TOOLS", None)
    if args.tlc:
        jar = args.tlc.resolve()
        if hashlib.sha256(jar.read_bytes()).hexdigest() != (
            "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
        ):
            parser.error("TLC jar does not match upstream's pinned 1.7.4 SHA-256")
        env["TLA2TOOLS"] = str(jar)
    else:
        print("TLC integration cases are not enabled; pass --tlc to certify them.", flush=True)
    before = identity(bundle)
    try:
        with tempfile.TemporaryDirectory(prefix="charms-pstack-tests-") as temporary:
            work = Path(temporary)
            toolchain = work / "toolchain"
            if args.install:
                shutil.copytree(root / "integrations/pstack/test-toolchain", toolchain,
                                ignore=shutil.ignore_patterns("node_modules"))
                run(["npm", "ci", "--no-audit", "--no-fund"], toolchain, env)
                modules = toolchain / "node_modules"
            else:
                modules = args.toolchain.resolve()
            bun = modules / ".bin/bun"
            if not bun.is_file():
                parser.error("test toolchain needs its pinned Bun executable")
            env["PATH"] = str(modules / ".bin") + os.pathsep + env.get("PATH", "")
            if subprocess.check_output([str(bun), "--version"], text=True).strip() != "1.3.13":
                parser.error("test toolchain Bun must be 1.3.13")
            # Preserve complete test fixtures; all dependency caches and test writes stay here.
            skills = work / "skills"
            shutil.copytree(bundle / "codex/skills", skills)
            (work / "node_modules").symlink_to(modules, target_is_directory=True)
            statechart = skills / "statechart/scripts"
            tests = sorted(str(p) for p in (statechart / "test").glob("*.test.ts"))
            if not tests:
                raise RuntimeError("Statechart test closure is missing")
            run(["node", "--disable-warning=ExperimentalWarning", "--test", *tests],
                statechart, env)
            mode = skills / "poteto-mode/scripts"
            run([str(bun), "install", "--frozen-lockfile", "--ignore-scripts"], mode, env)
            run([str(bun), "test", "watch-pr"], mode, env)
            run([str(bun), "run", "typecheck"], mode, env)
            run([sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"),
                 "-p", "test_pstack_watch_pr.py"], root,
                {**env, "PSTACK_TEST_BUN": str(bun)})
    finally:
        if identity(bundle) != before:
            raise RuntimeError("upstream checks changed the authoritative bundle")
    print("Upstream helper checks passed; bundle bytes and modes are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
