"""Dependency and coverage reporting.

Answers the questions you ask while refactoring: what does this task
actually pull in, what is nothing routing to, and which triggers have no
recipe behind them.

Reporting only. Everything here is derived from an Index, and nothing
raises -- a library with unresolved dependencies still produces a graph,
with the gaps shown rather than hidden.
"""

# Imports
import json

###########################################################
# Coverage
###########################################################
def coverage(index, config = None):
    """Summarise what the library contains and what reaches what.

    Args:
        index: Built Index.
        config: Accepted for symmetry with the other reporting entry
            points; not currently used.

    Returns:
        dict: With `fragments` (a count), `tasks` (each with its resolved
        closure and any missing ids), `triggers` (name to candidate ids),
        `orphans`, and `kinds` (a count per kind).
    """
    tasks = []
    for task in index.tasks():
        resolution = index.resolve(task.id)
        tasks.append({
            "id": task.id,
            "fragments": resolution.ids(),
            "missing": resolution.missing,
        })

    triggers = {}
    for trigger, matches in sorted(index.by_trigger.items()):
        triggers[trigger] = [item.id for item in matches]

    return {
        "fragments": len(index.fragments),
        "tasks": tasks,
        "triggers": triggers,
        "orphans": [item.id for item in index.orphans()],
        "kinds": _count_kinds(index),
    }

def _count_kinds(index):
    """Return a count of fragments per kind, ordered by kind name."""
    counts = {}
    for item in index.fragments:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return dict(sorted(counts.items()))

###########################################################
# Rendering
###########################################################
def render_json(index):
    """Render the coverage summary as indented JSON."""
    return json.dumps(coverage(index), indent = 2)

def render_text(index, show_orphans_only = False):
    """Render the coverage summary for a terminal.

    A trigger routing to more than one fragment is marked with `*`, which
    is what PC009 reports as a collision.

    Args:
        index: Built Index.
        show_orphans_only: List only unreachable fragments, with their
            paths. Reads "no orphan fragments" when there are none.

    Returns:
        str: The report, with trailing whitespace stripped.
    """
    data = coverage(index)
    lines = []

    if show_orphans_only:
        if not data["orphans"]:
            return "no orphan fragments"
        lines.append(f"{len(data['orphans'])} orphan fragment(s) — unreachable from any task")
        for fragment_id in data["orphans"]:
            item = index.get(fragment_id)
            lines.append(f"  {fragment_id:<40} {item.path if item else ''}")
        return "\n".join(lines)

    kinds = ", ".join(f"{count} {kind}" for kind, count in data["kinds"].items())
    lines.append(f"{data['fragments']} fragments — {kinds}")
    lines.append("")

    for task in data["tasks"]:
        lines.append(f"task {task['id']}  ({len(task['fragments'])} fragments always included)")
        for fragment_id in task["fragments"]:
            item = index.get(fragment_id)
            kind = item.kind if item else "?"
            lines.append(f"    {kind:<9} {fragment_id}")
        for missing in task["missing"]:
            lines.append(f"    MISSING   {missing}")
        lines.append("")

    if data["triggers"]:
        lines.append(f"{len(data['triggers'])} trigger(s) routed")
        width = max(len(name) for name in data["triggers"])
        for trigger, matches in data["triggers"].items():
            marker = "  " if len(matches) == 1 else " *"
            lines.append(f"  {trigger:<{width}}{marker} -> {', '.join(matches)}")
        lines.append("")

    if data["orphans"]:
        lines.append(f"{len(data['orphans'])} orphan(s): {', '.join(data['orphans'])}")

    return "\n".join(lines).rstrip()

###########################################################
# Graphviz
###########################################################
def render_dot(index):
    """Render the dependency graph as Graphviz DOT.

    Node shape encodes kind, so a task is distinguishable from a recipe at
    a glance. Edges point from a fragment to what it requires.

    Args:
        index: Built Index.

    Returns:
        str: A complete digraph, for piping to `dot -Tsvg`.
    """
    lines = ["digraph promptc {", "  rankdir=LR;", "  node [shape=box, fontname=\"monospace\"];"]
    shapes = {"task": "doubleoctagon", "rule": "box", "recipe": "component",
              "glossary": "note", "workflow": "box3d", "example": "folder"}

    for item in index.fragments:
        shape = shapes.get(item.kind, "box")
        lines.append(f'  "{item.id}" [shape={shape}];')
    for item in index.fragments:
        for required in item.requires:
            lines.append(f'  "{item.id}" -> "{required}";')

    lines.append("}")
    return "\n".join(lines)
