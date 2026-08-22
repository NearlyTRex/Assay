"""Assembly: fragments -> a single prompt, plus a manifest.

Assembly is deterministic. The same source tree, task and trigger set
always produce byte-identical output, so a diff between two builds means a
real change rather than reordering noise. That is what makes a `pass@k`
figure comparable to the previous one.
"""

# Imports
import dataclasses
import hashlib
import json

# Local imports
from . import fragment as fragment_module

# Order fragments are emitted in. Rules before recipes means shared
# constraints are stated before the pattern-specific steps that assume them.
KIND_ORDER = {
    "glossary": 0,
    "rule": 1,
    "workflow": 2,
    "recipe": 3,
    "example": 4,
    "task": 5,
}

###########################################################
# Assembly
###########################################################
@dataclasses.dataclass
class Assembly:
    """One assembled prompt and the record of how it was built.

    Attributes:
        task: Id of the task this was assembled for.
        triggers: Trigger names that were active.
        fragments: Included fragments, in emission order.
        text: The prompt. Always ends with exactly one newline.
        missing: Ids named by `requires` that no fragment provides.
        routed: Recipes selected by trigger, excluding their transitive
            dependencies.
        offsets: Fragment id to the character offset of its body within
            `text`.
    """

    task: str
    triggers: list
    fragments: list
    text: str
    missing: list = dataclasses.field(default_factory = list)
    routed: list = dataclasses.field(default_factory = list)
    offsets: dict = dataclasses.field(default_factory = dict)

    def ids(self):
        """Return the included fragment ids, in emission order."""
        return [item.id for item in self.fragments]

    def digest(self):
        """Return a short content hash of the assembled text.

        Returns:
            str: First 16 hex characters of the SHA-256. Long enough to
            compare two builds by eye, and recorded in the manifest so a
            changed prompt is visible without diffing it.
        """
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    def manifest(self, counter = None):
        """Build the record of what went into this assembly.

        Args:
            counter: Optional Counter. When given, per-fragment and total
                token counts are included along with the tokenizer's label,
                so a reader can tell whether the figures are exact.

        Returns:
            dict: Always carries task, triggers, routed, fragments, chars
            and digest. Token fields appear only with a counter, and
            `missing` only when something failed to resolve -- so its
            presence is itself the signal.
        """
        entry_list = []
        for item in self.fragments:
            entry = {
                "id": item.id,
                "kind": item.kind,
                "path": item.path,
                "offset": self.offsets.get(item.id, 0),
            }
            if counter is not None:
                entry["tokens"] = counter.count(item.body)
            entry_list.append(entry)

        manifest = {
            "task": self.task,
            "triggers": list(self.triggers),
            "routed": [item.id for item in self.routed],
            "fragments": entry_list,
            "chars": len(self.text),
            "digest": self.digest(),
        }
        if counter is not None:
            manifest["tokens"] = counter.count(self.text)
            manifest["tokenizer"] = counter.describe()
        if self.missing:
            manifest["missing"] = list(self.missing)
        return manifest

    def manifest_json(self, counter = None):
        """Return the manifest as indented JSON."""
        return json.dumps(self.manifest(counter), indent = 2)

###########################################################
# Emission
###########################################################
def order_fragments(fragments):
    """Sort resolved fragments into kind bands.

    Fragments arrive in dependency order. Banding by kind puts glossary
    terms before the rules that use them, and shared rules before the
    pattern-specific recipes that assume them, while dependency order is
    preserved *within* each band.

    Args:
        fragments: Fragments in dependency order.

    Returns:
        list: The same fragments, reordered. An unknown kind sorts last.
    """
    decorated = [(KIND_ORDER.get(item.kind, 99), position, item)
                 for position, item in enumerate(fragments)]
    decorated.sort(key = lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in decorated]

def render_body(item):
    """Return a fragment's body as it should appear in the prompt.

    Suppression comments are removed and surrounding blank lines are
    normalised, so the same body always contributes the same bytes.

    Args:
        item: Fragment to render.

    Returns:
        str: Body text, with no leading or trailing newlines.
    """
    body = fragment_module.SUPPRESS_PATTERN.sub("", item.body)
    return body.strip("\n")

def assemble(index, task_id, triggers = (), heading = True):
    """Assemble a task and its routed recipes into one prompt.

    Args:
        index: Built Index to resolve against.
        task_id: Id of the task fragment. An unknown id yields an empty
            assembly with the id recorded in `missing`.
        triggers: Active trigger names. Order does not matter -- routing
            sorts, so the prompt depends on the set.
        heading: Emit a markdown heading above each non-task fragment.
            The task's own body closes the prompt without one.

    Returns:
        Assembly: Deterministic for a given (index, task, trigger set).
    """
    resolution = index.resolve(task_id, triggers)
    ordered = order_fragments(resolution.fragments)

    chunks = []
    offsets = {}
    cursor = 0

    for item in ordered:
        piece = ""
        if heading and item.kind != "task":
            title = item.title or item.id
            piece += f"## {title}\n\n"
        piece += render_body(item) + "\n"

        offsets[item.id] = cursor + (len(piece) - len(render_body(item)) - 1)
        chunks.append(piece)
        cursor += len(piece) + 1

    text = "\n".join(chunks).strip() + "\n"

    return Assembly(
        task = task_id,
        triggers = list(triggers),
        fragments = ordered,
        text = text,
        missing = resolution.missing,
        routed = resolution.routed,
        offsets = offsets,
    )
