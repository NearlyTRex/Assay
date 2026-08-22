---
id: {{id}}
kind: recipe
title: {{title}}
triggers: []          # detector names that route to this recipe
requires: []          # fragment ids this one references or depends on
provides: []          # terms of art this fragment defines
budget: 800           # token ceiling for this fragment
---

State the condition that makes this recipe apply, in one sentence.

## Steps

1. First action. One action per step, no conditionals inside a step.
2. Second action.
3. Third action.

## Example

Before — the shape you will encounter. Marked `promptc:noverify` because it
is not expected to be valid:

```c promptc:noverify
/* the broken form */
```

After — the shape to produce. This block IS verified, so it must build:

```c
/* the corrected form */
```
