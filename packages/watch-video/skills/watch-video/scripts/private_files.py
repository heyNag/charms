"""Write a file that holds credentials so that nobody else can read it.

The content goes into a new file that is private (mode 600) from the moment
it exists and has a name nothing else can have put there. That file then
takes the place of the old one in a single step. There is no moment when the
content is readable by another account, and a symbolic link planted in the
folder is never written through.

A folder this has to create is private (mode 700). A folder that already
exists keeps its permissions.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


PRIVATE_DIR_MODE = 0o700


def write_private_text(path: Path, text: str) -> None:
    """Replace the file at `path` with `text`, private from the first byte."""
    path = Path(path)
    path.parent.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    # mkstemp opens with O_EXCL and O_NOFOLLOW, and creates the file as mode 600.
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
