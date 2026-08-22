# Corpus discovery, trigger routing, and holdout splitting.
#
# An item is one unit of work: some input files shown to the model, a golden
# answer that is never shown, and the trigger names that decide which recipes
# get routed. Everything about what those files mean lives in promptc.yaml.

# Imports
import dataclasses
import glob
import hashlib
import os
import subprocess

###########################################################
# Item
###########################################################
@dataclasses.dataclass
class Item:
    # Stem is the corpus-relative identity of the work item
    stem: str
    inputs: list = dataclasses.field(default_factory = list)
    golden: str = ""
    triggers: list = dataclasses.field(default_factory = list)

    def label(self):
        return os.path.basename(self.stem)

    # Deterministic bucket in [0,1) from a seed -- used for the holdout split
    # so the same seed always yields the same partition.
    def bucket(self, seed):
        digest = hashlib.sha256(f"{seed}:{self.stem}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(1 << 64)

    def read_inputs(self, root):
        parts = []
        for relative in self.inputs:
            path = os.path.join(root, relative)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding = "utf-8", errors = "replace") as handle:
                parts.append((relative, handle.read()))
        return parts

    def read_golden(self, root):
        path = os.path.join(root, self.golden)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding = "utf-8", errors = "replace") as handle:
            return handle.read()

###########################################################
# Discovery
###########################################################
class CorpusError(Exception):
    pass

def _corpus_root(config):
    root = config.corpus.root or "."
    if not os.path.isabs(root):
        root = os.path.join(config.root, root)
    return root

def discover(config, limit = 0):
    corpus = config.corpus
    if not corpus.discover:
        raise CorpusError(
            "promptc.yaml: `corpus.discover` is not set, so there is nothing to evaluate.\n"
            "Set it to a glob that finds your golden files, e.g. \"**/*.keep.cpp\".")
    if not corpus.golden_suffix:
        raise CorpusError(
            "promptc.yaml: `corpus.golden_suffix` is not set.\n"
            "Set it to the suffix stripped from a golden path to get the item stem, "
            "e.g. \".keep.cpp\".")

    root = _corpus_root(config)
    if not os.path.isdir(root):
        raise CorpusError(f"Corpus root does not exist: {root}")

    pattern = os.path.join(root, corpus.discover)
    matches = sorted(glob.glob(pattern, recursive = True))

    items = []
    for golden_path in matches:
        relative = os.path.relpath(golden_path, root)
        if not relative.endswith(corpus.golden_suffix):
            continue
        stem = relative[: -len(corpus.golden_suffix)]
        inputs = [template.replace("{stem}", stem) for template in corpus.inputs]
        items.append(Item(stem = stem, inputs = inputs, golden = relative))
        if limit and len(items) >= limit:
            break

    return items, root

###########################################################
# Trigger routing
###########################################################
# Ask the project which patterns fired for an item. One trigger name per
# line on stdout; a non-zero exit means "no triggers", not a hard failure,
# so a detector that legitimately finds nothing does not abort a run.
def resolve_triggers(config, item, root):
    command_template = config.corpus.triggers_command
    if not command_template:
        return []

    substitutions = {
        "{stem}": item.stem,
        "{golden}": item.golden,
        "{input}": item.inputs[0] if item.inputs else "",
    }

    command = []
    for part in command_template:
        for key, value in substitutions.items():
            part = part.replace(key, value)
        command.append(part)

    try:
        completed = subprocess.run(
            command, cwd = root, capture_output = True, text = True, timeout = 60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if completed.returncode != 0:
        return []

    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

def annotate_triggers(config, items, root):
    for item in items:
        item.triggers = resolve_triggers(config, item, root)
    return items

###########################################################
# Stratification and holdout
###########################################################
# Group items by their primary trigger so a sample covers every recipe
# rather than over-representing whichever pattern is most common.
def stratify(items, key = "triggers"):
    groups = {}
    for item in items:
        if key == "triggers":
            bucket = item.triggers[0] if item.triggers else "<none>"
        else:
            bucket = "<all>"
        groups.setdefault(bucket, []).append(item)
    return groups

# Split into (dev, test). Tuning happens on dev; numbers get reported on
# test. Without this you overfit the prompt to the corpus and learn nothing.
def holdout(items, fraction, seed):
    dev, test = [], []
    for item in items:
        if item.bucket(seed) < fraction:
            test.append(item)
        else:
            dev.append(item)
    return dev, test

# Take up to `per_group` items from each stratum, deterministically.
def sample(items, per_group, seed, key = "triggers"):
    selected = []
    for bucket, members in sorted(stratify(items, key).items()):
        ordered = sorted(members, key = lambda item: item.bucket(seed))
        selected.extend(ordered[:per_group] if per_group else ordered)
    return selected
