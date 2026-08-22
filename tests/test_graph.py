# Tests for promptc/graph.py -- dependency and routing reporting.

# Imports
import json

# Local imports
from promptc import graph

###########################################################
# Fixtures
###########################################################
def build_library(fragment_file):
    fragment_file("core", """
        ---
        id: core
        kind: rule
        ---
        Core.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [core]
        contract: contracts/out.gbnf
        ---
        Task.
    """)
    fragment_file("recipe-x", """
        ---
        id: recipe-x
        kind: recipe
        triggers: [pattern_x]
        ---
        Recipe.
    """)
    fragment_file("lonely", """
        ---
        id: lonely
        kind: recipe
        ---
        Nothing routes here.
    """)

###########################################################
# Coverage
###########################################################
def test_coverage_counts_kinds(project, fragment_file, build_index):
    build_library(fragment_file)
    data = graph.coverage(build_index())
    assert data["fragments"] == 4
    assert data["kinds"]["recipe"] == 2
    assert data["kinds"]["task"] == 1

def test_coverage_lists_task_closures(project, fragment_file, build_index):
    build_library(fragment_file)
    data = graph.coverage(build_index())
    task = data["tasks"][0]
    assert task["id"] == "task-a"
    assert set(task["fragments"]) == {"core", "task-a"}

def test_coverage_reports_missing_dependencies(project, fragment_file, build_index):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [ghost]
        contract: contracts/out.gbnf
        ---
        Task.
    """)
    data = graph.coverage(build_index())
    assert data["tasks"][0]["missing"] == ["ghost"]

def test_coverage_maps_triggers(project, fragment_file, build_index):
    build_library(fragment_file)
    data = graph.coverage(build_index())
    assert data["triggers"]["pattern_x"] == ["recipe-x"]

def test_coverage_lists_orphans(project, fragment_file, build_index):
    build_library(fragment_file)
    assert graph.coverage(build_index())["orphans"] == ["lonely"]

###########################################################
# Rendering
###########################################################
def test_json_render_is_parseable(project, fragment_file, build_index):
    build_library(fragment_file)
    payload = json.loads(graph.render_json(build_index()))
    assert payload["fragments"] == 4

def test_text_render_lists_tasks_and_triggers(project, fragment_file, build_index):
    build_library(fragment_file)
    text = graph.render_text(build_index())
    assert "task task-a" in text
    assert "pattern_x" in text
    assert "lonely" in text

def test_orphans_only_mode(project, fragment_file, build_index):
    build_library(fragment_file)
    text = graph.render_text(build_index(), show_orphans_only = True)
    assert "lonely" in text
    assert "task-a" not in text

def test_orphans_only_says_so_when_clean(project, fragment_file, build_index):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Task.
    """)
    assert graph.render_text(build_index(), show_orphans_only = True) == "no orphan fragments"

def test_dot_render_is_a_digraph(project, fragment_file, build_index):
    build_library(fragment_file)
    dot = graph.render_dot(build_index())
    assert dot.startswith("digraph promptc {")
    assert dot.rstrip().endswith("}")
    assert '"task-a" -> "core";' in dot

def test_dot_marks_tasks_distinctly(project, fragment_file, build_index):
    build_library(fragment_file)
    dot = graph.render_dot(build_index())
    assert '"task-a" [shape=doubleoctagon];' in dot

def test_collision_is_marked_in_text_output(project, fragment_file, build_index):
    for name in ("r1", "r2"):
        fragment_file(name, f"""
            ---
            id: {name}
            kind: recipe
            triggers: [shared]
            ---
            Body.
        """)
    text = graph.render_text(build_index())
    assert "*" in text
