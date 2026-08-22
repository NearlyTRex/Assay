# Naming

## Full words

`fragment`, not `frag`. `verifier`, not `vfy`. `resolution`, not `res`.
`diagnostic`, not `diag`.

The one place abbreviations are allowed is where they match an external
name already in play — `gbnf`, `cwd`, `argv`, `json`, `yaml`.

This matters more than usual here because the domain vocabulary *is* the
product: PC104 exists to enforce consistent terminology in prompts, and a
tool that abbreviates inconsistently in its own source has no standing.

## Conventions

| Thing | Style | Example |
|---|---|---|
| Modules, functions, variables | `lower_snake_case` | `check_budget` |
| Classes, dataclasses | `CapWords` | `ItemResult` |
| Module-level constants | `UPPER_SNAKE_CASE` | `DEFAULT_THRESHOLDS` |
| Internal helpers | `_leading_underscore` | `_parse_profiles` |
| Rule ids | `PC` + three digits | `PC001` |
| Test functions | `test_<what it asserts>` | `test_orphan_detection` |

## Rule ids

`PC0xx` — decidable structural rules.
`PC1xx` — measured heuristics.

The band is meaningful, not cosmetic: `tests/rules/test_base.py` asserts
that no `PC1xx` rule is an `ERROR` and that only `PC1xx` rules carry
`calibrated = True`. Allocate the next free number in the right band; never
renumber an existing rule, because ids appear in suppression comments in
user repositories.

## Builtins

Do not shadow them. `id` is the one exception, and only as a dataclass
field where it reads as the domain term:

```python
@dataclasses.dataclass
class Fragment:
    id: str          # fine -- this is the fragment's id
```

Never as a local variable.

## Test names

The name states what is asserted, not what is exercised. A reader scanning
`pytest -v` output should learn the behaviour without opening the file.

```python
def test_suppression_is_scoped_to_its_file():        # good
def test_apply_suppressions():                       # says nothing
def test_the_golden_answer_never_reaches_the_prompt(): # good -- names the invariant
```

Long names are fine. They are read far more often than typed.
