# Configuration

`promptc.yaml` is the entire domain boundary. promptc knows how to run a
command you gave it and read an exit code; everything it knows about your
language or toolchain arrives here. See
[invariant 5](../coding-standard/invariants.md#5-the-domain-boundary-is-promptcyaml).

It is found by walking upward from the working directory, or named with
`--config`.

## Full reference

```yaml
library: promptlib          # where fragments live
contracts: contracts        # where grammars and schemas live

# Commands that decide whether an example block is valid.
# {file} becomes a temp file holding the extracted block.
verifiers:
  - id: compiles
    match: c                # compared against the fence info string
    command: ["scripts/compile.sh", "{file}"]
    timeout: 120
    suffix: .c              # optional; defaults from the fence language

# Target models. `context` and `tokenizer` make PC004 meaningful.
profiles:
  qwen-7b:
    context: 32768
    tokenizer: hf:Qwen/Qwen2.5-Coder-7B
    reserve: 9000           # held back for the runtime work item
    output_reserve: 2048    # held back for the model's own output
    endpoint: http://127.0.0.1:8080
    backend: llamacpp       # llamacpp | openai | command
  reference:
    context: 200000
    tokenizer: tiktoken:cl100k_base
    backend: command
    command: ["./scripts/ask-reference-model.sh"]

eval:
  task: fix-source
  verifiers: [compiles, lint-clean]   # run in order; first failure wins
  extract: fence            # fence | raw
  suffix: .c
  attempts: 5               # pass@k
  seeds: [1000, 1001, 1002, 1003, 1004]
  temperature: 0.2
  max_tokens: 4096
  baseline_profile: reference   # denominator of the portability index
  payload_header: "\n\n## Work item\n\n"

corpus:
  root: corpus
  discover: "**/*.expected.c"    # glob finding golden files
  golden_suffix: ".expected.c"   # stripped to get the item stem
  inputs: ["{stem}.c", "{stem}.meta.json"]
  triggers_command: ["scripts/detect.sh", "{stem}"]
  stratify_by: triggers
  holdout: 0.2
  seed: 20260822

# Canonical term -> names that must not be used for it (PC104)
vocabulary:
  "work item": ["workitem", "the item", "task file"]

# Phrases counted by PC100. Omit to use the built-in list.
hedges: ["generally", "prefer", "where appropriate", "use judgement"]

# Calibrated thresholds. Every one is a placeholder until measured.
thresholds:
  PC100: 6.0
  PC102: 30
```

## Verifiers

`command` must be **argv form** — a list, not a shell string. `{file}` is
replaced with a temp file holding the extracted block.

```yaml
command: ["./build.sh", "{file}"]     # correct
command: "./build.sh {file}"          # rejected at parse time
```

`match` is compared against the fence info string. Both `cpp` and
```` ```cpp ```` forms are accepted. An empty `match` matches every block.

`suffix` sets the temp file extension. Defaults to the fence language, so
a ```` ```cpp ```` block becomes `.cpp` without configuration.

## Profiles

| Field | Default | Purpose |
|---|---|---|
| `context` | 32768 | Total window |
| `tokenizer` | `chars` | How PC004 measures |
| `reserve` | 0 | Held back for the runtime work item |
| `output_reserve` | 2048 | Held back for generation |
| `endpoint` | — | For `llamacpp` and `openai` backends |
| `model` | — | For `openai` |
| `backend` | inferred | `llamacpp`, `openai`, or `command` |
| `command` | — | Argv for the `command` backend |

The budget PC004 checks is `context − reserve − output_reserve`. A
non-positive result is rejected at parse time, because it would make every
prompt "exceed" the budget and the diagnostic would blame the prompt for a
configuration fault:

```
profile `tiny` leaves no room for a prompt — context 1,000 minus reserve 0
minus output_reserve 2,048 is -1,048.
```

### Tokenizer specs

| Spec | Exact? | Needs |
|---|---|---|
| `chars` | no — reports itself as an estimate | nothing |
| `tiktoken:cl100k_base` | yes | `tiktoken` |
| `hf:Qwen/Qwen2.5-Coder-7B` | yes | `tokenizers` |
| `llamacpp:http://127.0.0.1:8080` | yes | a running `llama-server` |

`hf:` accepts a model name or a path to a local `tokenizer.json`.

An unavailable tokenizer falls back to `chars` and raises PC014. It never
falls back silently: a budget measured against the wrong tokenizer appears
to pass while proving nothing.

## Corpus

`discover` is a recursive glob finding **golden** files — the known-good
answers. Each match defines one work item. `golden_suffix` is stripped from
the path to get the item stem, and `inputs` templates the files actually
shown to the model.

```yaml
discover: "**/*.expected.c"
golden_suffix: ".expected.c"
inputs: ["{stem}.c", "{stem}.meta.json"]
```

Given `widgets/resize.expected.c`, the stem is `widgets/resize` and the
model sees `widgets/resize.c` and `widgets/resize.meta.json`. **The golden
file is never shown** — there is a test pinning that.

An input path that does not exist is skipped rather than failing the item,
so a corpus where only some entries carry an optional file still works.

`triggers_command` is argv emitting one trigger name per line on stdout.
`{stem}`, `{golden}` and `{input}` are substituted. A non-zero exit means
"no triggers", not a failure — a detector that legitimately finds nothing
must not abort the run.

`holdout` and `seed` control the dev/test split, which is deterministic by
hash of `(seed, stem)`. See [eval.md](eval.md#the-holdout).

## Vocabulary

```yaml
vocabulary:
  "work item": ["workitem", "the item"]
```

The key is canonical; the list is banned synonyms. A synonym that is a
substring of its canonical term is handled correctly — *"the work item"*
does not trip the `"the item"` rule.

## Thresholds

Overrides for `PC100`–`PC105`. Every built-in default is a placeholder
until `promptc calibrate` measures it against real pass rates, and
deliberately loose so an uncalibrated install does not drown an author in
noise.
