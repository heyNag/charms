"""The oldest Python the watch-video scripts support, checked in one place.

Every command imports this module ahead of the skill's other modules, so an
interpreter that is too old stops with one clear line instead of a traceback
from whichever newer feature it meets first. Doctor and the local-model
preflight report against the same MIN_PYTHON.

Keep this file free of newer syntax and library calls: it has to run on the
interpreters it turns away.
"""

import sys


MIN_PYTHON = (3, 9)
PLUGIN = "watch-video"


def version_text(version=None):
    """Dotted form of a version tuple; the floor when none is given."""
    return ".".join(str(part) for part in (MIN_PYTHON if version is None else version))


def problem(version_info=None):
    """Say why this interpreter is too old, or return None when it is fine."""
    current = tuple((sys.version_info if version_info is None else version_info)[:3])
    if current[:2] >= MIN_PYTHON:
        return None
    return "%s needs Python %s or newer, but %s is Python %s. Run the script with a newer python3." % (
        PLUGIN, version_text(), sys.executable or "this interpreter", version_text(current),
    )


def require(version_info=None):
    """Stop with one clear line on an interpreter older than the floor."""
    message = problem(version_info)
    if message:
        raise SystemExit(message)


require()
