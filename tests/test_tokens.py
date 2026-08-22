# Tests for promptc/tokens.py -- token counting and loud degradation.

# Third party
import pytest

# Local imports
from promptc import tokens

###########################################################
# Character estimation
###########################################################
def test_chars_counter_reports_itself_as_an_estimate():
    counter = tokens.counter("chars")
    assert not counter.exact
    assert "estimate" in counter.describe()

def test_chars_counter_uses_the_documented_ratio():
    assert tokens.counter("chars").count("a" * 360) == 100

def test_empty_text_counts_zero():
    assert tokens.counter("chars").count("") == 0

def test_default_spec_is_chars():
    assert tokens.counter(None).spec == "chars"
    assert tokens.counter("").spec == "chars"

def test_counters_are_cached():
    assert tokens.counter("chars") is tokens.counter("chars")

###########################################################
# Failure modes
###########################################################
def test_unknown_scheme_raises_with_a_fix_hint():
    with pytest.raises(tokens.TokenizerUnavailable) as caught:
        tokens.counter("nonsense:thing")
    assert caught.value.fix_hint
    assert "chars" in caught.value.fix_hint

def test_malformed_spec_raises_with_a_fix_hint():
    with pytest.raises(tokens.TokenizerUnavailable) as caught:
        tokens.counter("gibberish")
    assert "Unrecognised tokenizer spec" in caught.value.reason

def test_unreachable_llamacpp_raises_rather_than_hanging():
    with pytest.raises(tokens.TokenizerUnavailable) as caught:
        tokens.counter("llamacpp:http://127.0.0.1:1")
    assert "unreachable" in caught.value.reason or "failed to load" in caught.value.reason

def test_failure_never_silently_becomes_an_estimate():
    """Falling back is the caller's decision, made visible via PC014.

    A silent fallback inside the counter would leave PC004 appearing to
    pass while measuring something other than the target model.
    """
    with pytest.raises(tokens.TokenizerUnavailable):
        tokens.counter("hf:definitely/not-a-real-model-xyz")
