# Quick start

## A new prompt library

```bash
promptc init .                       # promptc.yaml + promptlib/ + contracts/
promptc new task fix-thing           # scaffold an entry point
promptc new recipe handle-pattern-x  # scaffold a routed recipe
promptc check --profile local        # the gate
```

`promptc new` emits valid frontmatter, so a fresh fragment cannot be born
malformed. A freshly `init`-ed project passes its own `check` — there is a
test pinning that.

## Refactoring an existing prompt

```bash
promptc split big-prompt.md --level 3              # dry run, writes nothing
promptc split big-prompt.md --level 3 --apply
promptc check --no-examples                        # drive the cleanup loop
```

`--level 3` means `###` headings become leaf fragments and `##` become the
parent rules they hang off. Adjust to match the document.

### What split does

- Slices on the heading tree.
- Derives fragment ids from headings, deduplicating collisions (`overview`,
  `overview-2`).
- Wires `requires` to the parent section.
- Records numbered sections (`### 20. Unchecked return value`) as
  `legacy_section: 20`.
- Rewrites `§20`-style references to `{{ref:unchecked-return-value}}` where
  the number resolves, **and adds each rewritten target to `requires`** — a
  reference it just created is a dependency it knows about.
- Turns a self-reference into the words "this recipe".

### What split does not do

It never rewrites prose, invents `triggers`, or fills in `provides`. Those
are editorial calls for the authoring model, gated by `check`. Anything it
could not resolve is reported rather than guessed at:

```
2 unresolved section reference(s) — these become PC001 errors until rewritten:
  error-handling-overview: §77
```

Keeping the tool mechanical is what makes it trustworthy. The moment it
starts making editorial calls it becomes another thing you have to verify.

### What to expect afterwards

A freshly split library reports a lot, and most of it is the work the split
deliberately left for you:

```
1 error, 70 warnings
  PC010    64      (nothing routes to these yet — no task exists)
  PC001     1      (a genuine "list below" prose reference)
  PC100     4
  PC101     1
  PC102     1
```

The orphans are expected at that point: no task fragment exists yet, so
nothing is reachable. Writing the task and mapping detector names onto
`triggers` is the next step, and each remains a `check` failure until done.

## The shape of a library

```
promptlib/
  glossary.md            kind: glossary   -- terms of art
  core-rules.md          kind: rule       -- constraints every task shares
  workflow.md            kind: workflow   -- order of operations
  fix-source.md          kind: task       -- an entry point, with a contract
  recipes/
    unchecked-return.md      kind: recipe -- triggers: [unchecked_return]
    unbounded-copy.md        kind: recipe -- triggers: [unbounded_copy]
contracts/
  patched-source.gbnf
```

Assembly order follows kind: glossary, rule, workflow, recipe, example,
task. Dependencies always land before whatever required them.
