# Tests for promptc/assemble.py -- deterministic ordering and manifests.

# Local imports
from promptc import assemble
from promptc import tokens

###########################################################
# Fixtures
###########################################################
def build_library(fragment_file):
    """Write a small library covering every kind that affects ordering."""
    fragment_file("terms", """
        ---
        id: terms
        kind: glossary
        ---
        Glossary body.
    """)
    fragment_file("core", """
        ---
        id: core
        kind: rule
        requires: [terms]
        ---
        Core rule body.
    """)
    fragment_file("recipe-x", """
        ---
        id: recipe-x
        kind: recipe
        triggers: [pattern_x]
        requires: [core]
        ---
        Recipe X body.
    """)
    fragment_file("recipe-y", """
        ---
        id: recipe-y
        kind: recipe
        triggers: [pattern_y]
        ---
        Recipe Y body.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [core]
        contract: contracts/out.gbnf
        ---
        Task body.
    """)

###########################################################
# Determinism
###########################################################
def test_assembly_is_byte_identical_across_runs(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    first = assemble.assemble(index, "task-a", ["pattern_x"])
    second = assemble.assemble(index, "task-a", ["pattern_x"])
    assert first.text == second.text
    assert first.digest() == second.digest()

def test_trigger_order_does_not_change_output(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    forward = assemble.assemble(index, "task-a", ["pattern_x", "pattern_y"])
    reverse = assemble.assemble(index, "task-a", ["pattern_y", "pattern_x"])
    assert forward.digest() == reverse.digest()

###########################################################
# Ordering
###########################################################
def test_kind_bands_order_the_assembly(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    ids = [item.id for item in assemble.assemble(index, "task-a", ["pattern_x"]).fragments]
    assert ids.index("terms") < ids.index("core")
    assert ids.index("core") < ids.index("recipe-x")
    assert ids.index("recipe-x") < ids.index("task-a")

def test_routing_only_pulls_matching_recipes(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    ids = [item.id for item in assemble.assemble(index, "task-a", ["pattern_x"]).fragments]
    assert "recipe-x" in ids
    assert "recipe-y" not in ids

def test_no_triggers_pulls_no_recipes(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    ids = [item.id for item in assemble.assemble(index, "task-a").fragments]
    assert "recipe-x" not in ids
    assert "recipe-y" not in ids
    assert "task-a" in ids

###########################################################
# Rendering
###########################################################
def test_suppression_comments_are_stripped_from_output(project, fragment_file, build_index):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        <!-- promptc-disable PC100: a justification long enough to pass -->
        Visible body.
    """)
    index = build_index()
    text = assemble.assemble(index, "task-a").text
    assert "promptc-disable" not in text
    assert "Visible body." in text

def test_headings_added_for_non_task_fragments(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    text = assemble.assemble(index, "task-a", ["pattern_x"]).text
    assert "## Recipe X body." not in text
    assert "## recipe-x" in text or "## Recipe" in text

###########################################################
# Manifest
###########################################################
def test_manifest_records_routing_and_digest(project, fragment_file, build_index):
    build_library(fragment_file)
    index = build_index()

    built = assemble.assemble(index, "task-a", ["pattern_x"])
    manifest = built.manifest(tokens.counter("chars"))

    assert manifest["task"] == "task-a"
    assert manifest["triggers"] == ["pattern_x"]
    assert manifest["routed"] == ["recipe-x"]
    assert manifest["digest"] == built.digest()
    assert manifest["tokens"] > 0
    assert "estimate" in manifest["tokenizer"]
    assert {entry["id"] for entry in manifest["fragments"]} == set(built.ids())

def test_manifest_reports_missing_fragments(project, fragment_file, build_index):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [ghost]
        contract: contracts/out.gbnf
        ---
        Task body.
    """)
    index = build_index()
    built = assemble.assemble(index, "task-a")
    assert built.manifest()["missing"] == ["ghost"]
