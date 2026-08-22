# Tests for promptc/cli.py -- the command line surface.
#
# Every test here spawns the real CLI as a subprocess, because exit codes
# and stream separation are the contract an agent depends on and neither is
# observable from an in-process call.

# Imports
import json
import os
import subprocess
import sys

# Third party
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

###########################################################
# Helpers
###########################################################
def run_cli(cwd, *args):
    """Invoke the CLI as a subprocess and return the CompletedProcess."""
    env = dict(os.environ, PYTHONPATH = REPO_ROOT, NO_COLOR = "1")
    return subprocess.run(
        [sys.executable, "-m", "promptc", *args],
        cwd = cwd, capture_output = True, text = True, env = env)

def valid_task(fragment_file):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        The task body.
    """)

###########################################################
# check
###########################################################
def test_check_exits_nonzero_on_error(project, fragment_file):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        ---
        As described above, do the thing.
    """)
    result = run_cli(project, "check", "--no-examples")
    assert result.returncode == 1
    assert "PC001" in result.stdout
    assert "PC005" in result.stdout

def test_check_exits_zero_when_clean(project, fragment_file):
    valid_task(fragment_file)
    result = run_cli(project, "check", "--no-examples")
    assert result.returncode == 0

def test_check_json_is_parseable(project, fragment_file):
    valid_task(fragment_file)
    result = run_cli(project, "check", "--no-examples", "--format", "json")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["errors"] == 0

def test_check_json_carries_fix_hints(project, fragment_file):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [ghost]
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    result = run_cli(project, "check", "--no-examples", "--format", "json")
    payload = json.loads(result.stdout)
    finding = [d for d in payload["diagnostics"] if d["rule"] == "PC002"][0]
    assert finding["fix_hint"]
    assert finding["file"]

def test_warnings_alone_do_not_fail_the_build(project, fragment_file):
    valid_task(fragment_file)
    fragment_file("lonely", """
        ---
        id: lonely
        kind: recipe
        ---
        Nothing routes here.
    """)
    result = run_cli(project, "check", "--no-examples")
    assert "PC010" in result.stdout
    assert result.returncode == 0

###########################################################
# explain
###########################################################
def test_explain_returns_rationale_and_remedy(project):
    result = run_cli(project, "explain", "PC001", "--format", "json")
    payload = json.loads(result.stdout)
    assert payload["id"] == "PC001"
    assert payload["rationale"]
    assert payload["remedy"]

def test_explain_lists_every_rule(project):
    result = run_cli(project, "explain", "--format", "json")
    payload = json.loads(result.stdout)
    assert len(payload) >= 20
    assert all("id" in entry for entry in payload)

def test_explain_unknown_rule_exits_two(project):
    result = run_cli(project, "explain", "PC999")
    assert result.returncode == 2
    assert "Unknown rule" in result.stderr

def test_explain_marks_uncalibrated_thresholds(project):
    result = run_cli(project, "explain", "PC100")
    assert "calibrate" in result.stdout

###########################################################
# build
###########################################################
def test_build_emits_the_prompt(project, fragment_file):
    valid_task(fragment_file)
    result = run_cli(project, "build", "task-a")
    assert result.returncode == 0
    assert "The task body." in result.stdout

def test_build_unknown_task_exits_two(project, fragment_file):
    valid_task(fragment_file)
    result = run_cli(project, "build", "nonexistent")
    assert result.returncode == 2
    assert "Known tasks" in result.stderr

def test_build_writes_a_manifest(project, fragment_file):
    valid_task(fragment_file)
    manifest = os.path.join(project, "manifest.json")
    result = run_cli(project, "build", "task-a", "--manifest", manifest,
                     "--out", os.path.join(project, "prompt.txt"))
    assert result.returncode == 0

    with open(manifest, encoding = "utf-8") as handle:
        payload = json.load(handle)
    assert payload["task"] == "task-a"
    assert payload["digest"]

