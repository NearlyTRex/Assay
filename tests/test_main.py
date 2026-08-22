# Tests for promptc/__main__.py -- module entry point.

# Imports
import os
import subprocess
import sys

# Third party
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.mark.integration
def test_module_is_runnable():
    """`python3 -m promptc` must work without an install step."""
    result = subprocess.run(
        [sys.executable, "-m", "promptc", "--version"],
        cwd = REPO_ROOT, capture_output = True, text = True,
        env = dict(os.environ, PYTHONPATH = REPO_ROOT))
    assert result.returncode == 0
    assert "promptc" in result.stdout
