# Test layout

## The mirror

`tests/` mirrors `promptc/` one file per module. A module has exactly one
test file, at the matching path.

```
promptc/split.py                 ->  tests/test_split.py
promptc/rules/structural.py      ->  tests/rules/test_structural.py
promptc/evalharness/corpus.py    ->  tests/evalharness/test_corpus.py
promptc/rules/__init__.py        ->  tests/rules/test_init.py
promptc/__main__.py              ->  tests/test_main.py
```

`__init__` maps to `test_init`, `__main__` to `test_main`.

## Why each directory has an `__init__.py`

Three files are named `test_init.py` — one at the root, one in `rules/`,
one in `evalharness/`. Without `__init__.py` in each test directory,
pytest cannot disambiguate them and collection fails outright with a
basename collision.

The test tree therefore mirrors the source in this too: both are packages
at every level.

## A new module ships with its test file

In the same change, not a follow-up. The mirror is mechanically checkable,
so a gap is visible rather than a matter of opinion:

```bash
for src in $(find promptc -name '*.py' -not -path '*__pycache__*'); do
    p=${src#promptc/}; p=${p%.py}
    n=$(basename "$p"); d=$(dirname "$p"); [ "$d" = "." ] && d="" || d="$d/"
    [ "$n" = "__init__" ] && n="init"; [ "$n" = "__main__" ] && n="main"
    [ -f "tests/${d}test_${n}.py" ] || echo "MISSING: tests/${d}test_${n}.py"
done
```

Currently reports nothing: 22 modules, 22 test files.

## Inside a file

Repeat the source file's section banners, in the same order, so the two
read side by side:

```python
###########################################################
# PC001 -- dangling references
###########################################################
def test_prose_reference_is_an_error(...):
    ...
```

Where a module has one concern per banner, the test file has one banner per
concern too. `tests/rules/test_structural.py` is banded by rule id;
`tests/evalharness/test_score.py` by extraction, verification, taxonomy.

## Module-level marks

Where every test in a file crosses a process boundary, mark the module
rather than each function:

```python
pytestmark = pytest.mark.integration
```

`tests/test_cli.py` does this. Everywhere else, mark individually — a file
that is *mostly* integration usually has pure tests worth keeping fast.

## Current shape

```
tests/
  __init__.py
  conftest.py                    shared fixtures
  test_assemble.py               test_calibrate.py    test_cli.py
  test_config.py                 test_diagnostics.py  test_fragment.py
  test_graph.py                  test_index.py        test_init.py
  test_main.py                   test_split.py        test_tokens.py
  test_verify.py
  rules/
    __init__.py
    test_base.py                 test_heuristic.py
    test_init.py                 test_structural.py
  evalharness/
    __init__.py
    test_corpus.py               test_init.py         test_report.py
    test_runner.py               test_score.py
```

344 tests: 281 unit, 63 integration.
