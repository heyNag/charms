"""What a run may leave at the top of its folder.

prune_runs names the files and folders a run creates there. It takes a folder
that lost its record for an unfinished run only when the folder holds nothing
else, and the repository's validator keeps the same names out of commits. The
tests that start a run pass its folder to unexpected_entries, so a run cannot
begin to create something those lists do not name.
"""

from __future__ import annotations

from pathlib import Path

import prune_runs


def unexpected_entries(run: Path) -> list[str]:
    """What prune_runs does not expect in a run folder, or in the runs of a batch."""
    found: list[str] = []
    for entry in sorted(run.iterdir()):
        is_folder = entry.is_dir() and not entry.is_symlink()
        if entry.name not in (prune_runs.RUN_FOLDERS if is_folder else prune_runs.RUN_FILES):
            found.append(entry.name)
        elif is_folder and entry.name == "videos":
            for video in sorted(entry.iterdir()):
                found.extend(f"videos/{video.name}/{name}" for name in unexpected_entries(video))
    return found
