# Tests for promptc/rules/base.py -- catalogue integrity.
#
# The catalogue is what `promptc explain` serves to an agent that hit a
# diagnostic. A rule missing its rationale is a rule nobody can act on
# without reading source, so these are structural tests on the catalogue
# itself rather than on any single rule's behaviour.

# Third party
import pytest

# Local imports
from promptc.diagnostics import Severity
from promptc.rules import base

###########################################################
# Registration
###########################################################
def test_catalogue_is_not_empty():
    assert len(base.all_rules()) >= 20

def test_ids_are_unique():
    ids = [rule.id for rule in base.all_rules()]
    assert len(ids) == len(set(ids))

def test_ids_follow_the_naming_scheme():
    for rule in base.all_rules():
        assert rule.id.startswith("PC")
        assert rule.id[2:].isdigit()
        assert len(rule.id) == 5

def test_lookup_is_case_insensitive():
    assert base.get("pc001") is base.get("PC001")

def test_unknown_rule_returns_none():
    assert base.get("PC999") is None

###########################################################
# Content
###########################################################
@pytest.mark.parametrize("rule", base.all_rules(), ids = lambda r: r.id)
def test_every_rule_documents_itself(rule):
    """Summary, rationale and remedy are what `explain` prints."""
    assert rule.name
    assert rule.summary
    assert rule.rationale
    assert rule.remedy

@pytest.mark.parametrize("rule", base.all_rules(), ids = lambda r: r.id)
def test_rationale_explains_rather_than_restates(rule):
    """A rationale that just repeats the summary teaches nobody anything."""
    assert rule.rationale.strip() != rule.summary.strip()
    assert len(rule.rationale) > len(rule.summary)

###########################################################
# Severity policy
###########################################################
def test_structural_rules_are_errors_or_documented_warnings():
    """PC0xx are decidable. The warnings among them are deliberate:
    PC010 orphans and PC012 stale suppressions are hygiene, not faults."""
    allowed_warnings = {"PC010", "PC012", "PC014"}
    for rule in base.all_rules():
        if not rule.id.startswith("PC0"):
            continue
        if rule.severity is Severity.WARN:
            assert rule.id in allowed_warnings, f"{rule.id} is a WARN but not listed"

def test_heuristic_rules_never_error():
    """A measured heuristic may not fail a build. See docs/coding-standard.md."""
    for rule in base.all_rules():
        if rule.id.startswith("PC1"):
            assert rule.severity is not Severity.ERROR

def test_calibrated_flag_only_on_heuristics():
    for rule in base.all_rules():
        if rule.calibrated:
            assert rule.id.startswith("PC1"), f"{rule.id} claims a calibrated threshold"
