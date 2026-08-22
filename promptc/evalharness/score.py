# Scoring model output.
#
# The compiler is the judge. This module extracts a candidate answer from
# whatever the model emitted, hands it to the verifier commands the project
# configured, and classifies the failure. No LLM is consulted, and the
# golden answer is never used to decide pass or fail -- only as a
# diagnostic signal, because a different-but-valid answer is not wrong.

# Imports
import dataclasses
import difflib
import os
import re
import subprocess
import tempfile

FENCE_PATTERN = re.compile(r"```[^\n]*\n(.*?)```", re.S)

###########################################################
# Outcome taxonomy
###########################################################
# Each bucket points at a different fix, which is the whole reason to
# classify rather than just count failures.
OUTCOME_EMPTY = "empty"                 # model produced nothing -> prompt or runtime
OUTCOME_NO_ANSWER = "no_answer"         # no extractable block -> output contract
OUTCOME_VERIFIER = "verifier_failed"    # ran, rejected -> recipe content
OUTCOME_ERROR = "backend_error"         # infrastructure, not the prompt
OUTCOME_PASS = "pass"

@dataclasses.dataclass
class Attempt:
    seed: int
    outcome: str
    failing_verifier: str = ""
    detail: str = ""
    text: str = ""
    similarity: float = 0.0
    elapsed: float = 0.0

    def passed(self):
        return self.outcome == OUTCOME_PASS

@dataclasses.dataclass
class ItemResult:
    stem: str
    triggers: list = dataclasses.field(default_factory = list)
    attempts: list = dataclasses.field(default_factory = list)

    def passed(self):
        return any(attempt.passed() for attempt in self.attempts)

    # 1-indexed attempt number that first passed, else 0
    def attempts_to_green(self):
        for position, attempt in enumerate(self.attempts, start = 1):
            if attempt.passed():
                return position
        return 0

    # The classification of the last attempt, used for the failure taxonomy
    def outcome(self):
        if self.passed():
            return OUTCOME_PASS
        return self.attempts[-1].outcome if self.attempts else OUTCOME_ERROR

    def failing_verifier(self):
        for attempt in reversed(self.attempts):
            if attempt.failing_verifier:
                return attempt.failing_verifier
        return ""

###########################################################
# Extraction
###########################################################
def extract(text, mode):
    if not text or not text.strip():
        return ""
    if mode == "raw":
        return text
    match = FENCE_PATTERN.search(text)
    if match:
        return match.group(1)
    return ""

###########################################################
# Verification
###########################################################
def _run(command, cwd, timeout):
    try:
        completed = subprocess.run(
            command, cwd = cwd, capture_output = True, text = True, timeout = timeout)
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as error:
        return 127, f"command not found: {error}"

# Run each configured verifier in order against the candidate. Returns
# (ok, failing_verifier_id, detail).
def verify(config, candidate, suffix):
    verifiers = [config.verifier(name) for name in config.eval.verifiers]
    missing = [name for name, verifier in zip(config.eval.verifiers, verifiers) if verifier is None]
    if missing:
        return False, "", f"unknown verifier(s) in eval.verifiers: {', '.join(missing)}"

    handle = tempfile.NamedTemporaryFile(
        mode = "w", suffix = suffix, delete = False, encoding = "utf-8")
    try:
        handle.write(candidate)
        handle.close()

        for verifier in verifiers:
            command = [part.replace("{file}", handle.name) for part in verifier.command]
            returncode, output = _run(command, config.root, verifier.timeout)
            if returncode != 0:
                lines = [line for line in output.splitlines() if line.strip()]
                detail = "\n".join(lines[:5])
                return False, verifier.id, detail
        return True, "", ""
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

###########################################################
# Similarity (diagnostic only)
###########################################################
# Never used to decide pass or fail. A low similarity on a passing answer
# is interesting -- it means the model found a different valid fix.
def similarity(candidate, golden):
    if not candidate or not golden:
        return 0.0
    return difflib.SequenceMatcher(None, candidate.split(), golden.split()).ratio()

###########################################################
# Scoring one generation
###########################################################
def score_generation(config, generation, golden, seed):
    if not generation.ok:
        return Attempt(seed = seed, outcome = OUTCOME_ERROR,
                       detail = generation.error, elapsed = generation.elapsed)

    if not generation.text.strip():
        return Attempt(seed = seed, outcome = OUTCOME_EMPTY,
                       detail = "model returned no text", elapsed = generation.elapsed)

    candidate = extract(generation.text, config.eval.extract)
    if not candidate.strip():
        return Attempt(seed = seed, outcome = OUTCOME_NO_ANSWER,
                       detail = "no fenced block in output", text = generation.text,
                       elapsed = generation.elapsed)

    ok, failing, detail = verify(config, candidate, config.eval.suffix)
    return Attempt(
        seed = seed,
        outcome = OUTCOME_PASS if ok else OUTCOME_VERIFIER,
        failing_verifier = failing,
        detail = detail,
        text = candidate,
        similarity = similarity(candidate, golden),
        elapsed = generation.elapsed,
    )
