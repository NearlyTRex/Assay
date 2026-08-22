# Tests for promptc/calibrate.py -- turning guessed thresholds into measured ones.
#
# The verdicts matter more than the arithmetic: `not-predictive` and
# `inverted` are how a bad rule gets removed, so both must be reachable.

# Imports
import json

# Third party
import pytest

# Local imports
from promptc import calibrate, tokens

###########################################################
# Statistics
###########################################################
def test_pearson_detects_a_perfect_positive_relationship():
    assert calibrate.pearson([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)

def test_pearson_detects_a_perfect_negative_relationship():
    assert calibrate.pearson([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)

def test_pearson_needs_at_least_three_points():
    assert calibrate.pearson([1, 2], [1, 2]) is None

def test_pearson_returns_none_without_variance():
    assert calibrate.pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None

def test_significance_falls_with_a_weaker_correlation():
    strong = calibrate.significance(0.95, 20)
    weak = calibrate.significance(0.10, 20)
    assert strong < weak

def test_significance_needs_enough_points():
    assert calibrate.significance(0.9, 3) is None

###########################################################
# Threshold proposals
###########################################################
def test_propose_threshold_finds_the_cliff():
    """Pass rate collapses above a feature value of 5."""
    pairs = [(1, 0.9), (2, 0.9), (3, 0.85), (4, 0.9), (5, 0.88),
             (6, 0.2), (7, 0.15), (8, 0.1), (9, 0.1), (10, 0.05)]
    proposal = calibrate.propose_threshold(pairs)
    assert proposal is not None
    assert 3 <= proposal <= 7

def test_propose_threshold_abstains_on_thin_data():
    assert calibrate.propose_threshold([(1, 0.5), (2, 0.4)]) is None

def test_propose_threshold_abstains_when_nothing_degrades():
    pairs = [(n, 0.9) for n in range(1, 11)]
    assert calibrate.propose_threshold(pairs) is None

###########################################################
# Calibration verdicts
###########################################################
def build_project(fragment_file, specs):
    """Write one recipe per (id, trigger, body) spec."""
    for fragment_id, trigger, body in specs:
        fragment_file(fragment_id, f"""
            ---
            id: {fragment_id}
            kind: recipe
            triggers: [{trigger}]
            ---
            {body}
        """)

def run_payload(rows):
    return {"runs": [{"scorecard": [
        {"trigger": trigger, "total": total, "passed": passed,
         "pass_rate": passed / total}
        for trigger, passed, total in rows
    ]}]}

def test_insufficient_data_is_reported_not_guessed(project, fragment_file, build_index, load_config):
    build_project(fragment_file, [("r1", "t1", "Set the field.")])
    findings = calibrate.calibrate(
        load_config(), build_index(), tokens.counter("chars"),
        run_payload([("t1", 5, 10)]))
    assert all(f["verdict"] == "insufficient-data" for f in findings)

def test_triggers_with_too_few_items_are_excluded(project, fragment_file, build_index, load_config):
    """Two observations cannot establish a rate worth regressing on."""
    build_project(fragment_file, [(f"r{n}", f"t{n}", "Set the field.") for n in range(5)])
    findings = calibrate.calibrate(
        load_config(), build_index(), tokens.counter("chars"),
        run_payload([(f"t{n}", 1, 2) for n in range(5)]))
    assert all(f["n"] == 0 for f in findings)

def test_predictive_feature_is_identified(project, fragment_file, build_index, load_config):
    """More instructions, lower pass rate -- PC102 should come out predictive."""
    specs = []
    rows = []
    for n in range(8):
        instructions = " ".join(f"Set field {i} to zero." for i in range(2 + n * 8))
        specs.append((f"r{n}", f"t{n}", instructions))
        # Pass rate falls as instruction count climbs
        rows.append((f"t{n}", max(0, 10 - n), 10))

    build_project(fragment_file, specs)
    findings = calibrate.calibrate(
        load_config(), build_index(), tokens.counter("chars"), run_payload(rows))

    instruction_finding = next(f for f in findings if f["feature"] == "instruction_count")
    assert instruction_finding["n"] == 8
    assert instruction_finding["r"] < 0
    assert instruction_finding["verdict"] in ("predictive", "weak")

def test_inverted_verdict_is_reachable(project, fragment_file, build_index, load_config):
    """A rule that fires on what actually helps must be catchable."""
    specs = []
    rows = []
    for n in range(8):
        instructions = " ".join(f"Set field {i} to zero." for i in range(2 + n * 8))
        specs.append((f"r{n}", f"t{n}", instructions))
        # Pass rate RISES with instruction count
        rows.append((f"t{n}", min(10, 2 + n), 10))

    build_project(fragment_file, specs)
    findings = calibrate.calibrate(
        load_config(), build_index(), tokens.counter("chars"), run_payload(rows))

    instruction_finding = next(f for f in findings if f["feature"] == "instruction_count")
    assert instruction_finding["r"] > 0
    assert instruction_finding["verdict"] in ("inverted", "weak")

def test_every_finding_names_its_rule_or_none(project, fragment_file, build_index, load_config):
    build_project(fragment_file, [("r1", "t1", "Set the field.")])
    findings = calibrate.calibrate(
        load_config(), build_index(), tokens.counter("chars"),
        run_payload([("t1", 5, 10)]))
    for finding in findings:
        assert "feature" in finding
        assert "verdict" in finding

###########################################################
# Rendering
###########################################################
def test_text_render_explains_each_verdict():
    findings = [{"rule": "PC102", "feature": "instruction_count", "n": 8,
                 "r": -0.9, "p": 0.001, "verdict": "predictive",
                 "current_threshold": 30, "proposed_threshold": 18.0}]
    text = calibrate.render_text(findings)
    assert "instruction_count" in text
    assert "keep the rule" in text
    assert "30 -> 18.0" in text
    assert "held-out" in text

def test_text_render_warns_against_blind_application():
    text = calibrate.render_text([])
    assert "starting points, not settings" in text

def test_json_render_is_parseable():
    findings = [{"rule": None, "feature": "token_size", "n": 4,
                 "r": 0.1, "p": 0.8, "verdict": "not-predictive"}]
    payload = json.loads(calibrate.render_json(findings))
    assert payload["findings"][0]["feature"] == "token_size"
