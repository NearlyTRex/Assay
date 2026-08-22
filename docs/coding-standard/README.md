# Coding standard

Python 3.10+. No enforced formatter — these are conventions a reviewer
checks, not something a tool rewrites for you.

| | |
|---|---|
| [invariants.md](invariants.md) | The five architectural rules. **Read first** |
| [layout.md](layout.md) | Module structure, imports, section banners, where new code goes |
| [naming.md](naming.md) | Identifiers, rule ids, test names, abbreviations |
| [formatting.md](formatting.md) | Spacing, line length, dataclasses over dicts |
| [docstrings.md](docstrings.md) | Module and function docstrings, part by part |
| [error-handling.md](error-handling.md) | Catching narrowly, remedies, subprocesses, temp files |
| [diagnostics.md](diagnostics.md) | Findings, fix hints, message wording, `data` |
| [adding-a-rule.md](adding-a-rule.md) | The full checklist for a new rule |

## The short version

Write it the way the file around it is written. Where that is ambiguous:

- **No model judges anything.** Not in `check`, not anywhere.
- **Errors are facts, warnings are guesses.** A threshold never fails a build.
- **Deterministic output.** Same input, same bytes.
- **Degrade loudly.** A missing capability announces itself or fails.
- **Domain knowledge lives in `promptc.yaml`**, never in the package.
- **Every finding is a `Diagnostic`** with an id, a location and a fix hint.
- **Full words**, spaces around keyword `=`, under 100 columns.
- **Docstrings are Google style**, on every module and public definition.
