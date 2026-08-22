"""Corpus discovery, trigger routing, and holdout splitting.

An item is one unit of work: some input files shown to the model, a golden
answer that is never shown, and the trigger names that decide which recipes
get routed. Everything about what those files mean lives in promptc.yaml.

Splitting is deterministic by hash of (seed, stem), so the same corpus
divides the same way on every machine. Without that, a reported pass rate
cannot be compared to the previous one.
"""

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
    """One unit of work from the corpus.

    Attributes:
        stem: Corpus-relative identity, derived by stripping the golden
            suffix from a discovered path.
        inputs: Corpus-relative paths shown to the model.
        golden: Corpus-relative path of the known-good answer. Read only
            for the similarity diagnostic; never placed in a prompt.
        triggers: Detector names for this item, filled in by
            annotate_triggers.
    """

    stem: str
    inputs: list = dataclasses.field(default_factory = list)
    golden: str = ""
    triggers: list = dataclasses.field(default_factory = list)

    def label(self):
        """Return a short display name for progress output."""
        return os.path.basename(self.stem)

    def bucket(self, seed):
        """Return this item's deterministic position in [0, 1).

        Hashing (seed, stem) rather than using a random generator means the
        holdout split is reproducible across runs, machines and Python
        versions.

        Args:
            seed: Corpus seed.

        Returns:
            float: In [0, 1). Stable for a given (seed, stem).
        """
        digest = hashlib.sha256(f"{seed}:{self.stem}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(1 << 64)

    def read_inputs(self, root):
        """Read the input files shown to the model.

        Args:
            root: Absolute corpus root.

        Returns:
            list: (relative_path, text) pairs. A path that does not exist
            is skipped rather than failing the item, so a corpus where only
            some entries carry an optional file still works.
        """
        parts = []
        for relative in self.inputs:
            path = os.path.join(root, relative)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding = "utf-8", errors = "replace") as handle:
                parts.append((relative, handle.read()))
        return parts

    def read_golden(self, root):
        """Read the known-good answer.

        Used only for the similarity diagnostic, which never decides pass
        or fail. This text must never reach a prompt.

        Args:
            root: Absolute corpus root.

        Returns:
            str: The golden text, or empty if the file is absent.
        """
        path = os.path.join(root, self.golden)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding = "utf-8", errors = "replace") as handle:
            return handle.read()

###########################################################
# Discovery
###########################################################
class CorpusError(Exception):
    """The corpus is misconfigured or empty.

    Raised with a message naming the missing setting and what it is for,
    since these faults are almost always a half-written config block.
    """

def _corpus_root(config):
    """Return the absolute corpus root, resolving against the project."""
    root = config.corpus.root or "."
    if not os.path.isabs(root):
        root = os.path.join(config.root, root)
    return root

def discover(config, limit = 0):
    """Find every work item in the corpus.

    Golden files define the item set: each match of `corpus.discover` is one
    item, and its stem comes from stripping `corpus.golden_suffix`.

    Args:
        config: Loaded Config.
        limit: Stop after this many items. Zero means no limit.

    Returns:
        tuple: (items, absolute_root). Items are sorted by path, so a
        `limit` always takes the same ones.

    Raises:
        CorpusError: `discover` or `golden_suffix` is unset, or the root
            does not exist.
    """
    corpus = config.corpus
    if not corpus.discover:
        raise CorpusError(
            "promptc.yaml: `corpus.discover` is not set, so there is nothing to evaluate.\n"
            "Set it to a glob that finds your golden files, e.g. \"**/*.expected.txt\".")
    if not corpus.golden_suffix:
        raise CorpusError(
            "promptc.yaml: `corpus.golden_suffix` is not set.\n"
            "Set it to the suffix stripped from a golden path to get the item stem, "
            "e.g. \".expected.txt\".")

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
def resolve_triggers(config, item, root):
    """Ask the project which patterns fired for one item.

    A non-zero exit means "no triggers", not a hard failure: a detector
    that legitimately finds nothing must not abort a run of a thousand
    items. A missing binary and a timeout are treated the same way.

    Args:
        config: Loaded Config, supplying `corpus.triggers_command`.
        item: The Item to inspect. `{stem}`, `{golden}` and `{input}` are
            substituted into the command.
        root: Working directory for the subprocess.

    Returns:
        list: Trigger names, one per non-empty output line. Empty when no
        command is configured or the command failed.
    """
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
    """Fill in `triggers` on every item, in place.

    Args:
        config: Loaded Config.
        items: Items to annotate.
        root: Working directory for the detector subprocess.

    Returns:
        list: The same items, for chaining.
    """
    for item in items:
        item.triggers = resolve_triggers(config, item, root)
    return items

###########################################################
# Stratification and holdout
###########################################################
def stratify(items, key = "triggers"):
    """Group items so a sample can cover every routed recipe.

    Args:
        items: Items to group.
        key: `triggers` groups by primary trigger; anything else puts
            everything in one bucket.

    Returns:
        dict: Bucket name to items. Items with no triggers land under
        `<none>`, which keeps them visible rather than dropping them.
    """
    groups = {}
    for item in items:
        if key == "triggers":
            bucket = item.triggers[0] if item.triggers else "<none>"
        else:
            bucket = "<all>"
        groups.setdefault(bucket, []).append(item)
    return groups

def holdout(items, fraction, seed):
    """Split items into tuning and reporting sets.

    Tune prompts on dev; report on test. Tuning against everything overfits
    the prompt to those specific items and teaches you nothing about the
    next one.

    Args:
        items: Items to split.
        fraction: Share assigned to test, in [0, 1].
        seed: Corpus seed, making the split reproducible.

    Returns:
        tuple: (dev, test). Disjoint, and together the whole input.
    """
    dev, test = [], []
    for item in items:
        if item.bucket(seed) < fraction:
            test.append(item)
        else:
            dev.append(item)
    return dev, test

def sample(items, per_group, seed, key = "triggers"):
    """Take a stratified sample, deterministically.

    Args:
        items: Items to sample from.
        per_group: Maximum per stratum. Zero returns everything.
        seed: Corpus seed, so the same items are chosen each run.
        key: Stratification key, passed to stratify.

    Returns:
        list: The selected items, grouped by stratum in sorted order.
    """
    selected = []
    for bucket, members in sorted(stratify(items, key).items()):
        ordered = sorted(members, key = lambda item: item.bucket(seed))
        selected.extend(ordered[:per_group] if per_group else ordered)
    return selected
