# Testing against models

## The hard rule

**No test in this repository may contact a real model.**

A suite whose result depends on a model's mood is not a suite. It fails
intermittently, it cannot run offline, it cannot run in CI, and when it
does fail nobody can tell whether the code broke or the weights changed.

This is not a preference. It follows directly from the invariant that
[no model judges anything](../coding-standard/invariants.md#1-no-model-judges-anything):
if the tool never trusts a model's opinion, neither may its tests.

## What to do instead

`CommandBackend` exists partly as a production escape hatch and partly so
the harness can be driven by a deterministic stand-in. A "model" is a
script that prints a fixed answer:

```python
ALWAYS_OK = "import sys; sys.stdin.read(); print('```'); print('OK'); print('```')"
```

Wired into a profile:

```yaml
profiles:
  fake:
    context: 32768
    tokenizer: chars
    backend: command
    command: ["/usr/bin/python3", "-c", "<the script>"]
```

That covers the entire harness — corpus discovery, trigger routing, prompt
assembly, payload rendering, extraction, verification, scoring, retries,
aggregation — because the only thing being faked is the token generator.
Everything downstream of "some text came back" is real.

## Varying behaviour deterministically

Where behaviour must differ between attempts, vary it on the **seed**,
which `CommandBackend` substitutes into the argv:

```python
SEED_DEPENDENT = (
    "import sys; sys.stdin.read();"
    "seed = {seed};"
    "print('```');"
    "print('OK' if seed % 2 else 'nope');"
    "print('```')"
)
```

With `seeds: [1000, 1001, 1002]`, attempt one fails and attempt two passes.
That tests retry logic — `pass@1` versus `pass@k`, and stopping at the
first success — with no nondeterminism at all:

```python
assert result.pass_rate() == 1.0
assert result.pass_at_1() == 0.0
assert result.items[0].attempts_to_green() == 2
```

## Failure modes get stand-ins too

Each taxonomy bucket has a script that produces it:

| Stand-in | Produces | Bucket |
|---|---|---|
| Prints a fenced `OK` | A passing answer | `pass` |
| Prints prose, no fence | Nothing extractable | `no_answer` |
| Prints nothing | Empty output | `empty` |
| Prints a fenced wrong answer | Verifier rejection | `verifier_failed:<id>` |
| Exits non-zero | Infrastructure failure | `backend_error` |

Because these are real subprocesses, the classification path is exercised
exactly as it would be in production.

## The test that matters most

```python
@pytest.mark.integration
def test_the_golden_answer_never_reaches_the_prompt(eval_project, project):
    """If the model could see the golden file the whole measurement is void."""
    captured = os.path.join(project, "captured.txt")
    script = (f"import sys; open({captured!r}, 'w').write(sys.stdin.read());"
              "print('```'); print('OK'); print('```')")
    config = eval_project(model_script = script, items = ("alpha",))

    evalharness.run_eval(config, "fake", split = "dev")

    with open(captured, encoding = "utf-8") as handle:
        prompt = handle.read()
    assert "input alpha" in prompt
    assert "golden alpha" not in prompt
```

The stand-in writes the prompt it received to disk so the test can inspect
it. If the golden answer ever leaked into the prompt, every pass rate the
tool has ever reported would be meaningless — and nothing else in the suite
would notice.

This is the shape to copy for any invariant whose violation is silent:
capture the artefact, assert on it directly.

## HTTP backends

`LlamaCppBackend` and `OpenAIBackend` are tested only for **failing cleanly
against a dead port**:

```python
def test_llamacpp_unreachable_returns_an_error_not_an_exception():
    backend = runner.LlamaCppBackend("http://127.0.0.1:1")
    generation = backend.generate("prompt", runner.Sampling(), timeout = 2)
    assert not generation.ok
    assert "llamacpp" in generation.error
```

Note these are *unit* tests — connecting to a closed port on localhost is
not a process boundary and returns immediately.

Testing them properly needs a live server. That belongs in someone's CI
against a real `llama-server`, not in this suite.
