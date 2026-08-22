"""External verification of example blocks (PC006).

This is the module that keeps the toolset domain-agnostic. It knows how to
extract a fenced block, write it to a file, run a command you configured,
and read an exit code. It knows nothing about what the command does.

Verifying examples matters more than it first appears: a worked example
that no longer compiles is worse than no example, because small models copy
examples far more literally than they follow prose.
"""

# Imports
import dataclasses
import os
import re
import subprocess
import tempfile

# Local imports
from .diagnostics import Diagnostic, Severity

###########################################################
# Fence extraction
###########################################################
FENCE_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)```(?P<info>[^\n]*)\n(?P<code>.*?)^(?P=indent)```[ \t]*$",
    re.S | re.M,
)

# Explicit opt-out for blocks that are meant to be broken -- a "before"
# example in a recipe, for instance.
NOVERIFY_TOKEN = "promptc:noverify"

@dataclasses.dataclass
class Block:
    """One fenced code block extracted from a fragment.

    Attributes:
        language: First word of the fence info string, e.g. `cpp`.
        info: The whole info string, including any markers.
        code: Block contents, without the fences.
        line: 1-indexed line in the file where the block opens.
        skip: True when the fence carries `promptc:noverify`, marking a
            block deliberately shown broken.
    """

    language: str
    info: str
    code: str
    line: int
    skip: bool

def extract_blocks(item):
    """Find every fenced code block in a fragment.

    Args:
        item: Fragment to scan.

    Returns:
        list: Block objects in document order, including skipped ones so a
        caller can count what it chose not to run.
    """
    blocks = []
    for match in FENCE_PATTERN.finditer(item.body):
        info = match.group("info").strip()
        language = info.split()[0] if info else ""
        blocks.append(Block(
            language = language,
            info = info,
            code = match.group("code"),
            line = item.body_line(match.start()),
            skip = NOVERIFY_TOKEN in info,
        ))
    return blocks

###########################################################
# Matching a verifier to a block
###########################################################
def verifier_matches(verifier, block):
    """Decide whether a verifier applies to a block.

    Both "```cpp" and "cpp" forms are accepted in config, so the YAML can
    read naturally either way.

    Args:
        verifier: Configured Verifier.
        block: Block to test.

    Returns:
        bool: True when the verifier's `match` equals the block's language
        or appears in its info string. An empty `match` matches everything.
    """
    if not verifier.match:
        return True
    needle = verifier.match.strip().strip("`").strip()
    if not needle:
        return True
    return needle == block.language or needle in block.info

###########################################################
# Execution
###########################################################
@dataclasses.dataclass
class VerifyResult:
    """The outcome of running one verifier against one block.

    Attributes:
        verifier: Verifier id.
        block: The Block that was checked.
        fragment: Id of the fragment it came from.
        ok: Whether the verifier exited zero.
        returncode: Exit code. 124 for a timeout, 127 for a missing binary.
        output: Combined stdout and stderr, stripped.
    """

    verifier: str
    block: Block
    fragment: str
    ok: bool
    returncode: int
    output: str

def _suffix_for(verifier, block):
    """Choose the temp file extension for a block.

    Prefers the verifier's configured suffix, then the fence language, so a
    ```cpp block becomes `.cpp` with no configuration at all.
    """
    if verifier.suffix:
        return verifier.suffix
    if block.language:
        return "." + block.language
    return ".txt"

def run_verifier(verifier, block, fragment, cwd):
    """Write a block to a temp file and run one verifier over it.

    Never raises. A timeout and a missing binary both become synthetic exit
    codes, so the caller has a single code path.

    Args:
        verifier: Configured Verifier. `{file}` in its command is replaced
            with the temp file path.
        block: Block to check.
        fragment: Id of the owning fragment, for reporting.
        cwd: Working directory for the subprocess, normally the project
            root so relative commands resolve.

    Returns:
        VerifyResult: The temp file is removed before returning, whatever
        happened.
    """
    suffix = _suffix_for(verifier, block)
    handle = tempfile.NamedTemporaryFile(
        mode = "w", suffix = suffix, delete = False, encoding = "utf-8")
    try:
        handle.write(block.code)
        handle.close()

        command = [part.replace("{file}", handle.name) for part in verifier.command]
        try:
            completed = subprocess.run(
                command, cwd = cwd, capture_output = True, text = True,
                timeout = verifier.timeout)
            output = (completed.stdout or "") + (completed.stderr or "")
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            output = f"verifier timed out after {verifier.timeout}s"
            returncode = 124
        except FileNotFoundError as error:
            output = f"verifier command not found: {error}"
            returncode = 127

        return VerifyResult(
            verifier = verifier.id, block = block, fragment = fragment,
            ok = returncode == 0, returncode = returncode,
            output = output.strip(),
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

###########################################################
# PC006
###########################################################
def _summarise(output, limit = 6):
    """Trim verifier output to something a diagnostic can carry."""
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[:limit] + [f"... ({len(lines) - limit} more lines)"])

def check_examples(config, fragments, only_fragment = None):
    """Run every configured verifier over every example block (PC006).

    Args:
        config: Loaded Config, supplying the verifiers.
        fragments: Fragments to check.
        only_fragment: Limit to one fragment id, for iterating on a single
            recipe's examples.

    Returns:
        tuple: (diagnostics, results). Diagnostics are PC006, ERROR
        severity, one per failing block-verifier pair. Results cover every
        pair that ran, including passes, so a caller can report how many
        blocks were checked. Both are empty when no verifiers are
        configured -- silence rather than a complaint, since verifying
        examples is opt-in.
    """
    found = []
    results = []

    if not config.verifiers:
        return found, results

    for item in fragments:
        if only_fragment and item.id != only_fragment:
            continue
        for block in extract_blocks(item):
            if block.skip:
                continue
            for verifier in config.verifiers:
                if not verifier_matches(verifier, block):
                    continue
                result = run_verifier(verifier, block, item.id, config.root)
                results.append(result)
                if result.ok:
                    continue
                found.append(Diagnostic(
                    rule = "PC006", severity = Severity.ERROR,
                    message = (f"Example block failed verifier `{verifier.id}` "
                               f"(exit {result.returncode}).\n"
                               f"{_summarise(result.output)}"),
                    file = item.path, line = block.line,
                    fix_hint = (f"fix the example, mark the fence `{block.language} "
                                f"{NOVERIFY_TOKEN}` if it is deliberately broken, "
                                f"or update the verifier."),
                    data = {
                        "verifier": verifier.id,
                        "returncode": result.returncode,
                        "language": block.language,
                    },
                ))

    return found, results
