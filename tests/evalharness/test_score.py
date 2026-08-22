# Tests for promptc/evalharness/score.py -- extraction, verification, taxonomy.
#
# The invariant under test throughout: the verifier decides pass and fail.
# Similarity to the golden answer is recorded but never consulted, because a
# different-but-valid answer is not wrong.

# Imports
import os

# Third party
import pytest

# Local imports
from promptc import config as config_module
from promptc.evalharness import runner, score

###########################################################
# Extraction
###########################################################
def test_fence_extraction_takes_the_block():
    text = "Here you go:\n\n```c\nint x = 1;\n```\n\nHope that helps."
    assert score.extract(text, "fence").strip() == "int x = 1;"

def test_fence_extraction_ignores_prose_when_no_fence():
    assert score.extract("just prose, no block", "fence") == ""

def test_raw_extraction_passes_everything_through():
    assert score.extract("anything at all", "raw") == "anything at all"

def test_empty_text_extracts_to_empty():
    assert score.extract("", "fence") == ""
    assert score.extract("   \n ", "raw") == ""

def test_fence_with_no_language_still_extracts():
    assert score.extract("```\nplain\n```", "fence").strip() == "plain"

###########################################################
# Similarity
###########################################################
def test_similarity_is_one_for_identical_text():
    assert score.similarity("a b c", "a b c") == 1.0

def test_similarity_is_zero_when_either_side_is_empty():
    assert score.similarity("", "a b c") == 0.0
    assert score.similarity("a b c", "") == 0.0

###########################################################
# Verification
###########################################################
VERIFY_CONFIG = """
library: promptlib
contracts: contracts
verifiers:
  - id: must-say-ok
    command: ["grep", "-q", "OK", "{file}"]
    timeout: 10
  - id: must-not-say-bad
    command: ["grep", "-qv", "BAD", "{file}"]
    timeout: 10
eval:
  task: t
  verifiers: [must-say-ok, must-not-say-bad]
  suffix: .txt
"""

@pytest.fixture
def verify_config(project, write):
    write(os.path.join(project, "promptc.yaml"), VERIFY_CONFIG)
    return config_module.load_config(os.path.join(project, "promptc.yaml"))

@pytest.mark.integration
def test_verify_passes_when_every_verifier_passes(verify_config):
    ok, failing, detail = score.verify(verify_config, "OK\n", ".txt")
    assert ok
    assert failing == ""

@pytest.mark.integration
def test_verify_reports_the_first_failing_verifier(verify_config):
    ok, failing, detail = score.verify(verify_config, "nothing useful\n", ".txt")
    assert not ok
    assert failing == "must-say-ok"

@pytest.mark.integration
def test_verify_runs_verifiers_in_order(verify_config):
    """First verifier passes, second fails -- the second must be named."""
    ok, failing, detail = score.verify(verify_config, "OK but also BAD\n", ".txt")
    assert not ok
    assert failing == "must-not-say-bad"

@pytest.mark.integration
def test_unknown_verifier_id_is_reported(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        eval:
          task: t
          verifiers: [ghost]
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    ok, failing, detail = score.verify(config, "anything", ".txt")
    assert not ok
    assert "ghost" in detail

###########################################################
# Taxonomy
###########################################################
@pytest.mark.integration
def test_backend_error_is_classified_separately(verify_config):
    generation = runner.Generation("", ok = False, error = "connection refused")
    attempt = score.score_generation(verify_config, generation, "golden", seed = 1)
    assert attempt.outcome == score.OUTCOME_ERROR
    assert not attempt.passed()

@pytest.mark.integration
def test_empty_output_is_classified_as_empty(verify_config):
    attempt = score.score_generation(
        verify_config, runner.Generation("   \n"), "golden", seed = 1)
    assert attempt.outcome == score.OUTCOME_EMPTY

@pytest.mark.integration
def test_unextractable_output_points_at_the_contract(verify_config):
    attempt = score.score_generation(
        verify_config, runner.Generation("I think you should do this."), "golden", seed = 1)
    assert attempt.outcome == score.OUTCOME_NO_ANSWER

@pytest.mark.integration
def test_verifier_rejection_names_the_verifier(verify_config):
    attempt = score.score_generation(
        verify_config, runner.Generation("```\nwrong\n```"), "golden", seed = 1)
    assert attempt.outcome == score.OUTCOME_VERIFIER
    assert attempt.failing_verifier == "must-say-ok"

@pytest.mark.integration
def test_passing_output_is_a_pass(verify_config):
    attempt = score.score_generation(
        verify_config, runner.Generation("```\nOK\n```"), "golden", seed = 1)
    assert attempt.outcome == score.OUTCOME_PASS
    assert attempt.passed()

@pytest.mark.integration
def test_similarity_does_not_decide_the_outcome(verify_config):
    """An answer nothing like the golden one still passes if it verifies."""
    attempt = score.score_generation(
        verify_config, runner.Generation("```\nOK\n```"),
        golden = "something entirely different from the answer", seed = 1)
    assert attempt.passed()
    assert attempt.similarity < 0.5

###########################################################
# ItemResult
###########################################################
def make_attempt(passed, seed = 1, verifier = ""):
    return score.Attempt(
        seed = seed,
        outcome = score.OUTCOME_PASS if passed else score.OUTCOME_VERIFIER,
        failing_verifier = "" if passed else (verifier or "some-verifier"))

def test_item_passes_if_any_attempt_passes():
    item = score.ItemResult(stem = "a", attempts = [
        make_attempt(False), make_attempt(False), make_attempt(True)])
    assert item.passed()
    assert item.attempts_to_green() == 3

def test_item_fails_when_no_attempt_passes():
    item = score.ItemResult(stem = "a", attempts = [make_attempt(False)] * 3)
    assert not item.passed()
    assert item.attempts_to_green() == 0
    assert item.outcome() == score.OUTCOME_VERIFIER

def test_failing_verifier_reported_from_the_last_attempt():
    item = score.ItemResult(stem = "a", attempts = [
        make_attempt(False, verifier = "first"),
        make_attempt(False, verifier = "second")])
    assert item.failing_verifier() == "second"

def test_item_with_no_attempts_is_a_backend_error():
    assert score.ItemResult(stem = "a").outcome() == score.OUTCOME_ERROR
