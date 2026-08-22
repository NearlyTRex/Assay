# Assay — `promptc`

A compiler for prompts. Assemble modular prompt fragments, validate them
against decidable rules, and measure them against a corpus scored by
external verifiers.

The design premise: a model writes the prompt source, and an external
program decides whether it is valid — the same relationship a compiler has
with the code you feed it. `promptc check` is the gate. Edit, re-run,
repeat until it exits zero.

An assay determines composition by external test rather than by opinion.
That is the whole stance: no model judges anything here.

Nothing is specific to any project or language. All domain knowledge lives
in `promptc.yaml`.

## Prior art

[lintlang](https://github.com/hermes-labs-ai/lintlang) does zero-LLM static
gating of agent configs and system prompts in CI, on the same instinct as
the structural rules below. Worth reading; it may well have checks this
should adopt.

The parts here it does not cover: fragment assembly with dependency
resolution and trigger routing, token budgets measured with the target
model's own tokenizer, example blocks verified by running an external
toolchain, and the eval/calibrate loop that forces every heuristic to earn
its threshold against measured pass rate.

Adjacent but different in kind: [promptfoo](https://github.com/promptfoo/promptfoo)
(eval harness — good enough that `promptc eval` may end up wrapping it) and
[DSPy](https://github.com/stanfordnlp/dspy) (optimises prompts against a
metric instead of validating hand-written ones).

## The two guarantees, kept apart

| Command | Claim | Cost |
|---|---|---|
| `promptc check` | **This prompt is well-formed.** References resolve, it fits the context window, every example passes its verifier, the output contract exists. | Fast, deterministic, no model. Safe as a pre-commit hook. |
| `promptc eval` | **This prompt works on this model.** Measured pass rate over a labelled corpus. | Slow, statistical. The model is the system under test; your verifier is the judge. |

Conflating these is how prompt tooling turns into unfalsifiable scoring.
Every heuristic rule ships as a `WARN` with a placeholder threshold, and
`promptc calibrate` is what decides whether it stays, tightens, or is
deleted.

## Quick start

```bash
promptc init .
promptc new task fix-thing
promptc new recipe handle-pattern-x
promptc check --profile local
```

To decompose an existing monolithic prompt:

```bash
promptc split big-prompt.md --level 3            # dry run
promptc split big-prompt.md --level 3 --apply
promptc check --no-examples                       # drive the cleanup loop
```

`split` slices on the heading tree, derives ids, wires `requires` to the
parent section, and rewrites the section-number references it can resolve
exactly — then stops. It never rewrites prose; that is the authoring
model's job, gated by `check`.

## Fragments

A fragment is markdown with YAML frontmatter. The metadata is what makes
the checks decidable.

```markdown
---
id:        depun-named-fields
kind:      recipe            # task | rule | recipe | workflow | example | glossary
title:     De-pun raw offsets to named fields
triggers:  [partial_struct_copy, stale_struct_offset_64bit]
requires:  [core-fidelity, type-system]
provides:  ["keep file", "de-pun"]
contract:  contracts/patched-source.gbnf
budget:    600
---

Body. Numbered steps, one worked example, no references that are not
declared in `requires`.
```

- **`triggers`** — mechanical routing. Detector names map onto recipes, so
  selection is a dictionary lookup with no model judgement.
- **`requires`** — dependency resolution. A fragment can only reference what
  it declares, which turns dangling cross-references into a build error.
- **`provides`** — builds a glossary, making vocabulary drift checkable.
- **`contract`** — the grammar or schema, so generation can fail closed.

Cross-references use `{{ref:fragment-id}}`. Prose references ("see above",
"§20", "the list below") are always errors, because fragments assemble in
different combinations and positional references cannot resolve.

## Rules

Errors are decidable facts. Warnings are heuristics that must earn their
thresholds.

| ID | Rule | Sev | Decided by |
|---|---|---|---|
| PC000 | parse-error | error | Frontmatter does not parse |
| PC001 | dangling-reference | error | Ref target absent from the assembly |
| PC002 | unresolved-require | error | No fragment with that id |
| PC003 | circular-require | error | Cycle in the dependency graph |
| PC004 | token-budget-exceeded | error | The target model's own tokenizer |
| PC005 | missing-output-contract | error | Task declares no grammar or schema |
| PC006 | example-verification-failed | error | External verifier exit code |
| PC007 | undefined-glossary-term | error | Term used, provider not required |
| PC008 | duplicate-fragment-id | error | Index collision |
| PC009 | trigger-collision | error | Two recipes claim one trigger, no priority |
| PC010 | orphan-fragment | warn | No task or trigger reaches it |
| PC011 | suppression-without-justification | error | Bare `promptc-disable` |
| PC012 | unused-suppression | warn | Suppression matches no diagnostic |
| PC013 | missing-contract-file | error | Declared contract path does not exist |
| PC014 | tokenizer-unavailable | warn | Budget fell back to estimation |
| PC100 | hedge-density | warn | Wordlist per 1k tokens · *calibrated* |
| PC101 | negation-density | warn | Prohibitions vs total instructions · *calibrated* |
| PC102 | instruction-count | warn | Imperatives per fragment · *calibrated* |
| PC103 | sentence-complexity | warn | textstat grade level · *calibrated* |
| PC104 | vocabulary-drift | warn | Synonyms for a canonical term |
| PC105 | critical-rule-buried | warn | MUST/NEVER in the middle · *calibrated* |

`promptc explain PC004` prints the rationale and the remedy for any rule, so
the docs never need to be in an agent's context.

Suppression requires a written reason:

```markdown
<!-- promptc-disable PC100: domain vocabulary is irreducibly hedged here;
     no pass-rate delta measured in eval run 2026-08-22 (n=480) -->
```

A gate an agent loops against is a gate an agent learns to satisfy cheaply.
`promptc check --no-suppress` reports findings anyway. Rising suppression
counts mean a rule is miscalibrated, not that the prompts improved.

## Configuration

`promptc.yaml` is the entire domain boundary. promptc knows how to run a
command you gave it and read an exit code.

```yaml
library: promptlib
contracts: contracts

verifiers:
  - id: cpp-compiles
    match: cpp
    command: ["scripts/test_compilation.sh", "{file}"]

profiles:
  qwen-7b:
    context: 32768
    tokenizer: hf:Qwen/Qwen2.5-Coder-7B
    reserve: 9000              # held back for the runtime work item
    endpoint: http://127.0.0.1:8080
    backend: llamacpp

eval:
  task: fix-compilation
  verifiers: [cpp-compiles, suspects-clean]
  extract: fence
  suffix: .cpp
  attempts: 5
  baseline_profile: claude

corpus:
  root: annotations/nocedit.exe/pseudocode/src
  discover: "**/*.keep.cpp"
  golden_suffix: ".keep.cpp"     # never shown to the model
  inputs: ["{stem}.cpp", "{stem}.asm", "{stem}.json"]
  triggers_command: ["scripts/detect.sh", "{stem}"]
  stratify_by: triggers
  holdout: 0.2
```

## Eval

Three outputs matter:

- **Pass rate** — `pass@1` and `pass@k`, plus mean attempts to green. With a
  verifier downstream, retries are nearly free locally, so `pass@k` is the
  number that reflects real cost.
- **Per-trigger scorecard** — pass rate per routed recipe, worst first. This
  is what tells you which recipe to rewrite next.
- **Failure taxonomy** — `empty` / `no_answer` / `verifier_failed:<id>` /
  `backend_error`. Each bucket points at a different fix: no extractable
  block means the output contract is wrong, a verifier failure means the
  recipe content is.

Similarity to the golden answer is recorded but **never decides pass or
fail** — a different-but-valid answer is not wrong.

Run several profiles to get the **portability index**
(`local_pass_rate / baseline_pass_rate`). Driving that toward 1.0 is what
"optimised for open-weight models" means as a number, and it is scored
entirely by external verifiers.

```bash
promptc eval --profile qwen-7b --profile claude --split test --out results.json
promptc calibrate results.json
```

`calibrate` correlates each heuristic feature against measured per-recipe
pass rate and reports `predictive` / `not-predictive` / `inverted`. One eval
run gives one data point per routed recipe, so this works from the first
run. Rules that do not predict get demoted or deleted.

## Backends

| Backend | For |
|---|---|
| `llamacpp` | `llama-server` — grammars, fixed seeds, prompt caching |
| `openai` | Any OpenAI-compatible endpoint |
| `command` | An argv you configure, prompt on stdin — the escape hatch for anything else |

`llama.cpp` is the one that matters for local work: ollama does not expose
grammar-constrained sampling, fixed seeds, or logprobs.

## Requirements

Python 3.10+ and PyYAML. Everything else is optional and degrades loudly:

- `tiktoken` / `tokenizers` — exact token budgets (PC004 falls back to
  character estimation and says so)
- `textstat` — PC103
- `jsonschema` — JSON Schema output contracts

Install via the JoyBox bootstrap, or `pip install -e ".[all]"`.

## Tests

```bash
python3 -m pytest tests/ -q
```
