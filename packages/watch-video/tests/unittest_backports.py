"""unittest helpers that Python 3.9 and 3.10 lack.

The plugin supports Python 3.9 and its tests run there too. Import this module
from any test file that calls TestCase.enterContext, which unittest gained in
Python 3.11. On newer interpreters the import changes nothing.
"""

from __future__ import annotations

import unittest


def _enter_context(self, context_manager):
    """Enter a context manager now and leave it when the test is cleaned up."""
    manager_type = type(context_manager)
    try:
        enter = manager_type.__enter__
        leave = manager_type.__exit__
    except AttributeError:
        raise TypeError(
            f"'{manager_type.__module__}.{manager_type.__qualname__}' object does "
            "not support the context manager protocol"
        ) from None
    result = enter(context_manager)
    self.addCleanup(leave, context_manager, None, None, None)
    return result


if not hasattr(unittest.TestCase, "enterContext"):
    unittest.TestCase.enterContext = _enter_context
