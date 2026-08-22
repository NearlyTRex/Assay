# Assembly: fragments -> a single prompt, plus a manifest.
#
# Assembly is deterministic. The same source tree, task and trigger set
# always produce byte-identical output, so a diff between two builds means
# a real change rather than reordering noise.

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
    task: str
    triggers: list
    fragments: list
    text: str
    missing: list = dataclasses.field(default_factory = list)
    routed: list = dataclasses.field(default_factory = list)
    # Character offset of each fragment's body within `text`
    offsets: dict = dataclasses.field(default_factory = dict)

    def digest(self):
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    def manifest(self, counter = None):
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
        return json.dumps(self.manifest(counter), indent = 2)

###########################################################
# Emission
###########################################################
# Fragments arrive in dependency order; sort into kind bands while keeping
# dependency order stable inside each band.
def order_fragments(fragments):
    decorated = [(KIND_ORDER.get(item.kind, 99), position, item)
                 for position, item in enumerate(fragments)]
    decorated.sort(key = lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in decorated]

# Strip suppression comments and normalise trailing whitespace so the same
# body always contributes the same bytes.
def render_body(item):
    body = fragment_module.SUPPRESS_PATTERN.sub("", item.body)
    return body.strip("\n")

def assemble(index, task_id, triggers = (), heading = True):
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
