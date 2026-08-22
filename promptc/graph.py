# Dependency and coverage reporting.
#
# Answers the questions you ask while refactoring: what does this task
# actually pull in, what is nothing routing to, and which triggers have no
# recipe behind them.

# Imports
import json

###########################################################
# Coverage
###########################################################
def coverage(index, config = None):
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
    counts = {}
    for item in index.fragments:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return dict(sorted(counts.items()))

###########################################################
# Rendering
###########################################################
def render_json(index):
    return json.dumps(coverage(index), indent = 2)

def render_text(index, show_orphans_only = False):
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
