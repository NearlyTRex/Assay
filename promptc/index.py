"""Fragment index: identity, dependency resolution, trigger routing.

Everything here is a pure function of the source tree. No model, no
network, no configuration beyond what the fragments declare themselves.

Two properties matter throughout. Dependency order is stable, so an
assembly built twice is byte-identical. And routing is a dictionary lookup
with no scoring or inference -- a detector emits a name, that name selects
a recipe, and nothing in between exercises judgement.
"""

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
    """What a task resolved to, before assembly renders it.

    Attributes:
        fragments: Every fragment to include, in dependency order --
            a fragment always follows everything it requires.
        missing: Ids named by `requires` that no fragment provides. Non-
            empty is PC002's problem; resolution itself does not fail.
        routed: The recipes selected by trigger, excluding their transitive
            dependencies. Recorded separately so a manifest can say what
            the triggers actually pulled in.
    """

    fragments: list = dataclasses.field(default_factory = list)
    missing: list = dataclasses.field(default_factory = list)
    routed: list = dataclasses.field(default_factory = list)

    def ids(self):
        """Return the resolved fragment ids, in assembly order."""
        return [fragment.id for fragment in self.fragments]

###########################################################
# Index
###########################################################
class Index:
    """Lookup tables over a parsed library.

    Attributes:
        fragments: Every fragment, in the order load_library returned them.
        by_id: Id to fragment. On a duplicate id the first wins, and the
            collision is recorded in `duplicates` for PC008.
        duplicates: (duplicate, original) pairs.
        by_trigger: Trigger name to candidate fragments, highest priority
            first.
        providers: Lowercased glossary term to the ids of fragments
            declaring it.
    """

    def __init__(self, fragments):
        """Build the lookup tables.

        Duplicate ids are recorded rather than raising, so a library with
        one collision still reports everything else wrong with it.

        Args:
            fragments: Parsed Fragment objects.
        """
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
        """Return the fragment with this id, or None."""
        return self.by_id.get(fragment_id)

    def tasks(self):
        """Return every task fragment, in library order."""
        return [f for f in self.fragments if f.kind == "task"]

    ###########################################################
    # Dependency closure
    ###########################################################
    def closure(self, roots, seen = None, missing = None, stack = None):
        """Resolve `requires` transitively, dependencies first.

        Depth-first with a stable order: a fragment always lands after
        everything it requires, and a shared dependency appears once.

        A cycle is survived rather than raised on -- the `stack` guard
        stops the recursion, and reporting the cycle is PC003's job. That
        matters because check must be able to report a cycle *and*
        everything else in the same run.

        Args:
            roots: Fragment ids to resolve from.
            seen: Accumulator of already-emitted ids. Callers pass nothing;
                recursion threads it.
            missing: Accumulator for unresolvable ids. Pass a list to
                collect them.
            stack: Ids currently being visited, for cycle detection.

        Returns:
            list: Fragment objects in dependency order.
        """
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
    def cycles(self):
        """Find dependency cycles in `requires`.

        Returns:
            list: Each entry is a list of ids forming a cycle, with the
            entry point repeated at the end so the loop reads as a path.
            Empty when the graph is acyclic.
        """
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
    def route(self, triggers):
        """Select the recipes for a set of active trigger names.

        Selection is a dictionary lookup -- there is deliberately no
        scoring or inference. One recipe per trigger, highest priority
        winning; a tie is PC009's problem, not something resolved here by
        file order.

        Args:
            triggers: Trigger names, typically from a detector subprocess.
                Unknown names select nothing rather than erroring.

        Returns:
            list: Fragments, sorted by descending priority then id.
        """
        selected = []
        for trigger in triggers:
            for fragment in self.by_trigger.get(trigger, []):
                if fragment not in selected:
                    selected.append(fragment)
                # Highest priority wins; only one recipe per trigger
                break

        # Sorted, not left in trigger order: triggers usually arrive from a
        # detector subprocess whose output order is not guaranteed stable,
        # and assembly must depend on the *set* of triggers rather than the
        # order they happened to be printed in.
        selected.sort(key = lambda fragment: (-fragment.priority, fragment.id))
        return selected

    def trigger_collisions(self):
        """Find triggers claimed by several fragments at equal priority.

        Returns:
            list: (trigger, tied_fragments) pairs, sorted by trigger. A
            trigger with several candidates at *different* priorities is
            not a collision -- priority resolved it.
        """
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
        """Resolve a task plus its routed recipes into an ordered list.

        Args:
            task_id: Id of the task fragment to resolve.
            triggers: Active trigger names.

        Returns:
            Resolution: With `missing` naming an unknown task id, in which
            case `fragments` is empty.
        """
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
    def reachable(self):
        """Return the ids of every fragment some task or trigger can reach.

        A fragment with any trigger counts as reachable even when no task
        currently routes it, because whether a detector will emit that name
        is not knowable from the source tree.

        Returns:
            set: Reachable fragment ids.
        """
        roots = [task.id for task in self.tasks()]
        for fragment in self.fragments:
            if fragment.triggers:
                roots.append(fragment.id)
        return {fragment.id for fragment in self.closure(roots)}

    def orphans(self):
        """Return fragments nothing can reach.

        Returns:
            list: Fragments in library order. Usually dead weight, and
            occasionally a routing rule someone forgot to add -- which is
            why this is a warning (PC010) rather than an error.
        """
        reachable = self.reachable()
        return [f for f in self.fragments if f.id not in reachable]

###########################################################
# Structural diagnostics that belong to the index itself
###########################################################
def index_diagnostics(index):
    """Report the faults visible from the index alone.

    These are the checks that need the whole library at once rather than
    one fragment at a time: identity collisions, dependency cycles, and
    ambiguous routing.

    Args:
        index: A built Index.

    Returns:
        list: Diagnostics for PC008 (duplicate id), PC003 (cycle) and
        PC009 (trigger collision). All ERROR severity.
    """
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
