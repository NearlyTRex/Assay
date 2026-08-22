# Token counting.
#
# Budgets must be checked with the *target model's* tokenizer, not an
# estimate, or PC004 is worthless. Estimation stays available as an
# explicit, clearly-labelled fallback so a missing tokenizer degrades
# loudly rather than silently.

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
    def __init__(self, spec, exact, count_fn):
        self.spec = spec
        self.exact = exact
        self._count = count_fn

    def count(self, text):
        if not text:
            return 0
        return self._count(text)

    def describe(self):
        return self.spec if self.exact else f"{self.spec} (estimate)"

###########################################################
# Backends
###########################################################
def _chars_counter(spec):
    def count(text):
        return int(len(text) / CHARS_PER_TOKEN)
    return Counter(spec, False, count)

def _tiktoken_counter(spec, encoding_name):
    import tiktoken
    encoding = tiktoken.get_encoding(encoding_name)
    return Counter(spec, True, lambda text: len(encoding.encode(text)))

def _hf_counter(spec, name):
    from tokenizers import Tokenizer
    if os.path.exists(name):
        tokenizer = Tokenizer.from_file(name)
    else:
        tokenizer = Tokenizer.from_pretrained(name)
    return Counter(spec, True, lambda text: len(tokenizer.encode(text).ids))

def _llamacpp_counter(spec, endpoint):
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
    def __init__(self, spec, reason, fix_hint):
        super().__init__(reason)
        self.spec = spec
        self.reason = reason
        self.fix_hint = fix_hint

# Build a counter from a spec string:
#   chars                      estimate, always available
#   tiktoken:cl100k_base       via tiktoken
#   hf:Qwen/Qwen2.5-Coder-7B   via tokenizers (name or local tokenizer.json)
#   llamacpp:http://host:8080  via a running llama-server /tokenize
@functools.lru_cache(maxsize = None)
def counter(spec):
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
            "install it via the JoyBox bootstrap, or set `tokenizer: chars` to fall back to estimation.",
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
