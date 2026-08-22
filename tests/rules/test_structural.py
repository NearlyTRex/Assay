# Tests for promptc/rules/structural.py -- the decidable rules, PC001-PC013.
#
# Every rule gets two tests: one that trips it, and one proving it clears
# once the fault is fixed. A rule that only ever fires is indistinguishable
# from a rule that always fires.

# Third party
import pytest

# Local imports
from promptc.diagnostics import Severity
from promptc.rules import run_check

###########################################################
# PC001 -- dangling references
###########################################################
def test_prose_reference_is_an_error(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        As described above, apply §20 to the input.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC001" in rules_in(report)
    # Both the prose reference and the section number are caught
    assert sum(1 for d in report.diagnostics if d.rule == "PC001") == 2

def test_explicit_ref_needs_a_declared_require(project, fragment_file, load_config, rules_in):
    fragment_file("helper", """
        ---
        id: helper
        kind: rule
        ---
        Helper body.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Follow {{ref:helper}} exactly.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC001" in rules_in(report)

def test_explicit_ref_passes_when_required(project, fragment_file, load_config, rules_in):
    fragment_file("helper", """
        ---
        id: helper
        kind: rule
        ---
        Helper body.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [helper]
        contract: contracts/out.gbnf
        ---
        Follow {{ref:helper}} exactly.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC001" not in rules_in(report)

def test_ref_to_unknown_fragment_says_so(project, fragment_file, load_config):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Follow {{ref:nonexistent}} exactly.
    """)
    report = run_check(load_config(), examples = False)
    matches = [d for d in report.diagnostics if d.rule == "PC001"]
    assert matches
    assert "names no known fragment" in matches[0].message

###########################################################
# PC002 -- unresolved requires
###########################################################
def test_unresolved_require(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [ghost]
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC002" in rules_in(report)

def test_resolved_require_passes(project, fragment_file, load_config, rules_in):
    fragment_file("real", """
        ---
        id: real
        kind: rule
        ---
        Body.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [real]
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC002" not in rules_in(report)

###########################################################
# PC004 -- token budget
###########################################################
def test_budget_exceeded_uses_profile_reserve(project, fragment_file, load_config):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {"word " * 4000}
    """)
    report = run_check(load_config(), profile_name = "small", examples = False)
    errors = [d for d in report.diagnostics
              if d.rule == "PC004" and d.severity is Severity.ERROR]
    assert errors
    # context 2000 - reserve 200 - output_reserve 200
    assert errors[0].data["budget"] == 1600

def test_same_library_fits_a_larger_profile(project, fragment_file, load_config):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {"word " * 4000}
    """)
    report = run_check(load_config(), profile_name = "big", examples = False)
    assert not [d for d in report.diagnostics
                if d.rule == "PC004" and d.severity is Severity.ERROR]

def test_per_fragment_budget_warns(project, fragment_file, load_config):
    fragment_file("fat", f"""
        ---
        id: fat
        kind: rule
        budget: 10
        ---
        {"word " * 200}
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [fat]
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), profile_name = "big", examples = False)
    warnings = [d for d in report.diagnostics
                if d.rule == "PC004" and d.severity is Severity.WARN]
    assert warnings
    assert warnings[0].data["id"] == "fat"

###########################################################
# PC005 / PC013 -- output contracts
###########################################################
def test_task_without_contract(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC005" in rules_in(report)

def test_non_task_needs_no_contract(project, fragment_file, load_config, rules_in):
    fragment_file("plain", """
        ---
        id: plain
        kind: rule
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC005" not in rules_in(report)

def test_contract_file_must_exist(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/missing.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC013" in rules_in(report)

def test_existing_contract_passes(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC013" not in rules_in(report)
    assert "PC005" not in rules_in(report)

###########################################################
# PC007 -- glossary terms
###########################################################
def test_glossary_term_needs_its_provider(project, fragment_file, load_config, rules_in):
    fragment_file("terms", """
        ---
        id: terms
        kind: glossary
        provides: ["keep file"]
        ---
        **keep file** — the authoritative manual version.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Update the keep file before continuing.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC007" in rules_in(report)

def test_glossary_term_passes_when_required(project, fragment_file, load_config, rules_in):
    fragment_file("terms", """
        ---
        id: terms
        kind: glossary
        provides: ["keep file"]
        ---
        **keep file** — the authoritative manual version.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [terms]
        contract: contracts/out.gbnf
        ---
        Update the keep file before continuing.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC007" not in rules_in(report)

def test_a_word_nobody_declares_is_not_a_term(project, fragment_file, load_config, rules_in):
    """Only terms some fragment `provides` are checked; ordinary prose is not."""
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Update the widget before continuing.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC007" not in rules_in(report)

###########################################################
# PC010 -- orphans
###########################################################
def test_orphan_fragment_warns(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    fragment_file("lonely", """
        ---
        id: lonely
        kind: recipe
        ---
        Nothing routes here.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC010" in rules_in(report)
    orphan = [d for d in report.diagnostics if d.rule == "PC010"][0]
    assert orphan.severity is Severity.WARN

###########################################################
# PC011 / PC012 -- suppressions
###########################################################
def test_suppression_requires_justification(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        <!-- promptc-disable PC100 -->
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC011" in rules_in(report)

def test_unused_suppression_is_reported(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        <!-- promptc-disable PC100: measured, no pass-rate delta on n=480 -->
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC012" in rules_in(report)
    assert "PC011" not in rules_in(report)
