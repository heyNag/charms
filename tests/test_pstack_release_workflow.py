"""Exercise the workflow's actual asset naming and verification with local ZIPs."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

from test_build_plugin_archive import make_plugin
from test_pstack_bundle import load_script, make_bundle


ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetWorkflowTests(unittest.TestCase):
    def test_both_archive_kinds_follow_validated_name_and_real_asset_checks(self):
        workflow = (ROOT / ".github/workflows/release-plugin.yml").read_text()
        name_output = next(line.strip() for line in workflow.splitlines()
                           if line.strip().startswith('echo "archive_name='))
        verification = workflow.split("- name: Verify the published immutable release", 1)[1]
        assignment = next(line.strip() for line in verification.splitlines()
                          if line.strip().startswith('archive='))
        program = re.search(r'python3 - "\$\{release_json\}"[^\n]+\n(.*?)\n          PY',
                            verification, re.S)
        self.assertIsNotNone(program)
        code = textwrap.dedent(program.group(1))
        self.assertIn("archive_name: ${{ steps.archive_check.outputs.archive_name }}", workflow)
        self.assertIn("ARCHIVE_NAME: ${{ needs.validate.outputs.archive_name }}", verification)
        builder = load_script("build-plugin-archive")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            make_plugin(root)
            make_bundle(root)
            for plugin in ("demo-plugin", "pstack"):
                with self.subTest(plugin=plugin):
                    output = root / "downloads" / plugin
                    built = builder.build_archive(root, plugin, output)
                    github_output = root / "job-output"
                    github_output.unlink(missing_ok=True)
                    env = dict(os.environ, ARCHIVE=str(built.archive),
                               GITHUB_OUTPUT=str(github_output))
                    subprocess.run(["bash", "-e", "-c", name_output], env=env, check=True)
                    name = github_output.read_text().strip().split("=", 1)[1]
                    env.update(ARCHIVE_NAME=name, release_dir=str(output),
                               PLUGIN=plugin, VERSION=built.version)
                    selected = subprocess.check_output(
                        ["bash", "-e", "-c", assignment + '\nprintf "%s" "$archive"'],
                        env=env, text=True,
                    )
                    self.assertEqual(selected, str(built.archive))
                    release = {"draft": False, "prerelease": False, "immutable": True,
                               "assets": [{"name": path.name,
                                           "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}
                                          for path in output.iterdir()]}
                    arguments = [sys.executable, "-c", code, json.dumps(release), str(output),
                                 selected, hashlib.sha256(built.archive.read_bytes()).hexdigest()]
                    result = subprocess.run(arguments, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    built.archive.write_bytes(built.archive.read_bytes() + b"changed after verification")
                    result = subprocess.run(arguments, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("published digests", result.stderr)


if __name__ == "__main__":
    unittest.main()
