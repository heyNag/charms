"""check-doc-links.py reports the links between documents that do not resolve."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from release_fixtures import git, init_repository, isolate_git


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-doc-links.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_doc_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CheckDocLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        isolate_git(self)
        self.module = load_module()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name).resolve()
        self.write("docs/guide.md", "# Guide\n\n## Set up\n\nBack to [the start](../README.md).\n")

    def write(self, relative: str, text: str = "") -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def problems(self, readme: str | None = None) -> list[str]:
        if readme is not None:
            self.write("README.md", readme)
        return self.module.check_links(self.root)[0]

    def test_links_that_resolve_pass(self) -> None:
        self.write("docs/release notes.md", "# Notes\n")
        self.write("docs/logo.png")
        self.write("packages/demo/plugin.json", "{}\n")
        self.write(
            "README.md",
            "# Demo\n\n"
            "A [file](docs/guide.md), a [folder](packages/demo/), the [top](.) and an\n"
            "![image](docs/logo.png). A [heading](docs/guide.md#set-up), one\n"
            "[here](#demo) and one [seen as source](docs/guide.md?plain=1#set-up).\n"
            "From [the top of the repository](/docs/guide.md). With a\n"
            '[title](docs/guide.md "The guide"), [escaped](docs/release%20notes.md)\n'
            "and [in angle brackets](<docs/release notes.md>).\n"
            "Text with [`code`](docs/guide.md), with [more [brackets] inside](docs/guide.md)\n"
            "and [over two\nlines](docs/guide.md). By [label][guide].\n\n"
            "[guide]: docs/guide.md\n",
        )

        # Fifteen links here, and the one in docs/guide.md.
        self.assertEqual(self.module.check_links(self.root), ([], 16, 0))

    def test_broken_links_are_reported_with_their_line(self) -> None:
        self.assertEqual(
            self.problems(
                "# Demo\n\n"
                "A [missing file](docs/missing.md) and a [missing folder](packages/).\n"
                "A [missing heading](docs/guide.md#install) and [one here](#usage).\n\n"
                "Text with [a link over two\nlines](../outside.md) and [a label][other].\n\n"
                "[other]: docs/other.md\n"
            ),
            [
                "README.md:3: docs/missing.md: no such file or folder in the repository",
                "README.md:3: packages/: no such file or folder in the repository",
                "README.md:4: #usage: README.md has no heading with the anchor #usage",
                "README.md:4: docs/guide.md#install: "
                "docs/guide.md has no heading with the anchor #install",
                "README.md:7: ../outside.md: points outside the repository",
                "README.md:9: docs/other.md: no such file or folder in the repository",
            ],
        )

    def test_a_link_is_read_from_the_folder_of_its_document(self) -> None:
        self.write(
            "docs/guide.md",
            "# Guide\n\n[Wrong](README.md), [right](../README.md), [top](/README.md).\n",
        )

        self.assertEqual(
            self.problems("# Demo\n"),
            ["docs/guide.md:3: README.md: no such file or folder in the repository"],
        )

    def test_links_to_other_sites_are_counted_and_not_followed(self) -> None:
        self.write(
            "README.md",
            "[Site](https://example.invalid/missing), [old](http://example.invalid/),\n"
            "[mail](mailto:nobody@example.invalid), [any scheme](//example.invalid/x)\n"
            "and <https://example.invalid/autolink>.\n\n[label]: https://example.invalid/label\n",
        )

        self.assertEqual(self.module.check_links(self.root), ([], 1, 5))

    def test_code_and_comments_are_not_read_for_links(self) -> None:
        self.assertEqual(
            self.problems(
                "# Demo\n\n"
                "Write `[text](missing.md)` or ``[`text`](missing.md)`` for a link.\n\n"
                "```markdown\n[text](missing.md)\n```\n\n"
                "~~~\n[text](missing.md)\n```\n[still code](missing.md)\n~~~\n\n"
                "````\n```\n[text](missing.md)\n```\n````\n\n"
                "<!-- [text](missing.md)\n[label]: missing.md -->\n\n"
                "[^1]: A footnote, not a link definition.\n\n"
                "- [ ] (a task, not a link)\n\n"
                "[Read after the code](missing.md).\n\n"
                "```\n[text](missing.md)\nA fence that never closes runs to the end.\n"
            ),
            ["README.md:28: missing.md: no such file or folder in the repository"],
        )

        # Three backticks open a code span when more backticks follow on the line.
        self.assertEqual(
            self.problems("```[text](missing.md)``` is code.\n\n[This is read](missing.md).\n"),
            ["README.md:3: missing.md: no such file or folder in the repository"],
        )

    def test_anchors_are_the_ones_github_gives_headings(self) -> None:
        for heading, anchor in (
            ("Python versions", "python-versions"),
            ("`plugin.json` and `SKILL.md`", "pluginjson-and-skillmd"),
            ("What's new in 1.2.0?", "whats-new-in-120"),
            ("Bird & the X API", "bird--the-x-api"),
            ("Set up [another Mac](other.md#mac)", "set-up-another-mac"),
            ("snake_case and _emphasis_ with **weight**", "snake_case-and-emphasis-with-weight"),
            ("Step-by-step", "step-by-step"),
        ):
            with self.subTest(heading=heading):
                self.assertEqual(self.module.anchor(heading), anchor)

        document = (
            "# Usage\n\nText\n\n## Usage\n\n### Usage ###\n\n#Not a heading\n\n"
            "```sh\n# A comment in code\n```\n\n    ## Indented too far to be a heading\n\n"
            "   ## Three spaces are fine\n"
        )
        lines = self.module._without_fenced_code(document)
        self.assertEqual(
            self.module.anchors(lines), {"usage", "usage-1", "usage-2", "three-spaces-are-fine"}
        )

    def test_git_decides_which_files_exist(self) -> None:
        init_repository(self.root)
        self.write(".gitignore", "private/\n")
        self.write("private/notes.md", "# Notes\n\n[Broken, and never read](missing.md).\n")
        self.write("docs/removed.md", "# Removed\n")
        git(self.root, "add", "--all")
        (self.root / "docs" / "removed.md").unlink()

        self.assertEqual(
            self.problems("# Demo\n\n[Notes](private/notes.md) and [removed](docs/removed.md).\n"),
            [
                "README.md:3: docs/removed.md: no such file or folder in the repository",
                "README.md:3: private/notes.md: "
                "Git ignores that path, so only this checkout has it",
            ],
        )

    def test_a_document_that_cannot_be_read_is_reported(self) -> None:
        (self.root / "docs" / "broken.md").write_bytes(b"# Title \xff\n")

        problems = self.problems("# Demo\n\n[Guide](docs/guide.md) and [broken](docs/broken.md).\n")

        self.assertEqual(len(problems), 1)
        self.assertRegex(problems[0], r"\Adocs/broken\.md: cannot read the document: .+")

    def test_cli_reports_each_broken_link_and_fails(self) -> None:
        self.write(
            "README.md", "# Demo\n\n[Guide](docs/guide.md) and [site](https://example.invalid/).\n"
        )
        with mock.patch.object(self.module, "REPOSITORY_ROOT", self.root):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.module.main([])
            self.assertEqual(
                (code, stdout.getvalue(), stderr.getvalue()),
                (
                    0,
                    "checked 2 link(s) between the documents; "
                    "1 link(s) to other sites were not followed\n",
                    "",
                ),
            )

            self.write(
                "README.md", "# Demo\n\n[Guide](docs/guide.md#missing) and [gone](gone.md).\n"
            )
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.module.main([])
            self.assertEqual((code, stdout.getvalue()), (1, ""))
            self.assertEqual(
                stderr.getvalue(),
                "error: README.md:3: docs/guide.md#missing: "
                "docs/guide.md has no heading with the anchor #missing\n"
                "error: README.md:3: gone.md: no such file or folder in the repository\n",
            )

            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as refused:
                    self.module.main(["README.md"])
            self.assertEqual(refused.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
