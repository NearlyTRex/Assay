# Driving promptc from a model

The whole design assumes a model authors the prompt source and an external
program decides whether it is valid — the same relationship a compiler has
with code.

## The loop

```bash
while ! promptc check --no-examples --format json > diag.json; do
    # agent reads diag.json, edits the named file:line, repeats
done
promptc check          # full pass, examples included
```

One gate, one loop. Nothing else needs to be understood to make progress.

## What makes it drivable

**`--format json` everywhere.** Diagnostics arrive as structured records —
no output parsing:

```json
{
  "rule": "PC001",
  "severity": "error",
  "message": "Reference to `error-conventions` is not declared in `requires`.",
  "file": "recipes/unchecked-return.md",
  "line": 41,
  "col": 0,
  "fix_hint": "add `error-conventions` to this fragment's `requires`.",
  "data": {"target": "error-conventions"}
}
```

**Fix hints name the concrete edit.** An agent acts without loading
documentation. Where the remedy is longer, `promptc explain <ID>` serves
the rationale and remedy on demand:

```bash
promptc explain PC004 --format json
```

**Scaffolds start valid.** `promptc new recipe <id>` emits required
frontmatter and a stub example, so a fresh fragment cannot be born
malformed.

**Deterministic, stable output.** Diagnostics sort by severity, file, line,
rule. Assembly is byte-stable. A diff between two runs means a real change.

**Non-interactive.** No TTY assumptions, no prompts, no colour when piped.
`NO_COLOR` is honoured.

**Findings on stdout, faults on stderr.** An agent parses stdout; stderr is
reserved for the tool having failed rather than the prompt. There is a test
pinning this.

## Exit codes

| Code | Means |
|---|---|
| 0 | Success, or findings but no errors |
| 1 | Errors found, or a command failed |
| 2 | Bad invocation — unknown rule, missing config, unreadable file |
| 130 | Interrupted |

Warnings never affect the exit code. Only `ERROR` severity does.

## The failure mode to guard against

A gate an agent loops against is a gate an agent will learn to satisfy
cheaply.

Suppression comments are the obvious escape hatch, which is why they demand
a written justification — a bare `promptc-disable PC100` is itself an error
(PC011). `promptc check --no-suppress` reports findings anyway, and a stale
suppression is reported as PC012.

**If suppression counts start climbing, that is a signal a rule is
miscalibrated, not that the prompts got better.** Take it to
`promptc calibrate` rather than tightening the wording of the rule.

## What the agent should not be asked to do

`split` deliberately stops at proposing structure. It does not rewrite
prose, invent `triggers`, or fill in `provides`, and neither should any
future command — the moment the tool makes editorial calls it becomes
another thing you have to verify.

The division is: **the tool does what is mechanical, the model does what is
editorial, and the gate decides whether the result is valid.**
