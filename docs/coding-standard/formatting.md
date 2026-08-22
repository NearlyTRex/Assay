# Formatting

No enforced formatter. These are conventions a reviewer checks, not
something a tool rewrites — so they are few, and they matter.

## Keyword argument spacing

Spaces around `=` in keyword arguments and defaults:

```python
def parse_fragment(path, root = ""):
    ...

diagnostics.Diagnostic(
    rule = "PC001",
    severity = Severity.ERROR,
    message = message,
    file = item.path,
    line = line,
    fix_hint = hint,
)
```

This is the one place the house style departs from PEP 8. It is applied
consistently throughout the package — keep it that way.

## Line length

Under 100 characters. Break at a natural boundary rather than hugging the
limit — one argument per line beats a wrapped soup:

```python
# Good
found.append(Diagnostic(
    rule = "PC002", severity = Severity.ERROR,
    message = f"`requires` names unknown fragment `{required}`.",
    file = item.path, line = 1,
    fix_hint = f"correct the id, or run `promptc new recipe {required}`.",
    data = {"missing": required},
))

# Bad
found.append(Diagnostic(rule = "PC002", severity = Severity.ERROR, message = f"`requires` names unknown fragment `{required}`.", file = item.path, line = 1))
```

Related short keyword arguments may share a line, as `file` and `line` do
above. Judgement, not a rule.

## Dataclasses over dicts

Prefer a dataclass for anything that crosses a module boundary. Dicts are
for JSON payloads on the way out.

```python
@dataclasses.dataclass
class VerifyResult:
    verifier: str
    block: Block
    fragment: str
    ok: bool
    returncode: int
    output: str
```

A dict here would mean every consumer re-deriving the shape and no error
when a key is misspelled.

Mutable defaults use `dataclasses.field(default_factory = list)`.

## f-strings

Use them. For multi-line messages, prefer implicit concatenation over
`\`-continuation or `.format`:

```python
message = (
    f"Assembled prompt is {total:,} tok; budget is {budget:,} "
    f"(context {profile.context:,} − payload {profile.reserve:,} "
    f"− output {profile.output_reserve:,}). Over by {over:,}.")
```

Thousands separators (`:,`) on any number a human reads. Percentages as
`{rate:.1%}`.

## Comments

Sentence case, no trailing period on single-line comments, above the line
they describe rather than beside it:

```python
# Probe once so a dead server fails at construction, not mid-check
count("probe")
```

Explain *why*, never *what*. `# increment the counter` above `count += 1`
is noise; `# Blank out the canonical term first, keeping the text the same
length so offsets stay valid` is the reason the next four lines exist.

## Blank lines

Two between top-level definitions is the Python default and is not
followed here — the section banners do that work. One blank line between
functions inside a banner group, matching the existing files.
