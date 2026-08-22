# Installing

## Requirements

Python 3.10+ and `PyYAML`. Everything else is optional and
[degrades loudly](../coding-standard/invariants.md#4-degrade-loudly) rather
than silently.

| Package | Extra | Needed for |
|---|---|---|
| `PyYAML` | — | Frontmatter and config. **Required** |
| `tiktoken` | `tokenizers` | Exact token budgets, OpenAI encodings |
| `tokenizers` | `tokenizers` | Exact token budgets, HuggingFace models |
| `textstat` | `prose` | Sentence complexity (PC103) |
| `jsonschema` | `schema` | JSON Schema output contracts |
| `pytest` | `dev` | The test suite |

## Installing

```bash
pip install -e ".[all]"          # or ".[dev]" for just the test deps
promptc --version
```

Individual extras:

```bash
pip install -e ".[tokenizers]"   # exact PC004
pip install -e ".[prose]"        # PC103
```

## Without installing

The module runs in place:

```bash
PYTHONPATH=/path/to/assay python3 -m promptc check
```

The test suite does the same via a `sys.path` insert in `conftest.py`, so
no install step is needed to run it.

## Optional external tools

Neither is required; promptc works without both.

**A local model server.** `promptc eval` can drive
[llama.cpp](https://github.com/ggml-org/llama.cpp), any OpenAI-compatible
endpoint, or an arbitrary command. llama.cpp is worth preferring for local
work because it exposes three things promptc uses and lighter wrappers
often do not:

- **Grammar-constrained sampling**, so an output contract makes malformed
  output unrepresentable rather than merely discouraged.
- **Fixed seeds**, so `pass@k` is reproducible run to run.
- **A `/tokenize` endpoint**, so PC004 measures with the target model's own
  tokenizer instead of an estimate.

**A prose linter.** [Vale](https://vale.sh) covers style rules beyond what
PC104 checks. Configure it separately; promptc does not invoke it.

## Verifying

```bash
promptc --version
promptc explain            # lists every rule
python3 -m pytest tests/ -q
```
