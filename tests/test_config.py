# Tests for promptc/config.py -- the domain boundary.
#
# Config errors must name the file and the remedy, because this is the one
# file a user hand-edits.

# Imports
import os

# Third party
import pytest

# Local imports
from promptc import config as config_module

###########################################################
# Discovery
###########################################################
def test_find_config_walks_upward(project):
    nested = os.path.join(project, "a", "b", "c")
    os.makedirs(nested, exist_ok = True)
    found = config_module.find_config(nested)
    assert found == os.path.join(project, "promptc.yaml")

def test_find_config_stops_at_the_nearest_one(project):
    """A nested project must not pick up a parent's config."""
    nested = os.path.join(project, "inner")
    os.makedirs(nested, exist_ok = True)
    with open(os.path.join(nested, "promptc.yaml"), "w", encoding = "utf-8") as handle:
        handle.write("library: other\n")
    assert config_module.find_config(nested) == os.path.join(nested, "promptc.yaml")

def test_explicit_missing_config_raises_with_a_remedy(tmp_path):
    """A typo'd --config is a user error, not a traceback."""
    with pytest.raises(config_module.ConfigError) as caught:
        config_module.load_config(os.path.join(str(tmp_path), "nope.yaml"))
    assert "not found" in str(caught.value)
    assert "promptc init" in str(caught.value)

def test_top_level_must_be_a_mapping(project, write):
    write(os.path.join(project, "promptc.yaml"), "- just\n- a\n- list\n")
    with pytest.raises(config_module.ConfigError) as caught:
        config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert "mapping" in str(caught.value)

###########################################################
# Defaults
###########################################################
def test_defaults_apply(project, write):
    write(os.path.join(project, "promptc.yaml"), "{}\n")
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert config.library == "promptlib"
    assert config.contracts == "contracts"
    assert config.verifiers == []
    assert config.hedges  # falls back to DEFAULT_HEDGES
    assert config.threshold("PC100") == config_module.DEFAULT_THRESHOLDS["PC100"]

def test_threshold_override(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        thresholds:
          PC100: 1.5
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert config.threshold("PC100") == 1.5
    # Unspecified rules keep their defaults
    assert config.threshold("PC102") == config_module.DEFAULT_THRESHOLDS["PC102"]

###########################################################
# Verifiers
###########################################################
def test_verifier_needs_argv_command(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        verifiers:
          - id: broken
            command: "./build.sh {file}"
    """)
    with pytest.raises(config_module.ConfigError) as caught:
        config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert "argv form" in str(caught.value)

def test_verifier_needs_an_id(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        verifiers:
          - command: ["./build.sh"]
    """)
    with pytest.raises(config_module.ConfigError):
        config_module.load_config(os.path.join(project, "promptc.yaml"))

def test_verifier_lookup(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        verifiers:
          - id: builds
            command: ["true"]
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert config.verifier("builds").command == ["true"]
    assert config.verifier("nope") is None

###########################################################
# Profiles
###########################################################
def test_profile_budget_subtracts_both_reserves(project, load_config):
    profile = load_config().profile("small")
    assert profile.budget() == 2000 - 200 - 200

def test_non_positive_budget_is_a_config_error(project, write):
    """context 1,000 with the default output_reserve of 2,048 is incoherent;
    catching it here stops PC004 blaming the prompt for a config fault."""
    write(os.path.join(project, "promptc.yaml"), """
        profiles:
          tiny:
            context: 1000
    """)
    with pytest.raises(config_module.ConfigError) as caught:
        config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert "no room for a prompt" in str(caught.value)
    assert "output_reserve" in str(caught.value)

def test_profile_raw_is_preserved_for_backends(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        profiles:
          shell:
            context: 8000
            backend: command
            command: ["./ask.sh"]
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert config.profile("shell").raw["backend"] == "command"
    assert config.profile("shell").raw["command"] == ["./ask.sh"]

###########################################################
# Eval settings
###########################################################
def test_eval_defaults(project, load_config):
    settings = load_config().eval
    assert settings.extract == "fence"
    assert settings.attempts == 1
    assert settings.seeds == [1000]

def test_eval_seed_list_generated_for_attempts(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        eval:
          attempts: 5
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert len(config.eval.seeds) == 5
    assert len(set(config.eval.seeds)) == 5

def test_too_few_seeds_is_an_error(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        eval:
          attempts: 5
          seeds: [1, 2]
    """)
    with pytest.raises(config_module.ConfigError) as caught:
        config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert "reproducible" in str(caught.value)

def test_invalid_extract_mode_rejected(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        eval:
          extract: telepathy
    """)
    with pytest.raises(config_module.ConfigError):
        config_module.load_config(os.path.join(project, "promptc.yaml"))

###########################################################
# Vocabulary
###########################################################
def test_vocabulary_scalar_becomes_a_list(project, write):
    write(os.path.join(project, "promptc.yaml"), """
        vocabulary:
          "keep file": keepfile
    """)
    config = config_module.load_config(os.path.join(project, "promptc.yaml"))
    assert config.vocabulary["keep file"] == ["keepfile"]
