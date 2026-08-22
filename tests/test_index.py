# Tests for promptc/index.py -- identity, dependency closure, routing.

# Local imports
from promptc import index as index_module

###########################################################
# Identity
###########################################################
def test_duplicate_ids_are_recorded(project, fragment_file, build_index):
    for name in ("a", "b"):
        fragment_file(name, """
            ---
            id: same
            kind: rule
            ---
            Body.
        """)
    index = build_index()
    assert len(index.duplicates) == 1

    diagnostics = index_module.index_diagnostics(index)
    assert [d.rule for d in diagnostics] == ["PC008"]

###########################################################
# Dependency closure
###########################################################
def test_closure_places_dependencies_first(project, fragment_file, build_index):
    fragment_file("base", """
        ---
        id: base
        kind: rule
        ---
        Base.
    """)
    fragment_file("middle", """
        ---
        id: middle
        kind: rule
        requires: [base]
        ---
        Middle.
    """)
    fragment_file("top", """
        ---
        id: top
        kind: rule
        requires: [middle]
        ---
        Top.
    """)
    index = build_index()
    ordered = [item.id for item in index.closure(["top"])]
    assert ordered == ["base", "middle", "top"]

def test_closure_reports_missing_without_raising(project, fragment_file, build_index):
    fragment_file("top", """
        ---
        id: top
        kind: rule
        requires: [ghost]
        ---
        Top.
    """)
    index = build_index()
    missing = []
    ordered = index.closure(["top"], missing = missing)
    assert [item.id for item in ordered] == ["top"]
    assert missing == ["ghost"]

def test_shared_dependency_appears_once(project, fragment_file, build_index):
    fragment_file("shared", """
        ---
        id: shared
        kind: rule
        ---
        Shared.
    """)
    for name in ("left", "right"):
        fragment_file(name, f"""
            ---
            id: {name}
            kind: rule
            requires: [shared]
            ---
            Body {name}.
        """)
    index = build_index()
    ordered = [item.id for item in index.closure(["left", "right"])]
    assert ordered.count("shared") == 1

###########################################################
# Cycles
###########################################################
def test_cycle_is_detected(project, fragment_file, build_index):
    fragment_file("one", """
        ---
        id: one
        kind: rule
        requires: [two]
        ---
        One.
    """)
    fragment_file("two", """
        ---
        id: two
        kind: rule
        requires: [one]
        ---
        Two.
    """)
    index = build_index()
    assert index.cycles()

    diagnostics = index_module.index_diagnostics(index)
    assert [d.rule for d in diagnostics] == ["PC003"]

def test_closure_survives_a_cycle(project, fragment_file, build_index):
    """A cycle is reported by PC003, but must not hang or recurse forever."""
    fragment_file("one", """
        ---
        id: one
        kind: rule
        requires: [two]
        ---
        One.
    """)
    fragment_file("two", """
        ---
        id: two
        kind: rule
        requires: [one]
        ---
        Two.
    """)
    index = build_index()
    ordered = index.closure(["one"])
    assert {item.id for item in ordered} == {"one", "two"}

###########################################################
# Routing
###########################################################
def test_route_selects_by_trigger(project, fragment_file, build_index):
    for name, trigger in (("recipe-x", "pattern_x"), ("recipe-y", "pattern_y")):
        fragment_file(name, f"""
            ---
            id: {name}
            kind: recipe
            triggers: [{trigger}]
            ---
            Body {name}.
        """)
    index = build_index()
    assert [item.id for item in index.route(["pattern_x"])] == ["recipe-x"]
    assert index.route(["unknown_pattern"]) == []

def test_trigger_collision_is_reported(project, fragment_file, build_index):
    for name in ("r1", "r2"):
        fragment_file(name, f"""
            ---
            id: {name}
            kind: recipe
            triggers: [shared]
            ---
            Body {name}.
        """)
    index = build_index()
    assert index.trigger_collisions()
    assert [d.rule for d in index_module.index_diagnostics(index)] == ["PC009"]

def test_priority_resolves_a_collision(project, fragment_file, build_index):
    fragment_file("r1", """
        ---
        id: r1
        kind: recipe
        triggers: [shared]
        priority: 10
        ---
        Body r1.
    """)
    fragment_file("r2", """
        ---
        id: r2
        kind: recipe
        triggers: [shared]
        ---
        Body r2.
    """)
    index = build_index()
    assert index.trigger_collisions() == []
    assert [item.id for item in index.route(["shared"])] == ["r1"]

###########################################################
# Reachability
###########################################################
def test_orphan_detection(project, fragment_file, build_index):
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
    index = build_index()
    assert [item.id for item in index.orphans()] == ["lonely"]

def test_a_triggered_recipe_is_not_an_orphan(project, fragment_file, build_index):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    fragment_file("routed", """
        ---
        id: routed
        kind: recipe
        triggers: [pattern_x]
        ---
        Body.
    """)
    index = build_index()
    assert index.orphans() == []

###########################################################
# Resolution
###########################################################
def test_resolve_combines_task_and_routed_recipes(project, fragment_file, build_index):
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
        requires: [core]
        ---
        Recipe.
    """)
    index = build_index()
    resolution = index.resolve("task-a", ["pattern_x"])
    assert set(resolution.ids()) == {"core", "task-a", "recipe-x"}
    assert [item.id for item in resolution.routed] == ["recipe-x"]

def test_resolve_unknown_task_reports_missing(project, build_index):
    resolution = build_index().resolve("nonexistent")
    assert resolution.missing == ["nonexistent"]
    assert resolution.fragments == []
