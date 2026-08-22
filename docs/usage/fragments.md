# Writing fragments

A fragment is markdown with YAML frontmatter. The metadata is what makes
the [structural checks](../coding-standard/invariants.md#2-errors-are-decidable-warnings-are-heuristics)
decidable.

```markdown
---
id:        unchecked-return
kind:      recipe            # task | rule | recipe | workflow | example | glossary
title:     Guard a return value before using it
triggers:  [unchecked_return, null_deref]
requires:  [core-fidelity, type-system]
provides:  ["work item", "guard clause"]
contract:  contracts/patched-source.gbnf
budget:    600
priority:  0
---

Body.
```

## Fields

| Field | Does |
|---|---|
| `id` | Addressing for `requires` and `{{ref:}}`. Must be unique (PC008) |
| `kind` | Sets assembly order and whether a contract is required |
| `title` | Heading text when assembled |
| `triggers` | Mechanical routing. A detector name maps to a recipe by lookup |
| `requires` | Bounds what this fragment may reference. Resolved transitively |
| `provides` | Terms of art defined here. Builds the glossary PC007 checks |
| `contract` | Grammar or schema. Required on tasks (PC005) |
| `budget` | Optional per-fragment token ceiling |
| `priority` | Breaks a trigger tie. Higher wins (PC009) |

Scalar values are accepted where a list is expected —
`triggers: single_trigger` becomes `["single_trigger"]`.

## Kinds and assembly order

Fragments are emitted in kind bands, with dependency order preserved inside
each band:

```
glossary -> rule -> workflow -> recipe -> example -> task
```

Terms are defined before the rules that use them; shared constraints are
stated before the pattern-specific steps that assume them; the task itself
comes last, closest to where generation begins.

Only `task` requires a `contract`.

## Triggers and routing

Routing is a dictionary lookup with deliberately no scoring or inference: a
detector emits a name, that name selects a recipe.

```yaml
triggers: [unchecked_return, null_deref]
```

One recipe per trigger. If two claim the same trigger at equal priority
that is PC009, resolved by giving one a higher `priority`.

The routed set is sorted before assembly, so the prompt depends on the
*set* of triggers rather than the order a detector printed them in.

## References

Use `{{ref:fragment-id}}`, and declare the target in `requires`:

```markdown
requires: [error-conventions]
---
Follow the error conventions in {{ref:error-conventions}} first.
```

**Prose references are always errors** — "see above", "§20", "the list
below", "as described earlier", "the previous section".

Fragments assemble in different combinations per task, so a positional
reference points at nothing in most assemblies. The failure is silent: the
model reads an instruction to consult something it cannot see and
improvises. That is PC001, and it is the single most common breakage when a
monolithic prompt is split.

## Glossary terms

```markdown
---
id: glossary
kind: glossary
provides: ["work item", "guard clause"]
---

**work item** — one unit of work: the input files plus the answer expected.
**guard clause** — an early return that rejects invalid input up front.
```

Any fragment using a declared term must be able to see its provider, via
`requires`. That is PC007.

Only terms some fragment actually `provides` are checked — an ordinary word
nobody declared is not a term of art and is left alone.

## Example blocks

Fenced blocks are extracted and run through the matching verifier:

````markdown
Before — the shape you will encounter:

```c promptc:noverify
int n = parse(input);
use(n);
```

After — this block IS verified, so it must build:

```c
int n = parse(input);
if (n < 0) {
    return -1;
}
use(n);
```
````

`promptc:noverify` on the fence skips a block. Use it for "before" examples
that are deliberately broken; without it they fail PC006.

## Suppressing a rule

```markdown
<!-- promptc-disable PC100: domain vocabulary is irreducibly hedged here;
     no pass-rate delta measured in eval run 2026-08-22 (n=480) -->
```

A bare `promptc-disable PC100` is itself an error (PC011). A gate an agent
loops against is a gate an agent learns to satisfy cheaply, so every
silenced rule leaves a reviewable trace.

Suppressions are scoped to their file and their rule. A stale one — no
longer matching anything — is reported as PC012.

`promptc check --no-suppress` reports findings anyway. Rising suppression
counts mean a rule is miscalibrated, not that the prompts improved.
