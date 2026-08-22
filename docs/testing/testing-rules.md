# Testing a rule

## Two tests minimum

**Every rule gets at least one test that trips it, and one proving it
clears once the fault is fixed.**

A rule with only the first is indistinguishable from a rule that always
fires, and the positive test passes either way. PC104 is the cautionary
shape: a banned synonym that is a substring of its canonical term makes
correct usage report itself, and only the paired negative test can catch
that.

```python
def test_explicit_ref_needs_a_declared_require(project, fragment_file, load_config, rules_in):
    fragment_file("helper", """
        ---
        id: helper
        kind: rule
        ---
        Helper body.
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Follow {{ref:helper}} exactly.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC001" in rules_in(report)

def test_explicit_ref_passes_when_required(project, fragment_file, load_config, rules_in):
    # ... identical, except `requires: [helper]` on the task
    report = run_check(load_config(), examples = False)
    assert "PC001" not in rules_in(report)
```

The pair should differ by exactly the fault. Anything else and you have not
shown the rule is responding to what you think it is.

## Pass `examples = False`

Unless the test is specifically about PC006. It skips every verifier
subprocess and keeps the test in the [unit suite](unit-tests.md):

```python
report = run_check(load_config(), examples = False)
```

## Test the message's structure, not its words

Assert on rule ids and `data`. Message text is meant to be edited for
clarity, and a test that pins it makes improving a diagnostic feel
expensive. See [assertions.md](assertions.md).

```python
assert errors[0].data["budget"] == 1600           # good
assert "budget is 1600" in errors[0].message      # brittle
```

## Cover the interesting boundaries

Beyond the pair, a rule usually has one or two edges worth pinning:

**Where it abstains.** PC100 skips fragments under 100 tokens, because the
density figure is noise at that size:

```python
def test_hedge_density_skips_short_fragments(project, fragment_file, load_config, rules_in):
    """Under 100 tokens the density figure is noise, so the rule abstains."""
```

**Where it is scoped.** PC007 only checks terms some fragment actually
declares via `provides` — an ordinary word nobody declared is not a term of
art:

```python
def test_a_word_nobody_declares_is_not_a_term(...):
```

**Where a related mechanism resolves it.** A trigger collision clears when
one recipe is given a higher `priority`:

```python
def test_priority_resolves_a_collision(project, fragment_file, build_index):
    assert index.trigger_collisions() == []
    assert [item.id for item in index.route(["shared"])] == ["r1"]
```

## Heuristic rules

`tests/rules/test_heuristic.py` pins **behaviour, not truth**: a rule fires
above its threshold and stays quiet below it.

Whether the threshold is the *right* one is a question for
`promptc calibrate` against real pass rates, never for a unit test. Do not
write a test that encodes a threshold value as if it were correct — you
will be asserting that a guess is right, and the moment calibration moves
it your test fails for no reason.

```python
HEDGED = "You should generally prefer the reasonable option where appropriate. " * 40
PLAIN = "Set the field to zero. Return the pointer. Write the result to disk. " * 40
```

Two corpora, obviously either side of any plausible threshold. That is the
level of precision a heuristic test should aim for.

Also assert the message reports its measurement, since that is what makes a
warning judgeable:

```python
def test_hedge_message_reports_measurement_and_threshold(...):
    assert "threshold" in finding.message
    assert finding.data["density"] > finding.data["threshold"]
```

## The catalogue

`tests/rules/test_base.py` tests the rule catalogue as a *structure*, and
its tests are parametrized across every registered rule — so a new rule is
covered the moment it is registered, without anyone writing a test for it:

```python
@pytest.mark.parametrize("rule", base.all_rules(), ids = lambda r: r.id)
def test_every_rule_documents_itself(rule):
    """Summary, rationale and remedy are what `explain` prints."""
    assert rule.name
    assert rule.summary
    assert rule.rationale
    assert rule.remedy
```

What it enforces:

- Every rule has a rationale and a remedy, and the rationale does not
  merely restate the summary.
- Ids are unique and well-formed (`PC` plus three digits).
- No `PC1xx` heuristic is an `ERROR`.
- Only heuristics carry `calibrated = True`.
- Among `PC0xx`, only `PC010`, `PC012` and `PC014` are warnings — the
  hygiene rules, listed explicitly so a fourth cannot appear silently.

Adding a rule that violates any of these fails the suite without anyone
having to notice in review. That is the point.

## Checklist

For a new rule, in its test file:

- [ ] A test that trips it
- [ ] A test proving it clears when fixed
- [ ] Any abstention boundary
- [ ] For a heuristic: fires above threshold, quiet below, message reports
      the measurement
- [ ] `examples = False` unless testing PC006
- [ ] Assertions on ids and `data`, not message wording
