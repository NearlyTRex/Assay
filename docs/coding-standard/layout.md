# File layout

## Module structure

Every module opens the same way: a module docstring, then imports grouped
under comment headers.

```python
"""Fragment parsing.

A fragment is a markdown file with YAML frontmatter. The frontmatter is
what makes the structural checks decidable.
"""

# Imports
import dataclasses
import os
import re

# Third party
import yaml

# Local imports
from . import diagnostics
from .diagnostics import Diagnostic, Severity
```

Standard library first, then third party, then local, each alphabetical
within its group. `# Third party` is omitted when there is none.

Prefer `from . import module` over importing names directly, except where a
name is used constantly — `Diagnostic` and `Severity` earn the direct
import; nothing else currently does.

## Section banners

Sections within a module are separated by banner comments:

```python
###########################################################
# Fence extraction
###########################################################
```

Exactly 59 hashes, matching the existing files.

Group by concept, not by visibility — do not collect "all the private
helpers" into one band. A banner is worth adding when a file grows past
roughly two screens, or when a reader would otherwise have to scan to find
where one idea ends and the next begins.

Test files repeat the source file's banners, in the same order, so the two
read side by side.

## Package structure

```
promptc/
  cli.py              argparse surface; no logic beyond dispatch
  config.py           promptc.yaml -- the entire domain boundary
  fragment.py         parsing a single fragment
  index.py            identity, dependency closure, routing
  assemble.py         fragments -> a prompt
  tokens.py           token counting
  verify.py           running external verifiers over example blocks
  split.py            monolith -> fragment skeletons
  graph.py            dependency and coverage reporting
  calibrate.py        turning guessed thresholds into measured ones
  diagnostics.py      Diagnostic, Report, rendering
  rules/
    base.py           the rule catalogue -- ids, rationale, remedy
    structural.py     decidable rules, PC001-PC013
    heuristic.py      measured rules, PC100-PC105
    __init__.py       run_check orchestration
  evalharness/
    corpus.py         discovery, stratification, holdout
    runner.py         model backends
    score.py          extraction, verification, taxonomy
    report.py         aggregation and rendering
    __init__.py       run_eval orchestration
```

`cli.py` holds no logic. If a command needs more than argument marshalling
and a call, the logic belongs in a module and the CLI calls it. This is
what lets the test suite exercise everything in-process and reserve
subprocess tests for the CLI contract itself.

## Where new code goes

| Adding | Goes in |
|---|---|
| A decidable rule | `rules/structural.py` + a catalogue entry |
| A measured rule | `rules/heuristic.py` + a catalogue entry + a feature extractor |
| A model backend | `evalharness/runner.py` |
| A new output format | The module that owns the data, as `render_<format>` |
| Anything domain-specific | `promptc.yaml`, not the package |
