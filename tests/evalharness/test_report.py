# Tests for promptc/evalharness/report.py -- aggregation.

# Imports
import json

# Local imports
from promptc.evalharness import report as report_module
from promptc.evalharness import score

###########################################################
# Helpers
###########################################################
def attempt(passed, verifier = "cpp-compiles"):
    return score.Attempt(
        seed = 1,
        outcome = score.OUTCOME_PASS if passed else score.OUTCOME_VERIFIER,
        failing_verifier = "" if passed else verifier)

def item(stem, triggers, outcomes):
    """Build an ItemResult from a list of per-attempt pass booleans."""
    return score.ItemResult(
        stem = stem, triggers = triggers,
        attempts = [attempt(flag) for flag in outcomes])

def run(items, profile = "local", attempts = 1):
    return report_module.RunResult(
        profile = profile, task = "t", split = "dev",
        items = items, attempts = attempts, tokenizer = "chars (estimate)")

###########################################################
# Pass rates
###########################################################
def test_pass_at_1_uses_only_the_first_attempt():
    result = run([
        item("a", ["x"], [False, True]),   # passes, but not first try
        item("b", ["x"], [True]),
    ], attempts = 2)
    assert result.pass_at_1() == 0.5
    assert result.pass_rate() == 1.0

def test_mean_attempts_to_green_ignores_failures():
    result = run([
        item("a", ["x"], [False, False, True]),
        item("b", ["x"], [True]),
        item("c", ["x"], [False, False, False]),
    ], attempts = 3)
    assert result.mean_attempts_to_green() == 2.0

def test_empty_run_reports_zero_rather_than_dividing_by_zero():
    result = run([])
    assert result.pass_rate() == 0.0
    assert result.pass_at_1() == 0.0
    assert result.mean_attempts_to_green() == 0.0

###########################################################
# Scorecard
###########################################################
def test_scorecard_counts_an_item_under_every_trigger():
    result = run([item("a", ["x", "y"], [True])])
    rows = {row["trigger"]: row for row in result.scorecard()}
    assert rows["x"]["total"] == 1
    assert rows["y"]["total"] == 1

def test_scorecard_sorts_worst_first():
    result = run([
        item("a", ["good"], [True]),
        item("b", ["good"], [True]),
        item("c", ["bad"], [False]),
        item("d", ["bad"], [False]),
    ])
    assert result.scorecard()[0]["trigger"] == "bad"
    assert result.scorecard()[0]["pass_rate"] == 0.0

def test_untriggered_items_bucket_under_none():
    result = run([item("a", [], [True])])
    assert result.scorecard()[0]["trigger"] == "<none>"

###########################################################
# Taxonomy
###########################################################
def test_taxonomy_names_the_failing_verifier():
    failing = score.ItemResult(
        stem = "a", triggers = ["x"],
        attempts = [attempt(False, verifier = "lint-clean")])
    result = run([failing])
    assert "verifier_failed:lint-clean" in result.taxonomy()

def test_taxonomy_counts_passes():
    result = run([item("a", ["x"], [True]), item("b", ["x"], [True])])
    assert result.taxonomy()[score.OUTCOME_PASS] == 2

###########################################################
# Portability
###########################################################
def test_portability_index_is_the_ratio_to_baseline():
    local = run([item("a", ["x"], [True]), item("b", ["x"], [False])], profile = "local")
    cloud = run([item("a", ["x"], [True]), item("b", ["x"], [True])], profile = "cloud")

    rows = report_module.portability([local, cloud], "cloud")
    assert len(rows) == 1
    assert rows[0]["profile"] == "local"
    assert rows[0]["portability_index"] == 0.5

def test_portability_empty_when_baseline_missing():
    local = run([item("a", ["x"], [True])], profile = "local")
    assert report_module.portability([local], "nonexistent") == []

def test_portability_empty_when_baseline_scored_zero():
    """Dividing by a baseline that failed everything says nothing."""
    local = run([item("a", ["x"], [True])], profile = "local")
    cloud = run([item("a", ["x"], [False])], profile = "cloud")
    assert report_module.portability([local, cloud], "cloud") == []

###########################################################
# Rendering
###########################################################
def test_json_render_is_parseable():
    result = run([item("a", ["x"], [True])])
    payload = json.loads(report_module.render_json([result]))
    assert payload["runs"][0]["profile"] == "local"
    assert payload["runs"][0]["pass_at_k"] == 1.0

def test_json_omits_per_item_rows_by_default():
    payload = json.loads(report_module.render_json([run([item("a", ["x"], [True])])]))
    assert "results" not in payload["runs"][0]

def test_json_includes_per_item_rows_on_request():
    result = run([item("a", ["x"], [True])])
    payload = json.loads(report_module.render_json([result], include_items = True))
    assert payload["runs"][0]["results"][0]["stem"] == "a"

def test_text_render_shows_rates_and_scorecard():
    result = run([item("a", ["x"], [True]), item("b", ["y"], [False])])
    text = report_module.render_text([result])
    assert "pass@1" in text
    assert "per-trigger scorecard" in text
    assert "failure taxonomy" in text
