"""Discover maintained pstack bridge tests without measuring generated duplicates."""

import importlib.util
from pathlib import Path


def load_tests(loader, tests, pattern):
    path = Path(__file__).resolve().parents[1] / "integrations/pstack/tests/test_bridge.py"
    spec = importlib.util.spec_from_file_location("pstack_bridge_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
