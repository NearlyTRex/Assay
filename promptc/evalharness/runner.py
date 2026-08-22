# Model backends.
#
# Three backends, all of which take a prompt and return text. The model is
# the system under test here; nothing in this module judges anything.
#
#   llamacpp  POST <endpoint>/completion    -- grammars, seeds, logprobs
#   openai    POST <endpoint>/v1/chat/completions
#   command   run an argv you configured, prompt on stdin
#
# `command` is the escape hatch that keeps cloud models usable as a baseline
# for the portability index without this file knowing anything about them.

# Imports
import dataclasses
import json
import subprocess
import urllib.error
import urllib.request

###########################################################
# Sampling parameters
###########################################################
@dataclasses.dataclass
class Sampling:
    temperature: float = 0.2
    top_p: float = 0.95
    seed: int = 0
    max_tokens: int = 4096
    grammar: str = ""
    stop: list = dataclasses.field(default_factory = list)

###########################################################
# Result
###########################################################
@dataclasses.dataclass
class Generation:
    text: str
    ok: bool = True
    error: str = ""
    # Wall time in seconds
    elapsed: float = 0.0
    # Whatever the backend reported, kept for diagnostics
    meta: dict = dataclasses.field(default_factory = dict)

###########################################################
# HTTP helper
###########################################################
def _post_json(url, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data = data, headers = {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout = timeout) as response:
        return json.loads(response.read().decode("utf-8"))

###########################################################
# Backends
###########################################################
class Backend:
    def generate(self, prompt, sampling, timeout = 600):
        raise NotImplementedError

class LlamaCppBackend(Backend):
    def __init__(self, endpoint):
        self.url = endpoint.rstrip("/") + "/completion"

    def generate(self, prompt, sampling, timeout = 600):
        payload = {
            "prompt": prompt,
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "n_predict": sampling.max_tokens,
            "seed": sampling.seed,
            "cache_prompt": True,
        }
        if sampling.grammar:
            payload["grammar"] = sampling.grammar
        if sampling.stop:
            payload["stop"] = sampling.stop

        try:
            body = _post_json(self.url, payload, timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            return Generation("", ok = False, error = f"llamacpp: {error}")

        return Generation(
            text = body.get("content", ""),
            meta = {
                "tokens_predicted": body.get("tokens_predicted"),
                "tokens_evaluated": body.get("tokens_evaluated"),
                "truncated": body.get("truncated"),
            },
        )

class OpenAIBackend(Backend):
    def __init__(self, endpoint, model, api_key = ""):
        self.url = endpoint.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self.api_key = api_key

    def generate(self, prompt, sampling, timeout = 600):
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_tokens": sampling.max_tokens,
        }
        if sampling.seed:
            payload["seed"] = sampling.seed
        if sampling.stop:
            payload["stop"] = sampling.stop

        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(self.url, data = data, headers = headers)
        try:
            with urllib.request.urlopen(request, timeout = timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            return Generation("", ok = False, error = f"openai: {error}")

        choices = body.get("choices") or []
        if not choices:
            return Generation("", ok = False, error = "openai: no choices returned")

        return Generation(
            text = choices[0].get("message", {}).get("content", ""),
            meta = {"usage": body.get("usage")},
        )

class CommandBackend(Backend):
    def __init__(self, command, cwd = None):
        self.command = list(command)
        self.cwd = cwd

    def generate(self, prompt, sampling, timeout = 600):
        command = [part.replace("{seed}", str(sampling.seed)) for part in self.command]
        try:
            completed = subprocess.run(
                command, input = prompt, capture_output = True, text = True,
                cwd = self.cwd, timeout = timeout)
        except FileNotFoundError as error:
            return Generation("", ok = False, error = f"command: {error}")
        except subprocess.TimeoutExpired:
            return Generation("", ok = False, error = f"command: timed out after {timeout}s")

        if completed.returncode != 0:
            return Generation(
                completed.stdout or "", ok = False,
                error = f"command exited {completed.returncode}: "
                        f"{(completed.stderr or '').strip()[:400]}")

        return Generation(text = completed.stdout)

###########################################################
# Construction
###########################################################
class BackendError(Exception):
    pass

# Build a backend from a profile. `backend:` may be set explicitly in the
# profile's raw config; otherwise it is inferred from what is present.
def make_backend(profile, spec = None, cwd = None):
    spec = spec or {}
    kind = spec.get("backend")

    if kind is None:
        kind = "openai" if profile.model else "llamacpp"

    if kind == "llamacpp":
        if not profile.endpoint:
            raise BackendError(
                f"Profile `{profile.name}` needs an `endpoint:` for the llamacpp backend "
                f"(e.g. http://127.0.0.1:8080).")
        return LlamaCppBackend(profile.endpoint)

    if kind == "openai":
        if not profile.endpoint:
            raise BackendError(f"Profile `{profile.name}` needs an `endpoint:`.")
        return OpenAIBackend(profile.endpoint, profile.model, spec.get("api_key", ""))

    if kind == "command":
        command = spec.get("command")
        if not command:
            raise BackendError(
                f"Profile `{profile.name}` uses the command backend but declares no `command:`.")
        return CommandBackend(command, cwd = cwd)

    raise BackendError(f"Unknown backend `{kind}`. Use llamacpp, openai, or command.")
