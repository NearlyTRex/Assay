# Docstrings

Google style throughout.

## The parts

A docstring has up to five parts, in this order. Only the first is always
required.

| Part | Required | Content |
|---|---|---|
| **Summary** | Always | One line, imperative mood, ends with a period |
| **Description** | When the *why* is not obvious | Prose paragraphs after a blank line |
| **`Args:`** | When a parameter needs explaining | One entry per parameter that does |
| **`Returns:`** | When the return is not obvious from the name | Type and meaning, including what empty means |
| **`Raises:`** | When the caller must handle something | Exception type and the condition |

## Modules

A summary line, then prose explaining what the module is *for* and why it
exists — the reasoning that is not recoverable from reading the code.

```python
"""External verification of example blocks (PC006).

This is the module that keeps the toolset domain-agnostic. It knows how to
extract a fenced block, write it to a file, run a command you configured,
and read an exit code. It knows nothing about what the command does.
"""
```

The description is where an architectural decision gets recorded. If a
module exists to enforce an invariant, say which one and why:

```python
"""Token counting.

Budgets must be checked with the *target model's* tokenizer, not an
estimate, or PC004 is worthless. Estimation stays available as an explicit,
clearly-labelled fallback so a missing tokenizer degrades loudly rather
than silently.
"""
```

Where a module is also an entry point, add a `Usage:` block with real
commands, indented four spaces:

```python
"""Split a monolithic prompt into fragment skeletons.

Usage:
    # Dry run — show what would be written
    python3 -m promptc split big-prompt.md --level 3

    # Apply
    python3 -m promptc split big-prompt.md --level 3 --apply
"""
```

## Functions

### Summary line

Imperative mood — "Return the assembled prompt", not "Returns the assembled
prompt" and not "This function returns the assembled prompt". One line,
under 79 characters, ending in a period.

A one-liner is correct and sufficient when the signature says the rest:

```python
def slugify(text, limit = 48):
    """Convert a heading into a fragment id."""
```

### The full form

```python
def check_budget(assembly, profile, counter):
    """Report fragments that push an assembly past its model's context.

    The per-fragment breakdown matters more than the total: knowing you are
    4,000 tokens over is useless without knowing which three fragments to
    cut.

    Args:
        assembly: Assembly to measure.
        profile: Target Profile, supplying context size and reserves.
        counter: Counter for the profile's tokenizer. May be an estimate,
            in which case PC014 will already have been raised.

    Returns:
        List of Diagnostic. One ERROR when the whole assembly is over
        budget, plus one WARN per fragment over its declared `budget`.
    """
```

Continuation lines in `Args:` are indented a further four spaces, as with
`counter` above.

### `Raises:`

Only for exceptions the caller is expected to handle. Do not document
`TypeError` from passing the wrong thing.

```python
def counter(spec):
    """Build a token counter from a tokenizer spec.

    Args:
        spec: One of `chars`, `tiktoken:<encoding>`, `hf:<name-or-path>`,
            or `llamacpp:<url>`.

    Returns:
        Counter. Its `exact` attribute is False for `chars`.

    Raises:
        TokenizerUnavailable: The spec is unrecognised, its package is not
            installed, or its endpoint is unreachable. Carries a `fix_hint`.
    """
```

## What not to write

**Do not restate the signature.** This is the most common failure and it
adds only noise:

```python
# Bad
"""Parse a fragment.

Args:
    path: The path.
    root: The root.
"""
```

If a parameter needs no explanation beyond its name, leave it out of
`Args:` entirely. If none of them do, drop the block.

**Do not describe the implementation.** The docstring is the contract; the
body is the implementation. "Loops over the fragments and appends to a
list" tells the reader nothing they cannot see.

**Do not restate the summary in the description.** If the description would
paraphrase the first line, delete it.

## What to document

The things a reader cannot recover from the code:

- **Units and scale.** Tokens or characters? Seconds or milliseconds?
- **Path semantics.** Absolute, project-relative, or corpus-relative?
- **What empty means.** Is `[]` "nothing wrong" or "could not check"?
- **Ownership.** Who deletes the temp file? Who closes the handle?
- **Swallowed errors.** If a subprocess failure becomes a return value
  rather than an exception, say so.
- **Invariants relied on.** "Assumes the index has already been checked for
  cycles."

## Where required

| | Docstring |
|---|---|
| Every module | Required |
| Public function or class | Required |
| Rule check function | Required — state which rule and what trips it |
| Dataclass with non-obvious fields | Required |
| `__init__` that only assigns | Not required |
| Internal helper under ~5 lines | Not required |

## Docstring or comment?

Both, for different jobs.

The **docstring** says what the function does and what its contract is. A
**`#` comment** says why a particular line does something surprising.

```python
def _llamacpp_counter(spec, endpoint):
    """Build a counter backed by a running llama-server."""
    url = endpoint.rstrip("/") + "/tokenize"

    def count(text):
        ...

    # Probe once so a dead server fails at construction, not mid-check
    count("probe")
    return Counter(spec, True, count)
```

Section banners stay as comments — they organise the file, they are not
part of any API:

```python
###########################################################
# Fence extraction
###########################################################
```

## Checking coverage

Nested closures are exempt, so a short list here is expected rather than a
gap:

```bash
python3 - <<'EOF'
import ast, glob
for p in sorted(glob.glob("promptc/**/*.py", recursive=True)):
    if "__pycache__" in p: continue
    tree = ast.parse(open(p).read())
    if not ast.get_docstring(tree):
        print(f"module missing docstring: {p}")
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not ast.get_docstring(n):
                print(f"{p}: {n.name}")
EOF
```
