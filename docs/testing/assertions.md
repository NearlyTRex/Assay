# What to assert

## Prefer the observable contract

Assert on what a caller depends on, not on internal state.

### Rule ids and `data`

```python
assert "PC001" in rules_in(report)                # good
assert errors[0].data["budget"] == 1600           # good
assert "budget is 1600" in errors[0].message      # brittle
```

Message text is meant to be edited for clarity. A test that pins wording
makes improving a diagnostic feel expensive, which is exactly backwards —
diagnostics are the product here.

**Two deliberate exceptions**, where the text *is* the behaviour:

Asserting a fix hint exists and is non-empty:

```python
assert errors[0].fix_hint
```

Asserting a specific phrase in a `ConfigError`, where the remedy is the
whole point:

```python
assert "argv form" in str(caught.value)
assert "output_reserve" in str(caught.value)
```

### Exit codes

The agent loop is `while ! promptc check; do ...; done`, so these are
load-bearing:

| Code | Means |
|---|---|
| 0 | Clean, or findings but no errors |
| 1 | Errors found |
| 2 | Bad invocation |
| 130 | Interrupted |

```python
assert result.returncode == 1
```

Including the case that is easy to get wrong — warnings must *not* fail:

```python
def test_warnings_alone_do_not_fail_the_build(project, fragment_file):
    assert "PC010" in result.stdout
    assert result.returncode == 0
```

### Stream separation

Findings on stdout, tool faults on stderr:

```python
assert "PC005" in result.stdout
assert "PC005" not in result.stderr
```

### JSON shape

Parse it and assert on keys. Never string-match JSON:

```python
payload = json.loads(result.stdout)
assert payload["ok"] is True
assert payload["summary"]["errors"] == 0
```

### Determinism

Where output must be reproducible, produce it twice and compare:

```python
def test_assembly_is_byte_identical_across_runs(project, fragment_file, build_index):
    first = assemble.assemble(index, "task-a", ["pattern_x"])
    second = assemble.assemble(index, "task-a", ["pattern_x"])
    assert first.text == second.text
    assert first.digest() == second.digest()
```

And where the *input order* must not matter, vary it:

```python
def test_trigger_order_does_not_change_output(project, fragment_file, build_index):
    forward = assemble.assemble(index, "task-a", ["pattern_x", "pattern_y"])
    reverse = assemble.assemble(index, "task-a", ["pattern_y", "pattern_x"])
    assert forward.digest() == reverse.digest()
```

The second is the one worth writing. Routing takes its triggers from a
detector whose output order is not guaranteed, so a prompt that depended on
that order would be silently irreproducible between runs.

## Assert the invariant, not its symptom

Some properties deserve a test purely because violating them fails
silently. Capture the artefact and assert on it directly:

```python
def test_the_golden_answer_never_reaches_the_prompt(...):
    """If the model could see the golden file the whole measurement is void."""
    assert "input alpha" in prompt
    assert "golden alpha" not in prompt
```

Nothing else in the suite would catch that leak, and every number the tool
reports depends on it. See [models.md](models.md).

## Docstrings on tests

Only where the assertion needs justifying — why this is the expected
behaviour, or what would break if it changed:

```python
def test_failing_triggers_command_means_no_triggers(...):
    """A detector that finds nothing exits non-zero; that is not a run failure."""
```

A docstring restating the test name is noise. The name should already say
what is asserted; the docstring says why it matters.

## Anti-patterns

**Asserting on internals a refactor would move.** Test `route()` returns
the right fragments, not that it built an intermediate dict.

**One test with fifteen assertions.** If it fails you learn one thing.
Split by what is being claimed.

**Snapshot-matching whole outputs.** A rendered report is meant to change.
Assert the parts that are contractual.

**Testing that a mock was called.** There are no mocks here, and that is
deliberate — every fixture builds a real artefact.
