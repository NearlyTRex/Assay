"""promptc -- a compiler for prompts.

Assemble modular prompt fragments, validate them against decidable rules,
and measure them against a corpus scored by external verifiers.

A model writes the prompt source; an external program decides whether it is
valid -- the same relationship a compiler has with code. `promptc check` is
the gate an authoring agent loops against.

Two guarantees are kept deliberately apart. `check` claims a prompt is
well-formed: fast, deterministic, no model involved. `eval` claims a prompt
works on a given model: statistical, and scored entirely by verifier exit
codes. No model judges anything, anywhere.
"""

__version__ = "0.1.0"
