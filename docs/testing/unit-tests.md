# Unit tests

## The default

Unit tests are **unmarked**. Anything without a marker must be:

- in-process — no `subprocess`, no CLI invocation
- offline — no network, not even to localhost
- confined — no filesystem writes outside `tmp_path`

If a test cannot meet all three, it is an
[integration test](integration-tests.md) and needs a marker.

```bash
python3 -m pytest tests/ -q -m "not integration"
# 281 passed, 63 deselected in 0.60s
```

Under a second for the whole unit suite. That is the point: this is the
loop you run on every edit, and it stops being run the moment it stops
being instant.

## They still use the real filesystem

A unit test here is not a test with everything mocked. Every fixture builds
a real project on disk under `tmp_path`, because promptc is a pure function
of a source tree — mocking the filesystem would mean testing a different
program.

```python
def test_unresolved_require(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        requires: [ghost]
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC002" in rules_in(report)
```

That writes a real file, parses it with the real parser, and runs the real
check. It is a unit test because nothing leaves the process.

## Keeping them fast

Pass `examples = False` to `run_check` unless the test is specifically
about PC006. It skips every verifier subprocess, which is the only thing in
the check path that would otherwise cost milliseconds:

```python
report = run_check(load_config(), examples = False)
```

A rule test that forgets this still passes — it just quietly turns itself
into an integration test without a marker.

## What belongs here

Almost everything:

| Module | Unit coverage |
|---|---|
| `fragment.py` | Parsing, references, suppressions, library walking |
| `index.py` | Closure, cycles, routing, reachability |
| `assemble.py` | Ordering, determinism, manifests |
| `config.py` | Defaults, validation, every error path |
| `diagnostics.py` | Severity, sorting, exit codes, rendering |
| `tokens.py` | Estimation, failure modes |
| `split.py` | Slugging, section parsing, ref rewriting |
| `graph.py` | Coverage, rendering |
| `calibrate.py` | Statistics, threshold proposals, verdicts |
| `rules/` | Every rule, positive and negative |
| `evalharness/corpus.py` | Holdout determinism, stratification |
| `evalharness/report.py` | Aggregation, portability index |

The pure parts of `evalharness/runner.py` and `evalharness/score.py` —
backend construction, extraction, similarity — are unit tested too. Only
the parts that actually spawn something are marked.
