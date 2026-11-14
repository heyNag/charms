#!/usr/bin/env python3
"""Check that the links between this repository's documents resolve.

Every Markdown file that Git can see is read. A link to a path must name a
file or folder that Git can see too, inside the repository. A link with a
#fragment that points at a Markdown file must name one of its headings, the
way GitHub turns a heading into an anchor.

Links to other sites are counted and not followed. A check that needs the
network fails for reasons that have nothing to do with the change under test.

Markdown links, images and link definitions are read; raw HTML is not. A
heading is a line that starts with one to six # characters.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import urllib.parse
from collections import Counter
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# The line that opens or closes a fenced code block. Backticks later on the
# line make it a code span instead.
FENCE_RE = re.compile(r"^ {0,3}(`{3,}(?=[^`]*$)|~{3,})")
HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# A run of backticks, then everything up to the next run of the same length.
CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
LINK_TEXT = r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]"
# [text](target) or ![text](target "title"). The text may hold one more pair
# of brackets, and the target one pair of parentheses.
INLINE_LINK_RE = re.compile(
    LINK_TEXT
    + r"\(\s*(<[^<>\n]*>|[^\s()<>]*(?:\([^\s()]*\)[^\s()<>]*)*)"
    + r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
# [label]: target. A label that starts with ^ names a footnote, not a link.
DEFINITION_RE = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:[ \t]*(<[^<>\n]*>|\S+)", re.MULTILINE)
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
HEADING_LINK_RE = re.compile(r"!?(" + LINK_TEXT + r")\([^()]*\)")
EMPHASIS_RE = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")


def _blank(match: re.Match[str]) -> str:
    """Spaces in place of the matched text, with its line breaks kept."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _without_fenced_code(text: str) -> list[str]:
    """The lines of a document, with every line of a fenced code block emptied."""
    lines: list[str] = []
    fence = ""
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if fence:
            closes = match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence)
            if closes and not line.strip().strip(fence[0]):
                fence = ""
            lines.append("")
        elif match:
            fence = match.group(1)
            lines.append("")
        else:
            lines.append(line)
    return lines


def anchor(heading: str) -> str:
    """The anchor GitHub gives a heading, before it numbers the repeats."""
    text = HEADING_LINK_RE.sub(lambda match: match.group(1)[1:-1], heading)
    text = EMPHASIS_RE.sub(r"\1", text).lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(lines: list[str]) -> set[str]:
    """Every anchor of a document: a repeated heading gets -1, -2 and so on."""
    found: set[str] = set()
    seen: Counter[str] = Counter()
    for line in lines:
        match = HEADING_RE.match(line)
        if not match:
            continue
        name = anchor(match.group(1))
        found.add(f"{name}-{seen[name]}" if seen[name] else name)
        seen[name] += 1
    return found


def links(lines: list[str]) -> list[tuple[int, str]]:
    """Each link target in a document, with the number of the line it is on."""
    text = COMMENT_RE.sub(_blank, "\n".join(lines))
    text = CODE_SPAN_RE.sub(_blank, text)
    found: list[tuple[int, str]] = []
    for pattern in (INLINE_LINK_RE, DEFINITION_RE):
        for match in pattern.finditer(text):
            target = match.group(1)
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            found.append((text.count("\n", 0, match.start(1)) + 1, target))
    return sorted(found)


def visible_files(root: Path) -> set[Path]:
    """The files under root that Git tracks or would add, or every file outside a Git work tree."""
    options = ["--cached", "--others", "--exclude-standard", "-z"]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", *options],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        listed = result.stdout.split(b"\0") if result.returncode == 0 else None
    except OSError:
        listed = None
    if listed is not None:
        paths = (Path(os.fsdecode(item)) for item in listed if item)
        # The index still lists a file that was deleted without `git rm`.
        return {path for path in paths if os.path.lexists(root / path)}

    found: set[Path] = set()
    for current, folders, files in os.walk(root):
        folders[:] = [name for name in folders if name != ".git"]
        found.update(Path(current, name).relative_to(root) for name in files)
    return found


def check_links(root: Path) -> tuple[list[str], int, int]:
    """Return the broken links, the number of links checked, and the number left unfollowed."""
    root = root.resolve()
    files = visible_files(root)
    folders = {parent for path in files for parent in path.parents}
    documents = sorted(path for path in files if path.suffix.lower() == ".md")

    lines_of: dict[Path, list[str]] = {}
    problems: list[str] = []
    for document in documents:
        try:
            lines_of[document] = _without_fenced_code((root / document).read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            problems.append(f"{document.as_posix()}: cannot read the document: {exc}")
    anchors_of = {document: anchors(lines) for document, lines in lines_of.items()}

    checked = unfollowed = 0
    for document, lines in lines_of.items():
        for line_number, target in links(lines):
            if SCHEME_RE.match(target) or target.startswith("//"):
                unfollowed += 1
                continue
            checked += 1
            reason = _broken(document, target, root, files, folders, anchors_of)
            if reason:
                problems.append(f"{document.as_posix()}:{line_number}: {target}: {reason}")
    return problems, checked, unfollowed


def _broken(
    document: Path,
    target: str,
    root: Path,
    files: set[Path],
    folders: set[Path],
    anchors_of: dict[Path, set[str]],
) -> str | None:
    """Say why a link from a document does not resolve, or None when it does."""
    location, _, fragment = target.partition("#")
    location = urllib.parse.unquote(location.partition("?")[0])
    fragment = urllib.parse.unquote(fragment)
    if not location:
        destination = document
    elif location.startswith("/"):
        # GitHub reads a leading slash as the top of the repository.
        destination = Path(os.path.normpath(location.lstrip("/")))
    else:
        destination = Path(os.path.normpath(os.path.join(document.parent, location)))

    if destination.is_absolute() or ".." in destination.parts:
        return "points outside the repository"
    if destination not in files and destination not in folders:
        if os.path.lexists(root / destination):
            return "Git ignores that path, so only this checkout has it"
        return "no such file or folder in the repository"
    if fragment and destination in anchors_of and fragment not in anchors_of[destination]:
        return f"{destination.as_posix()} has no heading with the anchor #{fragment}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)

    problems, checked, unfollowed = check_links(REPOSITORY_ROOT)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"checked {checked} link(s) between the documents; "
        f"{unfollowed} link(s) to other sites were not followed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
