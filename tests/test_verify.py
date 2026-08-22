# Tests for promptc/verify.py -- example blocks and external verifiers.
#
# Every test that actually runs a verifier is marked integration: it crosses
# a process boundary. The extraction tests above them are pure.

# Imports
import os

# Third party
import pytest

# Local imports
from promptc import config as config_module
from promptc import fragment as fragment_module
from promptc import verify
from promptc.rules import run_check

###########################################################
# Fixtures
###########################################################
VERIFIER_CONFIG = """
library: promptlib
contracts: contracts
verifiers:
  - id: must-say-ok
    match: text
    command: ["grep", "-q", "OK", "{file}"]
    timeout: 10
"""

@pytest.fixture
def verifier_project(project, write):
    write(os.path.join(project, "promptc.yaml"), VERIFIER_CONFIG)
    return lambda: config_module.load_config(os.path.join(project, "promptc.yaml"))

def load_fragments(project):
    fragments, _ = fragment_module.load_library(os.path.join(project, "promptlib"))
    return fragments

###########################################################
# Block extraction
###########################################################
def test_blocks_are_extracted_with_language_and_line(project, fragment_file):
    fragment_file("r", """
        ---
        id: r
        kind: recipe
        ---
        Example:

        ```c
        int x = 1;
        ```
    """)
    blocks = verify.extract_blocks(load_fragments(project)[0])
    assert len(blocks) == 1
    assert blocks[0].language == "c"
    assert blocks[0].code.strip() == "int x = 1;"
    assert blocks[0].line > 0
    assert not blocks[0].skip

def test_noverify_marker_sets_skip(project, fragment_file):
    fragment_file("r", """
        ---
        id: r
        kind: recipe
        ---
        ```c promptc:noverify
        broken on purpose
        ```
    """)
    assert verify.extract_blocks(load_fragments(project)[0])[0].skip

def test_multiple_blocks_are_all_found(project, fragment_file):
    fragment_file("r", """
        ---
        id: r
        kind: recipe
        ---
        ```c
        one
        ```

        ```python
        two
        ```
    """)
    blocks = verify.extract_blocks(load_fragments(project)[0])
    assert [b.language for b in blocks] == ["c", "python"]

###########################################################
# Verifier matching
###########################################################
def test_match_compares_against_the_fence_language():
    verifier = config_module.Verifier(id = "v", command = ["true"], match = "cpp")
    block = verify.Block(language = "cpp", info = "cpp", code = "", line = 1, skip = False)
    assert verify.verifier_matches(verifier, block)

def test_match_accepts_backtick_form():
    verifier = config_module.Verifier(id = "v", command = ["true"], match = "```cpp")
    block = verify.Block(language = "cpp", info = "cpp", code = "", line = 1, skip = False)
    assert verify.verifier_matches(verifier, block)

def test_empty_match_matches_everything():
    verifier = config_module.Verifier(id = "v", command = ["true"], match = "")
    block = verify.Block(language = "rust", info = "rust", code = "", line = 1, skip = False)
    assert verify.verifier_matches(verifier, block)

def test_non_matching_language_is_skipped():
    verifier = config_module.Verifier(id = "v", command = ["true"], match = "cpp")
    block = verify.Block(language = "python", info = "python", code = "", line = 1, skip = False)
    assert not verify.verifier_matches(verifier, block)

###########################################################
# Running verifiers -- PC006
###########################################################
@pytest.mark.integration
def test_example_verification_catches_a_bad_block(project, write, verifier_project):
    write(os.path.join(project, "promptlib", "r.md"), """
        ---
        id: r
        kind: recipe
        ---
        ```text
        NOT FINE
        ```
    """)
    report = run_check(verifier_project())
    assert "PC006" in {d.rule for d in report.diagnostics}

@pytest.mark.integration
def test_good_block_passes(project, write, verifier_project):
    write(os.path.join(project, "promptlib", "r.md"), """
        ---
        id: r
        kind: recipe
        ---
        ```text
        OK
        ```
    """)
    report = run_check(verifier_project())
    assert "PC006" not in {d.rule for d in report.diagnostics}

@pytest.mark.integration
def test_noverify_marker_skips_a_block(project, write, verifier_project):
    write(os.path.join(project, "promptlib", "r.md"), """
        ---
        id: r
        kind: recipe
        ---
        Before:

        ```text promptc:noverify
        NOT FINE
        ```

        After:

        ```text
        OK
        ```
    """)
    report = run_check(verifier_project())
    assert "PC006" not in {d.rule for d in report.diagnostics}

@pytest.mark.integration
def test_diagnostic_names_the_verifier_and_carries_output(project, write, verifier_project):
    write(os.path.join(project, "promptlib", "r.md"), """
        ---
        id: r
        kind: recipe
        ---
        ```text
        NOT FINE
        ```
    """)
    report = run_check(verifier_project())
    finding = [d for d in report.diagnostics if d.rule == "PC006"][0]
    assert finding.data["verifier"] == "must-say-ok"
    assert finding.data["returncode"] != 0
    assert "promptc:noverify" in finding.fix_hint

@pytest.mark.integration
def test_missing_verifier_binary_is_reported_not_raised(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        library: promptlib
        contracts: contracts
        verifiers:
          - id: ghost
            match: text
            command: ["definitely-not-a-real-binary-xyz", "{file}"]
    """)
    write(os.path.join(project, "promptlib", "r.md"), """
        ---
        id: r
        kind: recipe
        ---
        ```text
        anything
        ```
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    diagnostics, results = verify.check_examples(config, load_fragments(project))
    assert results[0].returncode == 127
    assert diagnostics

@pytest.mark.integration
def test_no_verifiers_configured_means_no_findings(project, fragment_file, load_config):
    fragment_file("r", """
        ---
        id: r
        kind: recipe
        ---
        ```text
        anything at all
        ```
    """)
    diagnostics, results = verify.check_examples(load_config(), load_fragments(project))
    assert diagnostics == []
    assert results == []

@pytest.mark.integration
def test_fragment_filter_limits_what_runs(project, write, verifier_project):
    for name in ("good", "bad"):
        write(os.path.join(project, "promptlib", f"{name}.md"), f"""
            ---
            id: {name}
            kind: recipe
            ---
            ```text
            {"OK" if name == "good" else "NOT FINE"}
            ```
        """)
    config = verifier_project()
    diagnostics, results = verify.check_examples(
        config, load_fragments(project), only_fragment = "good")
    assert len(results) == 1
    assert diagnostics == []
