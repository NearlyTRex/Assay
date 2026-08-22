# Commands

Every command supports `--format json` where it produces findings, and none
waits on a TTY. See [agent-loop.md](agent-loop.md) for the ergonomics
behind that.

## `promptc check`

The gate. A pure function of the source tree, plus verifier exit codes when
examples are enabled.

```bash
promptc check                          # everything, text output
promptc check --profile local-7b       # adds PC004 (needs a profile)
promptc check --no-examples            # skip PC006; runs no subprocesses
promptc check --format json            # for an agent
promptc check --no-suppress            # report findings even where suppressed
promptc check --task fix-source        # limit assembly checks to one task
promptc check --triggers unchecked_return   # route recipes while checking
```

Exit `0` when there are no errors, `1` when there are. Warnings never fail
the build.

`--no-examples` is the difference between a millisecond check and one that
shells out per example block. Use it in an edit loop, and the full check in
CI.

`--profile` is required for PC004 — without a target model there is no
context size to measure against, so the budget check is skipped entirely.

## `promptc build`

```bash
promptc build fix-source                            # to stdout
promptc build fix-source --triggers unchecked_return  # route recipes
promptc build fix-source --out prompt.txt --manifest manifest.json
promptc build fix-source --profile local-7b --explain
```

`--explain` prints the token cost of each fragment instead of the prompt,
worst first. This is how you find what to cut when PC004 fires:

```
  recipe    error-handling        4,940 tok   22.7%
  rule      core-fidelity        3,102 tok   14.2%
  glossary  type-system          1,880 tok    8.6%

  total 21,768 tok (hf:Qwen/Qwen2.5-Coder-7B)
  budget 21,768 tok for profile `local-7b`
```

`--manifest` writes the assembly record: which fragments were included,
which were routed, per-fragment token counts, and a digest.

Assembly is deterministic — same tree, task and triggers give
byte-identical output, so a diff between two builds is a real change.

## `promptc new`

```bash
promptc new task fix-thing
promptc new recipe handle-pattern-x --title "Handle pattern X"
promptc new rule core-fidelity --subdir rules
```

Scaffolds from `templates/<kind>.md` with required frontmatter filled in,
so an agent starts structurally valid. Refuses to overwrite without
`--force`.

Kinds: `task`, `rule`, `recipe`, `workflow`, `example`, `glossary`.

## `promptc init`

```bash
promptc init .
promptc init ~/some/project --force
```

Writes a commented `promptc.yaml` and creates `promptlib/` and
`contracts/`. The result passes its own `check`.

## `promptc split`

```bash
promptc split big-prompt.md                        # dry run
promptc split big-prompt.md --level 3 --apply
promptc split big-prompt.md --kind rule --out promptlib/rules
promptc split big-prompt.md --format json
```

Dry run by default — nothing is written without `--apply`.

`--level` sets which heading depth becomes a leaf fragment (default 3).
`--kind` sets the kind assigned to leaves (default `recipe`).

See [quick-start.md](quick-start.md#refactoring-an-existing-prompt) for
what it does and deliberately does not do.

## `promptc graph`

```bash
promptc graph                    # tasks, what each pulls in, trigger routing
promptc graph --orphans          # fragments nothing reaches
promptc graph --format json
promptc graph --format dot | dot -Tsvg > graph.svg
```

A trigger marked `*` routes to more than one fragment — that is PC009.

## `promptc explain`

```bash
promptc explain              # list every rule
promptc explain PC004        # rationale and remedy for one
promptc explain PC004 --format json
```

Written so an agent never needs the docs in context to act on a diagnostic.
A rule whose threshold is uncalibrated says so.

## `promptc verify-examples`

```bash
promptc verify-examples
promptc verify-examples --fragment unchecked-return
promptc verify-examples --format json
```

Extracts fenced blocks, writes each to a temp file, runs the matching
verifier. A block whose fence carries `promptc:noverify` is skipped — use
that for "before" examples that are deliberately broken.

This is what `check` runs unless `--no-examples` is passed; the standalone
command is for iterating on one fragment's examples.

## `promptc eval`

Runs a model. See [eval.md](eval.md).

```bash
promptc eval --profile local-7b --per-group 5 --split dev
promptc eval --profile local-7b --profile reference --split test \
             --baseline reference --out results.json
```

## `promptc calibrate`

```bash
promptc calibrate results.json
promptc calibrate run-a.json run-b.json --format json
```

Correlates each heuristic feature against measured per-recipe pass rate.
See [eval.md](eval.md#calibration).
