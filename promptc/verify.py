# External verification of example blocks (PC006).
#
# This is the module that keeps the toolset domain-agnostic. It knows how to
# extract a fenced block, write it to a file, run a command you configured,
# and read an exit code. It knows nothing about what the command does.

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
    language: str
    info: str
    code: str
    line: int
    skip: bool

def extract_blocks(item):
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
# A verifier's `match` is compared against the fence info string. Both
# "```cpp" and "cpp" forms are accepted in config so the YAML can read
# naturally either way.
def verifier_matches(verifier, block):
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
    verifier: str
    block: Block
    fragment: str
    ok: bool
    returncode: int
    output: str

def _suffix_for(verifier, block):
    if verifier.suffix:
        return verifier.suffix
    if block.language:
        return "." + block.language
    return ".txt"

def run_verifier(verifier, block, fragment, cwd):
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
# Trim verifier output to something a diagnostic can carry without
# flooding the report.
def _summarise(output, limit = 6):
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[:limit] + [f"... ({len(lines) - limit} more lines)"])

def check_examples(config, fragments, only_fragment = None):
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
