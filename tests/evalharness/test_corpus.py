# Tests for promptc/evalharness/corpus.py -- discovery and splitting.
#
# The holdout split must be reproducible across runs and machines, or a
# reported pass rate cannot be compared to the previous one.

# Imports
import os

# Third party
import pytest

# Local imports
from promptc import config as config_module
from promptc.evalharness import corpus as corpus_module

###########################################################
# Fixtures
###########################################################
CORPUS_CONFIG = """
library: promptlib
contracts: contracts
corpus:
  root: corpus
  discover: "**/*.keep.txt"
  golden_suffix: ".keep.txt"
  inputs: ["{stem}.txt", "{stem}.meta"]
  holdout: 0.2
  seed: 20260822
"""

@pytest.fixture
def corpus_project(project, write):
    write(os.path.join(project, "promptc.yaml"), CORPUS_CONFIG)
    for name in ("alpha", "beta", "gamma"):
        write(os.path.join(project, "corpus", f"{name}.keep.txt"), f"golden {name}\n")
        write(os.path.join(project, "corpus", f"{name}.txt"), f"input {name}\n")
        write(os.path.join(project, "corpus", f"{name}.meta"), f"meta {name}\n")
    return config_module.load_config(os.path.join(project, "promptc.yaml"))

###########################################################
# Discovery
###########################################################
def test_discover_finds_items_and_derives_stems(corpus_project):
    items, root = corpus_module.discover(corpus_project)
    assert sorted(item.stem for item in items) == ["alpha", "beta", "gamma"]
    assert root.endswith("corpus")

def test_discover_templates_input_paths(corpus_project):
    items, _ = corpus_module.discover(corpus_project)
    alpha = next(item for item in items if item.stem == "alpha")
    assert alpha.inputs == ["alpha.txt", "alpha.meta"]
    assert alpha.golden == "alpha.keep.txt"

def test_discover_respects_limit(corpus_project):
    items, _ = corpus_module.discover(corpus_project, limit = 2)
    assert len(items) == 2

def test_reading_inputs_skips_absent_files(corpus_project, project):
    os.unlink(os.path.join(project, "corpus", "alpha.meta"))
    items, root = corpus_module.discover(corpus_project)
    alpha = next(item for item in items if item.stem == "alpha")
    parts = alpha.read_inputs(root)
    assert [name for name, _ in parts] == ["alpha.txt"]

def test_reading_golden(corpus_project):
    items, root = corpus_module.discover(corpus_project)
    alpha = next(item for item in items if item.stem == "alpha")
    assert alpha.read_golden(root).strip() == "golden alpha"

###########################################################
# Configuration errors
###########################################################
def test_missing_discover_is_an_error(project, write):
    write(os.path.join(project, "promptc.yaml"), "corpus:\n  root: corpus\n")
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    with pytest.raises(corpus_module.CorpusError) as caught:
        corpus_module.discover(config)
    assert "corpus.discover" in str(caught.value)

