"""Scoring model output.

The compiler is the judge. This module extracts a candidate answer from
whatever the model emitted, hands it to the verifier commands the project
configured, and classifies the failure. No LLM is consulted, and the golden
answer is never used to decide pass or fail -- only as a diagnostic signal,
because a different-but-valid answer is not wrong.

The taxonomy exists because each bucket points at a different fix. Nothing
extractable means the output contract is wrong; a verifier rejection means
the recipe content is; a backend error means neither.
"""

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
    """One generation and what the verifiers made of it.

    Attributes:
        seed: Sampling seed used, so a result can be reproduced exactly.
        outcome: One of the OUTCOME_* constants.
        failing_verifier: Id of the first verifier to reject, or empty.
        detail: Verifier output or error text, trimmed for reporting.
        text: The extracted candidate, kept for inspection.
        similarity: Word-level ratio against the golden answer. Recorded
            only as a diagnostic; it never affects `outcome`.
        elapsed: Wall time in seconds.
    """

    seed: int
    outcome: str
    failing_verifier: str = ""
    detail: str = ""
    text: str = ""
    similarity: float = 0.0
    elapsed: float = 0.0

    def passed(self):
        """Return True if every verifier accepted this attempt."""
        return self.outcome == OUTCOME_PASS

@dataclasses.dataclass
class ItemResult:
    """Every attempt made on one work item.

    Attributes:
        stem: Corpus-relative item identity.
        triggers: Trigger names that fired, used to build the per-recipe
            scorecard.
        attempts: Attempts in order. Generation stops at the first success,
            so a passing item's last attempt is the one that passed.
    """

    stem: str
    triggers: list = dataclasses.field(default_factory = list)
    attempts: list = dataclasses.field(default_factory = list)

    def passed(self):
        """Return True if any attempt passed."""
        return any(attempt.passed() for attempt in self.attempts)

    def attempts_to_green(self):
        """Return how many attempts it took to pass.

        Returns:
            int: 1-indexed position of the first passing attempt, or 0 if
            none passed. Averaged across items, this is the real cost
            signal for a retry-heavy local run.
        """
        for position, attempt in enumerate(self.attempts, start = 1):
            if attempt.passed():
                return position
        return 0

    def outcome(self):
        """Return the taxonomy bucket for this item.

        Returns:
            str: OUTCOME_PASS when any attempt passed, else the last
            attempt's outcome. An item with no attempts is a backend error.
        """
        if self.passed():
            return OUTCOME_PASS
        return self.attempts[-1].outcome if self.attempts else OUTCOME_ERROR

    def failing_verifier(self):
        """Return the most recent failing verifier id, or empty."""
        for attempt in reversed(self.attempts):
            if attempt.failing_verifier:
                return attempt.failing_verifier
        return ""

###########################################################
# Extraction
###########################################################
def extract(text, mode):
    """Pull the candidate answer out of a model's output.

    Args:
        text: Raw generation.
        mode: `fence` takes the first fenced block; `raw` returns the text
            unchanged.

    Returns:
        str: The candidate, or empty when nothing could be extracted --
        which the caller classifies as `no_answer`, an output contract
        problem rather than a knowledge problem.
    """
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
    """Run a verifier, mapping failure modes onto exit codes.

    Returns:
        tuple: (returncode, combined_output). 124 for a timeout and 127 for
        a missing binary, matching shell convention, so the caller has one
        code path.
    """
    try:
        completed = subprocess.run(
            command, cwd = cwd, capture_output = True, text = True, timeout = timeout)
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as error:
        return 127, f"command not found: {error}"

def verify(config, candidate, suffix):
    """Run every configured verifier against a candidate answer.

    Verifiers run in the order listed and the first failure wins, so put
    the cheapest or most fundamental check first.

    Args:
        config: Loaded Config, supplying `eval.verifiers`.
        candidate: The extracted answer.
        suffix: Extension for the temp file handed to each verifier.

    Returns:
        tuple: (ok, failing_verifier_id, detail). An unknown verifier id in
        the config is reported through `detail` rather than raising, so one
        misconfigured run still produces a report.
    """
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
def similarity(candidate, golden):
    """Compare a candidate to the golden answer, word by word.

    Never used to decide pass or fail. A low similarity on a *passing*
    answer is interesting -- the model found a different valid fix, or the
    verifier is too permissive -- but it is not evidence of a fault.

    Args:
        candidate: The extracted answer.
        golden: The known-good answer.

    Returns:
        float: Ratio in [0, 1]. Zero when either side is empty.
    """
    if not candidate or not golden:
        return 0.0
    return difflib.SequenceMatcher(None, candidate.split(), golden.split()).ratio()

###########################################################
# Scoring one generation
###########################################################
def score_generation(config, generation, golden, seed):
    """Classify one generation into the taxonomy.

    Args:
        config: Loaded Config, supplying extraction mode and verifiers.
        generation: Generation from a backend.
        golden: Known-good answer, for the similarity diagnostic only.
        seed: Seed used, recorded on the attempt.

    Returns:
        Attempt: With `outcome` naming the bucket and, for a verifier
        rejection, which verifier said no.
    """
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
