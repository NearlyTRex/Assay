# Assay documentation

## [usage/](usage/)

| | |
|---|---|
| [installing.md](usage/installing.md) | Requirements, install, optional dependencies |
| [quick-start.md](usage/quick-start.md) | First project, and refactoring an existing prompt |
| [commands.md](usage/commands.md) | Every command and flag |
| [configuration.md](usage/configuration.md) | The `promptc.yaml` reference |
| [fragments.md](usage/fragments.md) | Frontmatter fields, references, suppressions |
| [eval.md](usage/eval.md) | Corpus, holdout, scorecard, portability index, calibration |
| [agent-loop.md](usage/agent-loop.md) | Driving promptc from a model, and exit codes |

## [coding-standard/](coding-standard/)

| | |
|---|---|
| [invariants.md](coding-standard/invariants.md) | The five architectural rules. Read first |
| [layout.md](coding-standard/layout.md) | Module structure, imports, section banners |
| [naming.md](coding-standard/naming.md) | Identifiers, rule ids, abbreviations |
| [formatting.md](coding-standard/formatting.md) | Spacing, line length, dataclasses over dicts |
| [docstrings.md](coding-standard/docstrings.md) | Module and function docstrings, with the parts spelled out |
| [error-handling.md](coding-standard/error-handling.md) | Catching narrowly, remedies, subprocesses, temp files |
| [diagnostics.md](coding-standard/diagnostics.md) | Findings, fix hints, message wording |
| [adding-a-rule.md](coding-standard/adding-a-rule.md) | The full checklist for a new rule |

## [testing/](testing/)

| | |
|---|---|
| [layout.md](testing/layout.md) | The `tests/` mirror, and how to check it |
| [unit-tests.md](testing/unit-tests.md) | The default: in-process, fast, unmarked |
| [integration-tests.md](testing/integration-tests.md) | Markers, and the three boundaries that earn one |
| [models.md](testing/models.md) | Why no test may contact a real model, and what to do instead |
| [fixtures.md](testing/fixtures.md) | What `conftest.py` provides |
| [testing-rules.md](testing/testing-rules.md) | Two tests per rule, heuristics, the catalogue |
| [assertions.md](testing/assertions.md) | What to assert, and what never to |

## The one invariant

Everything in this repository follows from a single rule:

> **No model judges anything.**

`check` is a pure function of the source tree. `verify-examples` runs a
command you configured and reads an exit code. `eval` runs a model, but the
model is the *system under test* — pass and fail come from your verifier.
`calibrate` correlates lint features against measured pass rate.

There is no LLM-as-judge anywhere, and a change that introduces one is a
change to the premise of the tool, not a feature. If you find yourself
wanting a model to score output quality, the answer is a better external
verifier.

See [coding-standard/invariants.md](coding-standard/invariants.md) for the
full set.

## The two guarantees

Keeping these apart is what stops the tool from drifting into
unfalsifiable prompt-scoring.

| | `promptc check` | `promptc eval` |
|---|---|---|
| Claim | This prompt is well-formed | This prompt works on this model |
| Basis | Decidable facts + verifier exit codes | Measured pass rate over a labelled corpus |
| Cost | Milliseconds, no model | Minutes to hours, runs a model |
| Use | Pre-commit hook, agent edit loop | Before changing a threshold or a model |

A heuristic rule may never fail a build on a threshold that `calibrate` has
not measured. See [coding-standard/adding-a-rule.md](coding-standard/adding-a-rule.md).
