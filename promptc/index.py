# Fragment index: identity, dependency resolution, trigger routing.
#
# Everything here is a pure function of the source tree. No model, no
# network, no configuration beyond what the fragments declare themselves.

# Imports
import dataclasses

# Local imports
from . import diagnostics
from .diagnostics import Diagnostic, Severity

###########################################################
# Resolution result
###########################################################
@dataclasses.dataclass
class Resolution:
    # Fragments in stable assembly order
    fragments: list = dataclasses.field(default_factory = list)
    # Fragment ids that could not be resolved
    missing: list = dataclasses.field(default_factory = list)
    # Recipes selected by trigger, in the order the triggers were given
    routed: list = dataclasses.field(default_factory = list)

    def ids(self):
        return [fragment.id for fragment in self.fragments]

###########################################################
# Index
###########################################################
class Index:
    def __init__(self, fragments):
        self.fragments = list(fragments)
        self.by_id = {}
        self.duplicates = []

        for fragment in self.fragments:
            if fragment.id in self.by_id:
                self.duplicates.append((fragment, self.by_id[fragment.id]))
            else:
                self.by_id[fragment.id] = fragment

        # trigger name -> [fragments], highest priority first
        self.by_trigger = {}
        for fragment in self.fragments:
            for trigger in fragment.triggers:
                self.by_trigger.setdefault(trigger, []).append(fragment)
        for trigger, matches in self.by_trigger.items():
            matches.sort(key = lambda f: (-f.priority, f.id))

        # glossary term -> [fragment ids that provide it]
        self.providers = {}
        for fragment in self.fragments:
            for term in fragment.provides:
                self.providers.setdefault(term.lower(), []).append(fragment.id)

    def get(self, fragment_id):
        return self.by_id.get(fragment_id)

    def tasks(self):
        return [f for f in self.fragments if f.kind == "task"]

    ###########################################################
    # Dependency closure
    ###########################################################
    # Depth-first transitive closure of `requires`, with a stable order:
    # dependencies always land before the fragment that required them.
    def closure(self, roots, seen = None, missing = None, stack = None):
        seen = seen if seen is not None else []
        missing = missing if missing is not None else []
        stack = stack if stack is not None else set()
        ordered = []

        for root_id in roots:
            fragment = self.by_id.get(root_id)
            if fragment is None:
                if root_id not in missing:
                    missing.append(root_id)
                continue
            if fragment.id in seen or fragment.id in stack:
                continue

            stack.add(fragment.id)
            ordered.extend(self.closure(fragment.requires, seen, missing, stack))
            stack.discard(fragment.id)

            if fragment.id not in seen:
                seen.append(fragment.id)
                ordered.append(fragment)

        return ordered

    ###########################################################
    # Cycle detection
    ###########################################################
    # Returns a list of cycles, each a list of fragment ids.
    def cycles(self):
        found = []
        colour = {}

        def visit(fragment_id, path):
            state = colour.get(fragment_id)
            if state == "done":
                return
            if state == "open":
                # Trim the path back to where the cycle began
                start = path.index(fragment_id)
                cycle = path[start:] + [fragment_id]
                if cycle not in found:
                    found.append(cycle)
                return

            fragment = self.by_id.get(fragment_id)
            if fragment is None:
                return

            colour[fragment_id] = "open"
            for dependency in fragment.requires:
                visit(dependency, path + [fragment_id])
            colour[fragment_id] = "done"

        for fragment in self.fragments:
            visit(fragment.id, [])
        return found

    ###########################################################
    # Routing
    ###########################################################
    # Select recipes for a set of active trigger names. Selection is a
    # dictionary lookup -- there is deliberately no scoring or inference.
    def route(self, triggers):
        selected = []
        for trigger in triggers:
            for fragment in self.by_trigger.get(trigger, []):
                if fragment not in selected:
                    selected.append(fragment)
                # Highest priority wins; only one recipe per trigger
                break
        return selected

    # Triggers claimed by more than one fragment at the same priority
    def trigger_collisions(self):
        collisions = []
        for trigger, matches in sorted(self.by_trigger.items()):
            if len(matches) < 2:
                continue
            top = matches[0].priority
            tied = [f for f in matches if f.priority == top]
            if len(tied) > 1:
                collisions.append((trigger, tied))
        return collisions

    ###########################################################
    # Full resolution for a task
    ###########################################################
    def resolve(self, task_id, triggers = ()):
        task = self.by_id.get(task_id)
        missing = []
        if task is None:
            return Resolution(missing = [task_id])

        routed = self.route(triggers)
        roots = [task.id] + [fragment.id for fragment in routed]

        # Resolve the task closure first so shared rules sort ahead of recipes
        ordered = self.closure(roots, missing = missing)
        return Resolution(fragments = ordered, missing = missing, routed = routed)

    ###########################################################
    # Reachability
    ###########################################################
    # Every fragment reachable from any task, via requires or any trigger.
    def reachable(self):
        roots = [task.id for task in self.tasks()]
        for fragment in self.fragments:
            if fragment.triggers:
                roots.append(fragment.id)
        return {fragment.id for fragment in self.closure(roots)}

    def orphans(self):
        reachable = self.reachable()
        return [f for f in self.fragments if f.id not in reachable]

###########################################################
# Structural diagnostics that belong to the index itself
###########################################################
def index_diagnostics(index):
    found = []

    for duplicate, original in index.duplicates:
        found.append(Diagnostic(
            rule = "PC008",
            severity = Severity.ERROR,
            message = f"Duplicate fragment id `{duplicate.id}` (also defined in {original.path}).",
            file = duplicate.path,
            line = 1,
            fix_hint = "fragment ids must be unique across the library; rename one.",
            data = {"id": duplicate.id, "other": original.path},
        ))

    for cycle in index.cycles():
        found.append(Diagnostic(
            rule = "PC003",
            severity = Severity.ERROR,
            message = "Circular `requires`: " + " -> ".join(cycle),
            file = index.by_id[cycle[0]].path if cycle[0] in index.by_id else "",
            line = 1,
            fix_hint = "break the cycle by extracting the shared part into its own fragment.",
            data = {"cycle": cycle},
        ))

    for trigger, tied in index.trigger_collisions():
        names = ", ".join(f"`{f.id}`" for f in tied)
        found.append(Diagnostic(
            rule = "PC009",
            severity = Severity.ERROR,
            message = f"Trigger `{trigger}` is claimed by {len(tied)} fragments at equal priority: {names}.",
            file = tied[0].path,
            line = 1,
            fix_hint = "give one of them a higher `priority:`, or narrow the triggers so only one matches.",
            data = {"trigger": trigger, "fragments": [f.id for f in tied]},
        ))

    return found
