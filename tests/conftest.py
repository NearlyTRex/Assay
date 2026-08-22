# Shared fixtures.
#
# Every fixture builds a throwaway project on disk, because promptc is a
# pure function of a source tree and testing it against anything else would
# be testing a different program.

# Imports
import os
import sys
import textwrap

# Third party
import pytest

# Make the package importable without an install step
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Local imports
from promptc import config as config_module
from promptc import fragment as fragment_module
from promptc import index as index_module

###########################################################
# Constants
###########################################################
BASE_CONFIG = """
library: promptlib
contracts: contracts
profiles:
  small:
    context: 2000
    tokenizer: chars
    reserve: 200
    output_reserve: 200
  big:
    context: 200000
    tokenizer: chars
"""

###########################################################
# Filesystem helpers
###########################################################
def write_file(path, text):
    """Write dedented text to path, creating parent directories.

    Args:
        path: Absolute destination path.
        text: Content. Dedented and left-stripped of newlines so tests can
            use triple-quoted strings at natural indentation.
    """
    os.makedirs(os.path.dirname(path), exist_ok = True)
    with open(path, "w", encoding = "utf-8") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))

@pytest.fixture
def write():
    """Return the write_file helper."""
    return write_file

###########################################################
# Project
###########################################################
@pytest.fixture
def project(tmp_path):
    """Create a minimal promptc project and return its root.

    Ships two profiles: `small` (2,000 token context, tight reserves) for
    exercising PC004, and `big` for everything that must not trip it.

    Returns:
        str: Absolute path to the project root.
    """
    root = str(tmp_path)
    write_file(os.path.join(root, "promptc.yaml"), BASE_CONFIG)
    os.makedirs(os.path.join(root, "promptlib"), exist_ok = True)
    os.makedirs(os.path.join(root, "contracts"), exist_ok = True)
    write_file(os.path.join(root, "contracts", "out.gbnf"), 'root ::= "x"\n')
    return root

@pytest.fixture
def fragment_file(project):
    """Return a helper that writes a fragment into the project library."""
    def _write(name, text):
        write_file(os.path.join(project, "promptlib", f"{name}.md"), text)
    return _write

@pytest.fixture
def load_config(project):
    """Return a helper that loads the project's config."""
    def _load():
        return config_module.load_config(os.path.join(project, "promptc.yaml"))
    return _load

@pytest.fixture
def build_index(project):
    """Return a helper that parses the library and builds an Index."""
    def _build():
        fragments, _ = fragment_module.load_library(os.path.join(project, "promptlib"))
        return index_module.Index(fragments)
    return _build

###########################################################
# Assertions
###########################################################
def rule_ids(report):
    """Return the sorted distinct rule ids present in a report.

    Args:
        report: Report to inspect.

    Returns:
        list[str]: Sorted unique rule ids.
    """
    return sorted({diagnostic.rule for diagnostic in report.diagnostics})

@pytest.fixture
def rules_in():
    """Return the rule_ids helper."""
    return rule_ids
