# Tests for promptc/evalharness/__init__.py -- run_eval orchestration.
#
# These run the whole harness end to end against the `command` backend
# driving a deterministic stand-in script. No test in this repository may
# contact a real model: a suite whose result depends on a model's mood is
# not a test. See docs/testing.md.

# Imports
import json
import os
import sys

# Third party
import pytest

# Local imports
from promptc import config as config_module
from promptc import evalharness

###########################################################
# Fixtures
###########################################################
# A stand-in "model" that always emits a fenced block saying OK.
ALWAYS_OK = "import sys; sys.stdin.read(); print('```'); print('OK'); print('```')"

# One that never produces anything extractable.
ALWAYS_PROSE = "import sys; sys.stdin.read(); print('I would rather not.')"

# One that alternates on the seed: fails on even seeds, passes on odd.
SEED_DEPENDENT = (
    "import sys; sys.stdin.read();"
    "seed = {seed};"
    "print('```');"
    "print('OK' if seed % 2 else 'nope');"
    "print('```')"
)

def eval_config(model_script):
    return f"""
library: promptlib
contracts: contracts
verifiers:
  - id: must-say-ok
    command: ["grep", "-q", "OK", "{{file}}"]
    timeout: 10
profiles:
  fake:
    context: 32768
    tokenizer: chars
    backend: command
    command: ["{sys.executable}", "-c", "{model_script}"]
eval:
  task: task-a
  verifiers: [must-say-ok]
  extract: fence
  suffix: .txt
  attempts: 1
corpus:
  root: corpus
  discover: "**/*.keep.txt"
  golden_suffix: ".keep.txt"
  inputs: ["{{stem}}.txt"]
  holdout: 0.0
"""

@pytest.fixture
def eval_project(project, write, fragment_file):
    def _setup(model_script = ALWAYS_OK, items = ("alpha", "beta")):
        write(os.path.join(project, "promptc.yaml"), eval_config(model_script))
        fragment_file("task-a", """
            ---
            id: task-a
            kind: task
            contract: contracts/out.gbnf
            ---
            Fix the thing. Return one fenced block.
        """)
        for name in items:
            write(os.path.join(project, "corpus", f"{name}.keep.txt"), f"golden {name}\n")
            write(os.path.join(project, "corpus", f"{name}.txt"), f"input {name}\n")
        return config_module.load_config(os.path.join(project, "promptc.yaml"))
    return _setup

###########################################################
# Happy path
###########################################################
@pytest.mark.integration
def test_run_eval_scores_a_passing_model(eval_project):
    config = eval_project()
    result = evalharness.run_eval(config, "fake", split = "dev")

    assert len(result.items) == 2
    assert result.pass_rate() == 1.0
    assert result.pass_at_1() == 1.0
    assert result.profile == "fake"

@pytest.mark.integration
def test_run_eval_records_prompt_size(eval_project):
    config = eval_project()
    result = evalharness.run_eval(config, "fake", split = "dev")
    assert result.prompt_tokens > 0
    assert "estimate" in result.tokenizer

@pytest.mark.integration
def test_run_eval_classifies_unextractable_output(eval_project):
    config = eval_project(model_script = ALWAYS_PROSE)
    result = evalharness.run_eval(config, "fake", split = "dev")

    assert result.pass_rate() == 0.0
    assert "no_answer" in result.taxonomy()

@pytest.mark.integration
def test_limit_caps_the_item_count(eval_project):
    config = eval_project(items = ("a", "b", "c", "d"))
    result = evalharness.run_eval(config, "fake", split = "dev", limit = 2)
    assert len(result.items) == 2

###########################################################
# Retries
###########################################################
@pytest.mark.integration
def test_retries_stop_at_the_first_pass(eval_project, project, write):
    """Seed 1000 fails, 1001 passes -- the item must stop after two."""
    config_text = eval_config(SEED_DEPENDENT).replace(
        "attempts: 1", "attempts: 3\n  seeds: [1000, 1001, 1002]")
    write(os.path.join(project, "promptc.yaml"), config_text)
    eval_project(items = ("alpha",))
    write(os.path.join(project, "promptc.yaml"), config_text)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))

    result = evalharness.run_eval(config, "fake", split = "dev")
    assert result.pass_rate() == 1.0
    assert result.pass_at_1() == 0.0
    assert result.items[0].attempts_to_green() == 2

###########################################################
# Configuration errors
###########################################################
@pytest.mark.integration
def test_unknown_profile_is_rejected(eval_project):
    config = eval_project()
    with pytest.raises(evalharness.EvalError) as caught:
        evalharness.run_eval(config, "nonexistent")
    assert "Known" in str(caught.value)

@pytest.mark.integration
def test_missing_task_is_rejected(project, write, eval_project):
    config = eval_project()
    config.eval.task = "nonexistent"
    with pytest.raises(evalharness.EvalError) as caught:
        evalharness.run_eval(config, "fake")
    assert "not found" in str(caught.value)

@pytest.mark.integration
def test_no_verifiers_is_rejected(eval_project):
    """Without a verifier nothing is scoring the output, which is the point."""
    config = eval_project()
    config.eval.verifiers = []
    with pytest.raises(evalharness.EvalError) as caught:
        evalharness.run_eval(config, "fake")
    assert "verifier" in str(caught.value)

@pytest.mark.integration
def test_empty_corpus_is_rejected(project, write, fragment_file):
    write(os.path.join(project, "promptc.yaml"), eval_config(ALWAYS_OK))
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    os.makedirs(os.path.join(project, "corpus"), exist_ok = True)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    with pytest.raises(evalharness.EvalError) as caught:
        evalharness.run_eval(config, "fake")
    assert "matched nothing" in str(caught.value)

###########################################################
# Golden answers
###########################################################
@pytest.mark.integration
def test_the_golden_answer_never_reaches_the_prompt(eval_project, project):
    """If the model could see the golden file the whole measurement is void."""
    captured = os.path.join(project, "captured.txt")
    script = (f"import sys; open({captured!r}, 'w').write(sys.stdin.read());"
              "print('```'); print('OK'); print('```')")
    config = eval_project(model_script = script, items = ("alpha",))

    evalharness.run_eval(config, "fake", split = "dev")

    with open(captured, encoding = "utf-8") as handle:
        prompt = handle.read()
    assert "input alpha" in prompt
    assert "golden alpha" not in prompt
