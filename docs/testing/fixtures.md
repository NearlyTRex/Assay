# Fixtures

All shared fixtures live in `tests/conftest.py`. Every one builds a real
project on disk under `tmp_path`, because promptc is a pure function of a
source tree and testing it against a mock would be testing a different
program.

## What is available

| Fixture | Gives you |
|---|---|
| `project` | A minimal project root, with `small` and `big` profiles |
| `fragment_file` | Writes a fragment into the project library |
| `write` | Writes any dedented text to any path |
| `load_config` | Loads the project's config |
| `build_index` | Parses the library and returns an `Index` |
| `rules_in` | Sorted distinct rule ids from a report |

## `project`

```python
@pytest.fixture
def project(tmp_path):
    """Create a minimal promptc project and return its root.

    Ships two profiles: `small` (2,000 token context, tight reserves) for
    exercising PC004, and `big` for everything that must not trip it.
    """
```

The two profiles exist for a reason. `small` has a 2,000-token context with
200-token reserves, giving a budget of exactly 1,600 — small enough that a
few thousand words overruns it, and a round number a test can assert on:

```python
assert errors[0].data["budget"] == 1600
```

`big` has a 200,000-token context, so any test that must *not* trip PC004
can pass `profile_name = "big"` and be sure the rule is not the reason it
passed.

The fixture also creates `contracts/out.gbnf`, so tasks have a contract
path that resolves and PC013 stays quiet unless a test wants it.

## `fragment_file`

```python
fragment_file("task-a", """
    ---
    id: task-a
    kind: task
    contract: contracts/out.gbnf
    ---
    The task body.
""")
```

Text is dedented and left-stripped, so triple-quoted fragments read as the
file they become rather than as indented Python. This matters more than it
sounds: frontmatter is whitespace-sensitive, and a test whose fixture does
not look like a real fragment invites subtle mistakes.

Line numbers work out to the natural values — the `---` is line 1, and a
test can assert `body_line(offset) == 8` against what a reader counts.

## `write`

For anything not a fragment — a `promptc.yaml` override, a corpus file, a
monolith to split:

```python
write(os.path.join(project, "promptc.yaml"), """
    library: promptlib
    contracts: contracts
    vocabulary:
      "keep file": ["keepfile", "the keep"]
""")
```

Overwriting `promptc.yaml` mid-test is the standard way to test a config
variation without a second fixture.

## `build_index`

Parses the library and returns an `Index`, for tests that work below the
`run_check` level:

```python
def test_closure_places_dependencies_first(project, fragment_file, build_index):
    ...
    index = build_index()
    assert [item.id for item in index.closure(["top"])] == ["base", "middle", "top"]
```

Call it *after* writing fragments — it reads the library at call time, not
at fixture time, which is what lets a test write files and then build.

## `rules_in`

```python
assert "PC001" in rules_in(report)
assert "PC004" not in rules_in(report)
```

Returns sorted distinct rule ids. Almost every rule test uses it, because
the assertion "this rule fired" is the one that survives message rewording.

## Local fixtures

Where a fixture is specific to one module, define it in that test file
rather than `conftest.py`. `tests/evalharness/test_corpus.py` has
`corpus_project`; `tests/test_verify.py` has `verifier_project`;
`tests/evalharness/test_init.py` has `eval_project`. None of them belongs
to the shared surface.

A local fixture that a second file starts needing moves to `conftest.py` at
that point, not before.

## Adding one

Two questions: is it used by more than one test file, and does it build a
real artefact rather than a mock? Both yes means `conftest.py`. Otherwise
keep it local.

Give it a docstring — `conftest.py` follows the same
[docstring standard](../coding-standard/docstrings.md) as the package.
