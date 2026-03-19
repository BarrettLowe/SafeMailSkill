"""Shared pytest configuration."""
import sys
import os

# Ensure the project root is on the path so tests can import modules directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest


_MODULES_TO_CLEAR = ("config", "main", "jmap_client", "notifier")


@pytest.fixture
def clear_module_cache():
    """Clear cached module imports to allow fresh imports after env patching."""
    for mod in list(sys.modules.keys()):
        if mod in _MODULES_TO_CLEAR:
            del sys.modules[mod]
    yield
    for mod in list(sys.modules.keys()):
        if mod in _MODULES_TO_CLEAR:
            del sys.modules[mod]
