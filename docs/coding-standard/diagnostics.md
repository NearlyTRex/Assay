# Diagnostics

## Never print a finding

Every finding is a `Diagnostic` with a stable rule id, a location, a
message, and a fix hint. Rendering is the `Report`'s job, and it supports
both text and JSON because an agent consumes one and a human the other.

```python
Diagnostic(
    rule = "PC001",
    severity = Severity.ERROR,
    message = f"Reference to `{target}` is not declared in `requires`.",
    file = item.path,
    line = line,
    fix_hint = f"add `{target}` to this fragment's `requires`.",
    data = {"target": target},
)
```

## Fix hints are not optional politeness

An agent acts on the hint without loading the docs, so it must name the
concrete edit:

```python
fix_hint = f"add `{providers[0]}` to `requires`."        # good
fix_hint = "fix the reference."                          # useless
```

Test for the presence of a hint, never its wording — see
[../testing/assertions.md](../testing/assertions.md).

Where the remedy is long or conditional, the hint points at
`promptc explain <ID>`, which serves the catalogue's `rationale` and
`remedy`.

## Message wording

State the measurement and the threshold, so the reader can judge the
finding without re-running anything:

```
Hedge density 7.2/1k tok, threshold 4.0 (31 hits in 4,300 tok).
Most frequent: 'generally', 'prefer', 'reasonable', 'where appropriate'.
```

Not `Too many hedges.` — that gives the reader nothing to act on and no way
to tell whether the rule is miscalibrated.

For a budget overrun, the breakdown matters more than the total:

```
Assembled prompt is 34,201 tok; budget is 21,768. Over by 12,433.
Largest fragments: `gdb-debugging` 4,940, `core-rules` 3,102, `type-system` 1,880.
```

Multi-line messages are fine. The text renderer indents continuation lines.

## `data`

Structured fields for tooling. Anything a caller might want to compare,
sort, or threshold goes here rather than being parsed back out of the
message:

```python
data = {
    "tokens": total, "budget": budget, "over": over,
    "tokenizer": counter.describe(), "profile": profile.name,
}
```

Tests assert on `data`, not on message text. It is omitted from JSON when
empty.

## Severity

| | Meaning | Effect |
|---|---|---|
| `ERROR` | A decidable fault | Exit code 1 |
| `WARN` | A heuristic, or hygiene | No effect on exit code |
| `INFO` | Context | No effect |

Only errors fail the build. A heuristic rule may never be an `ERROR` —
see [invariants.md](invariants.md#2-errors-are-decidable-warnings-are-heuristics).

## Locations

`file` is project-relative, so diagnostics are stable across machines.
`line` is 1-indexed into the *file*, not the fragment body —
`Fragment.body_line` does that translation, accounting for the frontmatter.

Where a finding is about an assembly rather than a file, the pseudo-path
`<assembly:task-id>` is used with `line = 0`. PC105 is the only rule that
does this, because position only means anything once fragments are
combined.

## Sorting

`Report.sorted()` orders by severity, then file, then line, then rule id.
Deterministic, so a diff between two runs is a real change — the same
requirement as [assembly](invariants.md#3-assembly-is-deterministic).
