# Integration tests

## The marker

```python
@pytest.mark.integration
def test_command_backend_returns_stdout():
    ...
```

Or, where every test in a file qualifies:

```python
pytestmark = pytest.mark.integration
```

Markers are declared in `pyproject.toml` and `--strict-markers` is on, so a
typo'd marker fails collection rather than silently doing nothing:

```toml
markers = [
    "integration: crosses a real process boundary (CLI, external verifier, model backend)",
    "slow: takes more than a second",
]
addopts = "--strict-markers"
```

## What earns one

Exactly three boundaries in this repository:

| Boundary | Where | Why it cannot be a unit test |
|---|---|---|
| **The CLI as a subprocess** | `tests/test_cli.py` | Exit codes and stream separation are the contract, and neither is observable in-process |
| **An external verifier** | `tests/test_verify.py` | The whole point is that a real program decides |
| **A model backend** | `tests/evalharness/` | Generation crosses a process boundary even when faked |

Nothing else. If a new test wants the marker for a fourth reason, that is
worth a conversation — it usually means logic has leaked into a place it
should not be.

## The CLI contract

`tests/test_cli.py` spawns the real CLI because three things matter and
none of them survive an in-process call:

**Exit codes.** `0` clean, `1` errors found, `2` bad invocation, `130`
interrupted. An agent's edit loop is `while ! promptc check; do ...; done`,
so these are load-bearing.

```python
def test_check_exits_nonzero_on_error(project, fragment_file):
    ...
    assert result.returncode == 1
```

**Stream separation.** Findings on stdout, tool faults on stderr. An agent
parses the former:

```python
def test_diagnostics_go_to_stdout_not_stderr(project, fragment_file):
    """Agents read findings from stdout; stderr is reserved for tool faults."""
    result = run_cli(project, "check", "--no-examples")
    assert "PC005" in result.stdout
    assert "PC005" not in result.stderr
```

**JSON parseability**, from the actual process, with real encoding:

```python
payload = json.loads(result.stdout)
assert payload["ok"] is True
```

Tests import via `PYTHONPATH`, so no install step is needed:

```python
env = dict(os.environ, PYTHONPATH = REPO_ROOT, NO_COLOR = "1")
```

`NO_COLOR` keeps ANSI escapes out of asserted output.

## Verifiers

`tests/test_verify.py` uses `grep` as a stand-in verifier — universally
available, and its exit code semantics are exactly what a real verifier's
are:

```yaml
verifiers:
  - id: must-say-ok
    match: text
    command: ["grep", "-q", "OK", "{file}"]
    timeout: 10
```

That covers the whole path: block extraction, verifier matching, temp file
handling, exit code interpretation, and PC006 emission. Two failure modes
get their own tests — a missing binary (exit 127) and a non-matching
language (skipped entirely).

## Running them

```bash
python3 -m pytest tests/ -q -m integration
# 63 passed, 281 deselected in 3.06s
```

Three seconds, dominated by process spawn. Run the whole suite before
pushing; run `-m "not integration"` while working.

## `slow`

Mark anything over a second. Nothing currently qualifies — the slowest
integration test is a one-second timeout check in
`tests/evalharness/test_runner.py`.
