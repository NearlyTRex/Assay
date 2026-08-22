# Adding a rule

## Checklist

1. **Pick the band.** `PC0xx` for a decidable fact, `PC1xx` for a measured
   heuristic. Take the next free number; never renumber an existing rule,
   because ids appear in suppression comments in user repositories.

2. **Register it in `rules/base.py`** with `summary`, `rationale` and
   `remedy`. The rationale explains *why the thing is a problem* — this is
   what `promptc explain` prints, and it is the only place that reasoning
   lives:

   ```python
   register(Rule(
       "PC016", "duplicate-trigger-in-fragment", Severity.ERROR,
       "A fragment lists the same trigger twice.",
       "A repeated trigger is always a copy-paste error, and it makes the "
       "routing table lie about how many patterns a recipe serves.",
       "Remove the duplicate entry from `triggers:`.",
   ))
   ```

   A rationale that paraphrases the summary is caught by
   `tests/rules/test_base.py`.

3. **Implement the check** in `rules/structural.py` or
   `rules/heuristic.py`. Return a list of `Diagnostic`; do not print, do
   not raise.

4. **Wire it into `rules/__init__.py:run_check`**, in the band it belongs
   to. Order within a band does not matter — the report sorts.

5. **Add tests** — at minimum one that trips it and one proving it clears
   once fixed. See [../testing/testing-rules.md](../testing/testing-rules.md).

6. **Document it** in the README rule table.

## Extra steps for a heuristic

A `PC1xx` rule additionally needs:

7. **A default threshold** in `config.DEFAULT_THRESHOLDS`, deliberately
   loose. An uncalibrated install should not drown an author in noise.

8. **`calibrated = True`** on the catalogue entry, so `explain` tells the
   reader the threshold is provisional.

9. **A feature extractor** in `calibrate.py`, so the rule can be measured:

   ```python
   def _my_feature(item, counter, config):
       """Return the measured value, or None when not applicable."""
       ...

   FEATURES = [
       ...
       ("PC106", "my_feature", _my_feature),
   ]
   ```

   Returning `None` for fragments where the feature does not apply is what
   keeps the correlation honest — a fragment too short to measure must not
   contribute a zero.

10. **Never ship it as an `ERROR`.** Enforced by `test_heuristic_rules_never_error`.

## Before merging

Three questions from [invariants.md](invariants.md):

1. Does the rule consult a model for a judgement? It must not.
2. Is it an `ERROR` resting on a threshold rather than a fact? Demote it.
3. Does implementing it require the package to know about a specific
   language or toolchain? Move that into `promptc.yaml`.

## Retiring a rule

`calibrate` reporting `not-predictive` or `inverted` for a heuristic is
grounds for removal, not for tuning. Demote to `INFO` first if you want a
grace period, then delete the rule, its extractor, its default threshold
and its tests together.

Leave the id retired. Do not reuse it.
