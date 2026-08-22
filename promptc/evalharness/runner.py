"""Model backends.

Three backends, all of which take a prompt and return text. The model is
the system under test here; nothing in this module judges anything.

    llamacpp  POST <endpoint>/completion    -- grammars, seeds, logprobs
    openai    POST <endpoint>/v1/chat/completions
    command   run an argv you configured, prompt on stdin

`command` is the escape hatch that keeps cloud models usable as a baseline
for the portability index without this file knowing anything about them.
It is also what the test suite drives, since no test may contact a real
model -- a stand-in script that prints a fixed answer exercises the entire
harness downstream of generation.

No backend raises on a transport failure. An unreachable server becomes a
Generation with `ok` false, so one dead endpoint mid-run classifies as a
backend error rather than aborting a thousand-item evaluation.
"""

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
    """How to sample one generation.

    Attributes:
        temperature: Sampling temperature. Low by default, since the work
            is mechanical rather than creative.
        top_p: Nucleus sampling cutoff.
        seed: Fixed per attempt so pass@k is reproducible. Substituted into
            the argv by CommandBackend.
        max_tokens: Generation cap.
        grammar: GBNF grammar text. Only the llamacpp backend enforces it;
            elsewhere the output contract is checked by a verifier instead.
        stop: Stop sequences.
    """

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
    """What a backend returned.

    Attributes:
        text: The generated text. May be empty on success, which the scorer
            classifies as `empty` rather than an error.
        ok: False for a transport or process failure -- infrastructure, not
            the prompt.
        error: Why it failed, when `ok` is false.
        elapsed: Wall time in seconds, set by the caller.
        meta: Whatever the backend reported, kept for diagnostics.
    """

    text: str
    ok: bool = True
    error: str = ""
    elapsed: float = 0.0
    meta: dict = dataclasses.field(default_factory = dict)

###########################################################
# HTTP helper
###########################################################
def _post_json(url, payload, timeout):
    """POST a JSON payload and return the decoded response."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data = data, headers = {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout = timeout) as response:
        return json.loads(response.read().decode("utf-8"))

###########################################################
# Backends
###########################################################
class Backend:
    """Interface every backend implements."""

    def generate(self, prompt, sampling, timeout = 600):
        """Generate one completion.

        Args:
            prompt: The full prompt.
            sampling: Sampling parameters.
            timeout: Seconds before giving up.

        Returns:
            Generation: With `ok` false rather than raising on failure.
        """
        raise NotImplementedError

class LlamaCppBackend(Backend):
    """A local llama-server, via its native completion endpoint.

    The only backend that enforces a GBNF grammar, and the one that makes
    prompt caching and fixed seeds available -- which is why promptc
    prefers llama.cpp over ollama for local work.
    """

    def __init__(self, endpoint):
        """Bind to a server.

        Args:
            endpoint: Base URL, e.g. http://127.0.0.1:8080.
        """
        self.url = endpoint.rstrip("/") + "/completion"

    def generate(self, prompt, sampling, timeout = 600):
        """Generate one completion, enforcing the grammar if given."""
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
    """Any OpenAI-compatible chat endpoint.

    Grammars are not passed: the API has no equivalent, so an output
    contract must be enforced by a verifier instead.
    """

    def __init__(self, endpoint, model, api_key = ""):
        """Bind to an endpoint.

        Args:
            endpoint: Base URL. `/v1/chat/completions` is appended.
            model: Model name sent with each request.
            api_key: Bearer token. Omitted from headers when empty, which
                suits a local server that wants no auth.
        """
        self.url = endpoint.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self.api_key = api_key

    def generate(self, prompt, sampling, timeout = 600):
        """Generate one completion as a single user message."""
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
    """An arbitrary program: prompt on stdin, completion on stdout.

    The escape hatch for anything the other two cannot reach -- a cloud CLI
    used as a portability baseline, or a deterministic stand-in in tests.
    """

    def __init__(self, command, cwd = None):
        """Bind to a command.

        Args:
            command: Argv list. `{seed}` in any element is substituted at
                generation time, which is how a stand-in can vary its
                answer reproducibly.
            cwd: Working directory for the subprocess.
        """
        self.command = list(command)
        self.cwd = cwd

    def generate(self, prompt, sampling, timeout = 600):
        """Run the command with the prompt on stdin."""
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
    """A backend could not be built from a profile.

    Always a configuration fault, so the message names what is missing and
    lists the valid choices.
    """

def make_backend(profile, spec = None, cwd = None):
    """Build the backend a profile describes.

    Args:
        profile: Target Profile.
        spec: The profile's raw mapping. `backend` selects explicitly;
            otherwise it is inferred -- `openai` when a model is named,
            `llamacpp` otherwise.
        cwd: Working directory, for the command backend.

    Returns:
        Backend: Ready to generate.

    Raises:
        BackendError: The backend name is unknown, or a required key for
            the chosen backend is missing.
    """
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