def test_missing_golden_suffix_is_an_error(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        corpus:
          root: corpus
          discover: "**/*.keep.txt"
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    with pytest.raises(corpus_module.CorpusError) as caught:
        corpus_module.discover(config)
    assert "golden_suffix" in str(caught.value)

def test_missing_root_is_an_error(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        corpus:
          root: nowhere
          discover: "**/*.keep.txt"
          golden_suffix: ".keep.txt"
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    with pytest.raises(corpus_module.CorpusError):
        corpus_module.discover(config)

###########################################################
# Holdout
###########################################################
def test_bucket_is_deterministic():
    item = corpus_module.Item(stem = "some/function")
    assert item.bucket(1) == item.bucket(1)
    assert 0.0 <= item.bucket(1) < 1.0

def test_bucket_varies_with_seed():
    item = corpus_module.Item(stem = "some/function")
    assert item.bucket(1) != item.bucket(2)

def test_holdout_is_reproducible(corpus_project):
    items, _ = corpus_module.discover(corpus_project)
    first = corpus_module.holdout(items, 0.5, seed = 7)
    second = corpus_module.holdout(items, 0.5, seed = 7)
    assert [i.stem for i in first[0]] == [i.stem for i in second[0]]
    assert [i.stem for i in first[1]] == [i.stem for i in second[1]]

def test_holdout_partitions_without_overlap(corpus_project):
    items, _ = corpus_module.discover(corpus_project)
    dev, test = corpus_module.holdout(items, 0.5, seed = 7)
    assert set(i.stem for i in dev).isdisjoint(i.stem for i in test)
    assert len(dev) + len(test) == len(items)

def test_holdout_of_zero_puts_everything_in_dev(corpus_project):
    items, _ = corpus_module.discover(corpus_project)
    dev, test = corpus_module.holdout(items, 0.0, seed = 7)
    assert len(test) == 0
    assert len(dev) == len(items)

###########################################################
# Stratification
###########################################################
def test_stratify_groups_by_primary_trigger():
    items = [
        corpus_module.Item(stem = "a", triggers = ["x"]),
        corpus_module.Item(stem = "b", triggers = ["x"]),
        corpus_module.Item(stem = "c", triggers = ["y"]),
        corpus_module.Item(stem = "d", triggers = []),
    ]
    groups = corpus_module.stratify(items)
    assert sorted(groups) == ["<none>", "x", "y"]
    assert len(groups["x"]) == 2

def test_sample_takes_a_fixed_number_per_group():
    items = [corpus_module.Item(stem = f"a{n}", triggers = ["x"]) for n in range(10)]
    items += [corpus_module.Item(stem = f"b{n}", triggers = ["y"]) for n in range(10)]
    selected = corpus_module.sample(items, per_group = 3, seed = 1)
    groups = corpus_module.stratify(selected)
    assert len(groups["x"]) == 3
    assert len(groups["y"]) == 3

def test_sample_is_deterministic():
    items = [corpus_module.Item(stem = f"a{n}", triggers = ["x"]) for n in range(10)]
    first = [i.stem for i in corpus_module.sample(items, 3, seed = 1)]
    second = [i.stem for i in corpus_module.sample(items, 3, seed = 1)]
    assert first == second

def test_sample_of_zero_returns_everything():
    items = [corpus_module.Item(stem = f"a{n}", triggers = ["x"]) for n in range(5)]
    assert len(corpus_module.sample(items, 0, seed = 1)) == 5

###########################################################
# Trigger routing
###########################################################
@pytest.mark.integration
def test_triggers_command_output_becomes_trigger_names(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        corpus:
          root: corpus
          discover: "**/*.keep.txt"
          golden_suffix: ".keep.txt"
          triggers_command: ["printf", "pattern_x\\npattern_y\\n"]
    """)
    write(os.path.join(project, "corpus", "alpha.keep.txt"), "golden\n")
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))

    items, root = corpus_module.discover(config)
    corpus_module.annotate_triggers(config, items, root)
    assert items[0].triggers == ["pattern_x", "pattern_y"]

@pytest.mark.integration
def test_triggers_command_runs_from_the_project_root(project, write):
    """A project-relative script must mean the same under `triggers_command`
    as it does under `verifiers` -- both run from the project root."""
    write(os.path.join(project, "scripts", "detect.sh"),
          "#!/bin/bash\necho from_project_root\n")
    os.chmod(os.path.join(project, "scripts", "detect.sh"), 0o755)
    write(os.path.join(project, "promptc.yaml"), """
        corpus:
          root: corpus
          discover: "**/*.keep.txt"
          golden_suffix: ".keep.txt"
          triggers_command: ["./scripts/detect.sh", "{stem}"]
    """)
    write(os.path.join(project, "corpus", "alpha.keep.txt"), "golden\n")
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))

    items, root = corpus_module.discover(config)
    corpus_module.annotate_triggers(config, items, root)
    assert items[0].triggers == ["from_project_root"]

@pytest.mark.integration
def test_failing_triggers_command_means_no_triggers(project, write):
    """A detector that finds nothing exits non-zero; that is not a run failure."""
    write(os.path.join(project, "promptc.yaml"), """
        corpus:
          root: corpus
          discover: "**/*.keep.txt"
          golden_suffix: ".keep.txt"
          triggers_command: ["false"]
    """)
    write(os.path.join(project, "corpus", "alpha.keep.txt"), "golden\n")
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))

    items, root = corpus_module.discover(config)
    corpus_module.annotate_triggers(config, items, root)
    assert items[0].triggers == []

@pytest.mark.integration
def test_missing_triggers_command_binary_is_survivable(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        corpus:
          root: corpus
          discover: "**/*.keep.txt"
          golden_suffix: ".keep.txt"
          triggers_command: ["definitely-not-a-real-binary-xyz"]
    """)
    write(os.path.join(project, "corpus", "alpha.keep.txt"), "golden\n")
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))

    items, root = corpus_module.discover(config)
    corpus_module.annotate_triggers(config, items, root)
    assert items[0].triggers == []
