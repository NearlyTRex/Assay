# Eval

`promptc eval` is the only command that runs a model — and even here the
model is the *system under test*. Pass and fail come from the verifier
commands in `promptc.yaml`.

```bash
# One profile, small stratified sample, on the tuning split
promptc eval --profile local-7b --per-group 5 --split dev

# Two profiles for a portability index, reported on held-out data
promptc eval --profile local-7b --profile reference \
             --split test --baseline reference --out results.json
```

## The holdout

The corpus splits deterministically by hash of `(seed, stem)`. Tune prompts
on `dev`; report on `test`.

Tuning against everything overfits the prompt to those specific items and
teaches you nothing about the next one. This is the single easiest way to
produce a number that is both impressive and meaningless.

`--split all` exists for one-off inspection. Do not quote a figure from it.

## Sampling

`--per-group N` takes at most N items from each stratum, so a sample covers
every routed recipe rather than over-representing whichever pattern is most
common. Deterministic given the corpus seed.

`--limit N` caps the total after stratification, for a quick smoke run.

## What comes out

### Pass rate

`pass@1` and `pass@k`, plus mean attempts to green.

With a verifier downstream and a local model, retries cost only
electricity, so `pass@k` is the figure that reflects real cost. A 14B model
at `pass@10` can beat a much larger one at `pass@1` for a fraction of the
price — which is the whole argument for running locally on verifiable work.

Attempts stop at the first success, so `mean_attempts_to_green` is a real
cost signal rather than a constant.

### Per-trigger scorecard

Pass rate per routed recipe, worst first:

```
  per-trigger scorecard (worst first)
    unbounded_copy       ###...............   18.2%  (2/11)
    unchecked_return     #########.........   47.1%  (8/17)
    null_deref           ################..   88.9%  (24/27)
```

This is the actionable output. A recipe at 18% tells you exactly what to
rewrite next, and the number tells you whether the rewrite helped.

An item counts towards every trigger that fired for it, so a recipe's score
reflects every case it was asked to handle.

### Failure taxonomy

Each bucket points at a different fix:

| Outcome | Means | Fix |
|---|---|---|
| `empty` | Model returned nothing | Prompt or runtime |
| `no_answer` | Nothing extractable from the output | Output contract |
| `verifier_failed:<id>` | Ran, rejected by that verifier | Recipe content |
| `backend_error` | Infrastructure | Not the prompt |

The distinction between `no_answer` and `verifier_failed` matters: the
first says the model did not produce a parseable answer at all, which is a
contract problem, not a knowledge problem.

### Portability index

```
  portability index (vs reference)
    local-7b          0.641   (57.0% / 88.9%)
```

`local_pass_rate / baseline_pass_rate`. Driving it toward 1.0 is what
"optimised for open-weight models" means as a number, and it is scored
entirely by external verifiers with no model judging anything.

Reported only when a baseline profile is named and it scored above zero —
dividing by a baseline that failed everything says nothing.

## Similarity is not a score

Similarity to the golden answer is recorded but **never decides pass or
fail**. A different-but-valid fix is not wrong.

Treat a passing answer with low similarity as interesting, not suspect —
it often means the model found a legitimate alternative, and occasionally
it means your verifier is too permissive.

## Calibration

```bash
promptc calibrate results.json
```

One eval run yields one data point per routed recipe, so this works from
the first run. Each heuristic feature is correlated against measured
per-recipe pass rate:

```
feature                r        p       n    verdict

hedge_density        -0.712   0.032    9    predictive
                     higher values track lower pass rates — keep the rule
                     PC100: 6.0 -> 4.2 (proposed)

negation_ratio       +0.104   0.790    9    not-predictive
                     no measurable relationship — demote to info or delete
```

| Verdict | Means |
|---|---|
| `predictive` | Higher values track lower pass rates — keep the rule |
| `inverted` | Higher values track *higher* pass rates — the rule is backwards |
| `not-predictive` | No measurable relationship — demote to info or delete |
| `weak` | Too weak to act on — gather more data |
| `insufficient-data` | Too few routed recipes to say anything |

`inverted` is the verdict that earns the whole exercise: it means a rule
has been firing on the thing that actually helps.

Proposed thresholds are starting points, not settings. The proposal finds
where pass rate falls off hardest, by maximising the separation between the
two sides of the cut. Apply one at a time and re-run on the held-out split
to confirm the change is real.

## Backends

| Backend | For |
|---|---|
| `llamacpp` | `llama-server` — grammars, fixed seeds, prompt caching |
| `openai` | Any OpenAI-compatible endpoint |
| `command` | An argv you configure, prompt on stdin |

`command` is the escape hatch that keeps cloud models usable as a
portability baseline without the package knowing anything about them. It is
also what the [test suite](../testing/models.md) drives, since no test may
contact a real model.

## Grammars

When a task's `contract` ends in `.gbnf`, it is passed to the backend as a
sampling grammar, so malformed output becomes unrepresentable rather than
merely discouraged.

A `.json` contract is not passed to the backend — not every backend can
enforce a schema — and should be checked by a verifier instead.