def test_build_explain_shows_token_costs(project, fragment_file):
    valid_task(fragment_file)
    result = run_cli(project, "build", "task-a", "--explain", "--profile", "big")
    assert "total" in result.stdout
    assert "budget" in result.stdout

###########################################################
# init and new
###########################################################
def test_init_creates_a_working_project(tmp_path):
    root = str(tmp_path)
    result = run_cli(root, "init", ".")
    assert result.returncode == 0
    assert os.path.exists(os.path.join(root, "promptc.yaml"))
    assert os.path.isdir(os.path.join(root, "promptlib"))

    # And the fresh project passes its own check
    assert run_cli(root, "check", "--no-examples").returncode == 0

def test_init_refuses_to_clobber(tmp_path):
    root = str(tmp_path)
    run_cli(root, "init", ".")
    result = run_cli(root, "init", ".")
    assert result.returncode == 2
    assert "--force" in result.stderr

def test_new_scaffolds_a_parseable_fragment(project):
    result = run_cli(project, "new", "recipe", "my-recipe")
    assert result.returncode == 0
    assert os.path.exists(os.path.join(project, "promptlib", "my-recipe.md"))

    from promptc import fragment as fragment_module
    fragments, errors = fragment_module.load_library(os.path.join(project, "promptlib"))
    assert errors == []
    assert any(item.id == "my-recipe" for item in fragments)

def test_new_refuses_to_clobber(project):
    run_cli(project, "new", "recipe", "my-recipe")
    result = run_cli(project, "new", "recipe", "my-recipe")
    assert result.returncode == 2

###########################################################
# graph
###########################################################
def test_graph_json_lists_tasks_and_orphans(project, fragment_file):
    valid_task(fragment_file)
    fragment_file("lonely", """
        ---
        id: lonely
        kind: recipe
        ---
        Body.
    """)
    result = run_cli(project, "graph", "--format", "json")
    payload = json.loads(result.stdout)
    assert payload["orphans"] == ["lonely"]
    assert payload["tasks"][0]["id"] == "task-a"

def test_graph_dot_is_emitted(project, fragment_file):
    valid_task(fragment_file)
    result = run_cli(project, "graph", "--format", "dot")
    assert result.stdout.startswith("digraph")

###########################################################
# split
###########################################################
def test_split_dry_run_reports_without_writing(project):
    source = os.path.join(project, "mono.md")
    with open(source, "w", encoding = "utf-8") as handle:
        handle.write("# Doc\n\n## Rules\n\n### One\n\nBody.\n")

    out = os.path.join(project, "promptlib", "split")
    result = run_cli(project, "split", source, "--out", out)
    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert not os.path.exists(out)

def test_split_apply_writes_fragments(project):
    source = os.path.join(project, "mono.md")
    with open(source, "w", encoding = "utf-8") as handle:
        handle.write("# Doc\n\n## Rules\n\n### One\n\nBody.\n")

    out = os.path.join(project, "promptlib", "split")
    result = run_cli(project, "split", source, "--out", out, "--apply")
    assert result.returncode == 0
    assert os.path.isdir(out)

###########################################################
# Global behaviour
###########################################################
def test_missing_config_exits_two_with_a_remedy(tmp_path):
    result = run_cli(str(tmp_path), "check")
    assert result.returncode == 2
    assert "promptc init" in result.stderr

def test_bad_config_path_exits_two(project):
    result = run_cli(project, "--config", "/nonexistent/promptc.yaml", "check")
    assert result.returncode == 2
    assert "not found" in result.stderr

def test_version_is_reported(project):
    result = run_cli(project, "--version")
    assert result.returncode == 0
    assert "promptc" in result.stdout

def test_no_subcommand_exits_nonzero(project):
    assert run_cli(project).returncode != 0

def test_diagnostics_go_to_stdout_not_stderr(project, fragment_file):
    """Agents read findings from stdout; stderr is reserved for tool faults."""
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        ---
        Body.
    """)
    result = run_cli(project, "check", "--no-examples")
    assert "PC005" in result.stdout
    assert "PC005" not in result.stderr
