# Architectural invariants

These are not style. A change that breaks one changes what the tool is, and
should be argued for on those terms rather than slipped in.

## 1. No model judges anything

`check`, `build`, `split` and `graph` are pure functions of the source
tree. `verify-examples` runs a command you configured and reads an exit
code. `eval` runs a model, but the model is the subject and your verifier
is the judge. `calibrate` correlates lint features against measured pass
rate.

If a feature seems to need a model's opinion, the answer is a better
external verifier. There is no LLM-as-judge anywhere in this codebase and
adding one is a change to the premise.

## 2. Errors are decidable; warnings are heuristics

An `ERROR` rule must be provable from the source tree or from a program's
exit code. Given the same inputs it always reaches the same verdict, and
that verdict can be defended without appeal to taste.

A heuristic gets `WARN`, ships with a loose placeholder threshold, and
never fails a build until `calibrate` has measured that the feature
predicts pass rate. Marking a heuristic `ERROR` is how a linter becomes
something people disable.

Enforced by `tests/rules/test_base.py`, which fails if any `PC1xx` rule is
an `ERROR`.

## 3. Assembly is deterministic

Same tree, same task, same triggers produces byte-identical output.

Never sort by anything unstable, never let filesystem order reach the
result, never stamp a time into an artefact. This is why `Index.route`
sorts its result rather than preserving trigger order: triggers arrive from
a detector subprocess whose output order is not guaranteed, and the prompt
must depend on the *set* of triggers, not the order they were printed in.

Without this, a `pass@k` figure cannot be compared to the previous one.

## 4. Degrade loudly

A missing optional dependency must announce itself.

`tokens.py` is the reference implementation: an unavailable tokenizer
raises `TokenizerUnavailable` carrying a fix hint, the caller emits PC014,
and the run continues on character estimation. Silently estimating would
leave PC004 appearing to pass while measuring the wrong thing — the worst
possible outcome, because it looks like success.

The rule generalises: when a capability is missing, say so at the point of
loss and continue in a clearly-labelled reduced mode, or fail. Never
substitute quietly.

## 5. The domain boundary is `promptc.yaml`

Nothing in `promptc/` may know about a specific language, toolchain or
project.

If you are about to write a file extension, a compiler name, or a tool
invocation into the package, it belongs in config. The toolset knows how to
run a command you gave it and read an exit code; that is the entire
contract, and it is what lets the same rules serve a C project and a Python
one without changing a line.

## Checking yourself

Before merging, three questions:

1. Does anything new consult a model for a judgement?
2. Does any new `ERROR` rest on a threshold rather than a fact?
3. Does the package now know something about a specific language or
   toolchain?

Three noes means the invariants hold.
