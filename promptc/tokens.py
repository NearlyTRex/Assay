"""Token counting.

Budgets must be checked with the *target model's* tokenizer, not an
estimate, or PC004 is worthless. Estimation stays available as an explicit,
clearly-labelled fallback so a missing tokenizer degrades loudly rather
than silently -- a budget measured against the wrong tokenizer appears to
pass while proving nothing, which is the worst outcome because it looks
like success.

Nothing here falls back on its own. An unavailable tokenizer raises, and
the caller decides whether to continue on estimation and say so (PC014).
"""

# Imports
import functools
import json
import os
import urllib.error
import urllib.request

# Rough bytes-per-token for dense technical prose. Only used by the
# `chars` counter, which always reports itself as an estimate.
CHARS_PER_TOKEN = 3.6

###########################################################
# Counter
###########################################################
class Counter:
    """A token counter bound to one tokenizer.

    Attributes:
        spec: The spec string this was built from.
        exact: False for character estimation, True for a real tokenizer.
            Callers use this to decide whether a budget figure can be
            trusted; describe() folds it into a human-readable label.
    """

    def __init__(self, spec, exact, count_fn):
        """Bind a counting function to its spec.

        Args:
            spec: Spec string, for reporting.
            exact: Whether the count is exact rather than estimated.
            count_fn: Callable taking text and returning a token count.
        """
        self.spec = spec
        self.exact = exact
        self._count = count_fn

    def count(self, text):
        """Return the token count for text.

        Args:
            text: Text to measure. Empty text counts as zero without
                invoking the backend.

        Returns:
            int: Token count, exact or estimated per `exact`.
        """
        if not text:
            return 0
        return self._count(text)

    def describe(self):
        """Return a label naming the tokenizer, marked when it estimates.

        Returns:
            str: The spec, with " (estimate)" appended when not exact. Used
            in manifests and eval reports so a reader can tell whether a
            token figure was measured or guessed.
        """
        return self.spec if self.exact else f"{self.spec} (estimate)"

###########################################################
# Backends
###########################################################
def _chars_counter(spec):
    """Build a counter that estimates from character count."""
    def count(text):
        return int(len(text) / CHARS_PER_TOKEN)
    return Counter(spec, False, count)

def _tiktoken_counter(spec, encoding_name):
    """Build a counter backed by a tiktoken encoding.

    Args:
        spec: Spec string, for reporting.
        encoding_name: A tiktoken encoding, e.g. `cl100k_base`.

    Raises:
        ImportError: tiktoken is not installed.
    """
    import tiktoken
    encoding = tiktoken.get_encoding(encoding_name)
    return Counter(spec, True, lambda text: len(encoding.encode(text)))

def _hf_counter(spec, name):
    """Build a counter backed by a HuggingFace tokenizer.

    Args:
        spec: Spec string, for reporting.
        name: A model name, or a path to a local tokenizer.json. A path is
            preferred offline, since a bare name triggers a download.

    Raises:
        ImportError: The tokenizers package is not installed.
    """
    from tokenizers import Tokenizer
    if os.path.exists(name):
        tokenizer = Tokenizer.from_file(name)
    else:
        tokenizer = Tokenizer.from_pretrained(name)
    return Counter(spec, True, lambda text: len(tokenizer.encode(text).ids))

def _llamacpp_counter(spec, endpoint):
    """Build a counter backed by a running llama-server.

    The most accurate option for a local model, since it uses the same
    tokenizer the model itself will see.

    Args:
        spec: Spec string, for reporting.
        endpoint: Base URL of the server, e.g. http://127.0.0.1:8080.

    Raises:
        urllib.error.URLError: The server is unreachable. Raised during
            construction rather than on first use, by way of the probe.
    """
    url = endpoint.rstrip("/") + "/tokenize"

    def count(text):
        payload = json.dumps({"content": text}).encode("utf-8")
        request = urllib.request.Request(
            url, data = payload, headers = {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout = 30) as response:
            body = json.loads(response.read().decode("utf-8"))
        return len(body.get("tokens", []))

    # Probe once so a dead server fails at construction, not mid-check
    count("probe")
    return Counter(spec, True, count)

###########################################################
# Resolution
###########################################################
class TokenizerUnavailable(Exception):
    """A tokenizer could not be built.

    Carries a remedy so the caller can put it straight into a diagnostic
    rather than inventing one.

    Attributes:
        spec: The spec that failed.
        reason: What went wrong, in a sentence.
        fix_hint: The concrete remedy -- install a package, start a server,
            or set `tokenizer: chars` to accept estimation deliberately.
    """

    def __init__(self, spec, reason, fix_hint):
        """Record the failed spec along with its remedy."""
        super().__init__(reason)
        self.spec = spec
        self.reason = reason
        self.fix_hint = fix_hint

@functools.lru_cache(maxsize = None)
def counter(spec):
    """Build a token counter from a tokenizer spec.

    Results are cached, so repeatedly asking for the same spec does not
    reload a tokenizer or re-probe a server.

    Args:
        spec: One of `chars` (estimate, always available),
            `tiktoken:<encoding>`, `hf:<name-or-path>`, or
            `llamacpp:<url>`. Empty or None is treated as `chars`.

    Returns:
        Counter: Check its `exact` attribute before trusting a budget
        figure derived from it.

    Raises:
        TokenizerUnavailable: The spec is unrecognised, its package is not
            installed, or its endpoint is unreachable. Never falls back
            silently -- that decision belongs to the caller, which
            announces it via PC014.
    """
    spec = (spec or "chars").strip()

    if spec == "chars":
        return _chars_counter(spec)

    if ":" not in spec:
        raise TokenizerUnavailable(
            spec,
            f"Unrecognised tokenizer spec `{spec}`.",
            "use one of: chars, tiktoken:<encoding>, hf:<name-or-path>, llamacpp:<url>.",
        )

    scheme, value = spec.split(":", 1)

    try:
        if scheme == "tiktoken":
            return _tiktoken_counter(spec, value)
        if scheme == "hf":
            return _hf_counter(spec, value)
        if scheme == "llamacpp":
            return _llamacpp_counter(spec, value)
    except ImportError as error:
        raise TokenizerUnavailable(
            spec,
            f"Tokenizer `{spec}` needs a package that is not installed: {error}.",
            "install it, or set `tokenizer: chars` to fall back to estimation.",
        )
    except (urllib.error.URLError, OSError) as error:
        raise TokenizerUnavailable(
            spec,
            f"Tokenizer `{spec}` is unreachable: {error}.",
            "start llama-server, or set `tokenizer: chars` to fall back to estimation.",
        )
    except Exception as error:
        raise TokenizerUnavailable(
            spec,
            f"Tokenizer `{spec}` failed to load: {error}.",
            "check the tokenizer name or path.",
        )

    raise TokenizerUnavailable(
        spec,
        f"Unknown tokenizer scheme `{scheme}`.",
        "use one of: chars, tiktoken:<encoding>, hf:<name-or-path>, llamacpp:<url>.",
    )
