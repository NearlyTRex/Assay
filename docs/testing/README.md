# Testing guidelines

344 tests. 281 unit, 63 integration. No test contacts a real model.

| | |
|---|---|
| [layout.md](layout.md) | The `tests/` mirror, and how to check it |
| [unit-tests.md](unit-tests.md) | The default: in-process, fast, unmarked |
| [integration-tests.md](integration-tests.md) | Markers, and the three boundaries that earn one |
| [models.md](models.md) | Why no test may contact a real model, and what to do instead |
| [fixtures.md](fixtures.md) | What `conftest.py` provides |
| [testing-rules.md](testing-rules.md) | Two tests per rule, heuristics, the catalogue |
| [assertions.md](assertions.md) | What to assert, and what never to |

## Running

```bash
python3 -m pytest tests/ -q                        # all 344
python3 -m pytest tests/ -q -m "not integration"   # 281, under a second
python3 -m pytest tests/ -q -m integration         # 63, ~3s
python3 -m pytest tests/rules/ -q                  # one area
python3 -m pytest tests/test_split.py -q           # one module
python3 -m pytest tests/ -q -k budget              # by name
```

`pytest` comes from `pip install -e ".[dev]"`.
Tests import `promptc` via a `sys.path` insert in `conftest.py`, so no
install step is needed.

## The four rules

1. **`tests/` mirrors `promptc/`**, one file per module. A new module ships
   with its test file in the same change. — [layout.md](layout.md)

2. **Unmarked means unit**: in-process, offline, no writes outside
   `tmp_path`. Anything crossing a process boundary carries
   `@pytest.mark.integration`. — [integration-tests.md](integration-tests.md)

3. **No test contacts a real model.** Use `CommandBackend` with a
   deterministic stand-in, and vary behaviour on the seed. —
   [models.md](models.md)

4. **Every rule gets two tests**: one that trips it, one proving it clears
   once fixed. — [testing-rules.md](testing-rules.md)

## When a test finds a bug

Fix the source, not the test — unless the test encoded the wrong
expectation, which happens and is fine to correct.

Keep the test that caught it, and note in a comment what it caught. That
comment is the cheapest regression guard there is, and it stops a later
reader from "simplifying" the assertion away.

Tests asserting a **negative** or an **invariant** find more than happy-path
tests do: that the same input in a different order gives the same output,
that a rule stays quiet on correct input, that a search finds the middle
rather than the edge. Happy paths confirm what you already believed.
