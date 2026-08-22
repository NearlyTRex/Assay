# Tests for promptc/evalharness/runner.py -- model backends.
#
# No test here contacts a real model. The `command` backend exists partly as
# a production escape hatch and partly so this file can exercise the harness
# against a deterministic stand-in. See docs/testing.md.

# Imports
import os
import sys

# Third party
import pytest

# Local imports
from promptc import config as config_module
from promptc.evalharness import runner

###########################################################
# Sampling
###########################################################
def test_sampling_defaults_are_low_temperature():
    sampling = runner.Sampling()
    assert sampling.temperature <= 0.5
    assert sampling.grammar == ""
    assert sampling.stop == []

###########################################################
# Backend construction
###########################################################
def test_llamacpp_inferred_without_a_model_name():
    profile = config_module.Profile(name = "p", endpoint = "http://127.0.0.1:8080")
    backend = runner.make_backend(profile, {})
    assert isinstance(backend, runner.LlamaCppBackend)

def test_openai_inferred_when_a_model_is_named():
    profile = config_module.Profile(
        name = "p", endpoint = "http://127.0.0.1:8080", model = "gpt-x")
    backend = runner.make_backend(profile, {"model": "gpt-x"})
    assert isinstance(backend, runner.OpenAIBackend)

def test_explicit_backend_wins():
    profile = config_module.Profile(name = "p", endpoint = "http://x", model = "m")
    backend = runner.make_backend(profile, {"backend": "llamacpp"})
    assert isinstance(backend, runner.LlamaCppBackend)

def test_llamacpp_without_endpoint_is_an_error():
    profile = config_module.Profile(name = "p")
    with pytest.raises(runner.BackendError) as caught:
        runner.make_backend(profile, {"backend": "llamacpp"})
    assert "endpoint" in str(caught.value)

def test_command_backend_without_command_is_an_error():
    profile = config_module.Profile(name = "p")
    with pytest.raises(runner.BackendError) as caught:
        runner.make_backend(profile, {"backend": "command"})
    assert "command" in str(caught.value)

def test_unknown_backend_lists_the_valid_ones():
    profile = config_module.Profile(name = "p", endpoint = "http://x")
    with pytest.raises(runner.BackendError) as caught:
        runner.make_backend(profile, {"backend": "telepathy"})
    assert "llamacpp" in str(caught.value)

###########################################################
# Command backend
###########################################################
@pytest.mark.integration
def test_command_backend_returns_stdout():
    backend = runner.CommandBackend([sys.executable, "-c", "print('hello')"])
    generation = backend.generate("ignored", runner.Sampling())
    assert generation.ok
    assert generation.text.strip() == "hello"

@pytest.mark.integration
def test_command_backend_receives_the_prompt_on_stdin():
    backend = runner.CommandBackend(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"])
    generation = backend.generate("hello", runner.Sampling())
    assert generation.text.strip() == "HELLO"

@pytest.mark.integration
def test_command_backend_substitutes_the_seed():
    backend = runner.CommandBackend([sys.executable, "-c", "print('seed={seed}')"])
    generation = backend.generate("ignored", runner.Sampling(seed = 4242))
    assert "seed=4242" in generation.text

@pytest.mark.integration
def test_command_backend_reports_a_non_zero_exit():
    backend = runner.CommandBackend(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    generation = backend.generate("ignored", runner.Sampling())
    assert not generation.ok
    assert "exited 3" in generation.error
    assert "boom" in generation.error

@pytest.mark.integration
def test_command_backend_reports_a_missing_binary():
    backend = runner.CommandBackend(["definitely-not-a-real-binary-xyz"])
    generation = backend.generate("ignored", runner.Sampling())
    assert not generation.ok
    assert "command" in generation.error

@pytest.mark.integration
def test_command_backend_honours_the_timeout():
    backend = runner.CommandBackend(
        [sys.executable, "-c", "import time; time.sleep(30)"])
    generation = backend.generate("ignored", runner.Sampling(), timeout = 1)
    assert not generation.ok
    assert "timed out" in generation.error

###########################################################
# HTTP backends fail cleanly when nothing is listening
###########################################################
def test_llamacpp_unreachable_returns_an_error_not_an_exception():
    backend = runner.LlamaCppBackend("http://127.0.0.1:1")
    generation = backend.generate("prompt", runner.Sampling(), timeout = 2)
    assert not generation.ok
    assert "llamacpp" in generation.error

def test_openai_unreachable_returns_an_error_not_an_exception():
    backend = runner.OpenAIBackend("http://127.0.0.1:1", "model-x")
    generation = backend.generate("prompt", runner.Sampling(), timeout = 2)
    assert not generation.ok
    assert "openai" in generation.error
