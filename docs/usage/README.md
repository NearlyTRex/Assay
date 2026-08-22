# Usage

| | |
|---|---|
| [installing.md](installing.md) | Requirements, install, optional dependencies |
| [quick-start.md](quick-start.md) | First project, and refactoring an existing prompt |
| [commands.md](commands.md) | Every command and flag |
| [configuration.md](configuration.md) | The `promptc.yaml` reference |
| [fragments.md](fragments.md) | Frontmatter fields, references, suppressions |
| [eval.md](eval.md) | Corpus, holdout, scorecard, portability index, calibration |
| [agent-loop.md](agent-loop.md) | Driving promptc from a model, and exit codes |

## In one screen

```bash
promptc init .                       # promptc.yaml + promptlib/ + contracts/
promptc new task fix-thing           # scaffold an entry point
promptc check --profile local        # the gate — exit 0 or 1
```

Refactoring an existing monolith:

```bash
promptc split big-prompt.md --level 3          # dry run
promptc split big-prompt.md --level 3 --apply
promptc check --no-examples                    # drive the cleanup loop
```

Measuring it:

```bash
promptc eval --profile local-7b --profile reference --split test --out results.json
promptc calibrate results.json
```

## The two guarantees

| | `promptc check` | `promptc eval` |
|---|---|---|
| Claim | This prompt is well-formed | This prompt works on this model |
| Basis | Decidable facts + verifier exit codes | Measured pass rate over a labelled corpus |
| Cost | Milliseconds, no model | Minutes to hours, runs a model |
| Use | Pre-commit hook, agent edit loop | Before changing a threshold or a model |
