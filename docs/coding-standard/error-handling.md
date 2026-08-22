# Error handling

## Catch narrowly

Name the exceptions you expect:

```python
try:
    body = _post_json(self.url, payload, timeout)
except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
    return Generation("", ok = False, error = f"llamacpp: {error}")
```

`except Exception` is acceptable only at a boundary where the alternative
is aborting a batch — parsing one bad fragment out of sixty, or a verifier
subprocess misbehaving in a way you cannot enumerate. Where it is used, it
must produce a diagnostic rather than a silent skip:

```python
try:
    fragments.append(parse_fragment(path, root))
except ParseError as error:
    errors.append(error.to_diagnostic())
```

One bad file reports and the other fifty-nine still get checked. A bare
`continue` there would hide the fault entirely.

## Exceptions carry a remedy

Anything that can reach a user states what to do about it:

```python
raise ConfigError(
    f"{path}: verifier `{entry['id']}` needs `command` as a non-empty list "
    f"(argv form, e.g. [\"./build.sh\", \"{{file}}\"]).")
```

Three things in that message: which file, what is wrong, and what correct
looks like. The example is what makes it actionable — a user who has just
written a string instead of a list needs to see the list.

The same applies to `TokenizerUnavailable`, which carries an explicit
`fix_hint` attribute so the caller can put it in a diagnostic.

## Config errors are not crashes

A typo in `promptc.yaml` or in `--config` is a user error and must surface
as a `ConfigError`, which `cli.main` catches and prints without a
traceback:

```python
# An explicit --config that does not exist is a user typo, not a crash
if not os.path.exists(path):
    raise ConfigError(
        f"Config file not found: {path}\n"
        f"Check the path, or run `promptc init` to create one.")
```

Validate at parse time where you can. A profile whose reserves exceed its
context is caught in `_parse_profiles` rather than producing a negative
budget that makes PC004 blame the prompt for a configuration fault.

## Subprocesses

Every subprocess call gets three things:

```python
try:
    completed = subprocess.run(
        command, cwd = cwd, capture_output = True, text = True,
        timeout = verifier.timeout)
    output = (completed.stdout or "") + (completed.stderr or "")
    returncode = completed.returncode
except subprocess.TimeoutExpired:
    output = f"verifier timed out after {verifier.timeout}s"
    returncode = 124
except FileNotFoundError as error:
    output = f"verifier command not found: {error}"
    returncode = 127
```

1. **A timeout.** A hung verifier must not hang the run.
2. **`FileNotFoundError` handled.** A missing binary is a configuration
   error, not a stack trace.
3. **A synthetic exit code** so the caller has one code path. 124 for
   timeout and 127 for not-found match shell convention.

## Temp files

Always removed in a `finally`, and the removal itself is guarded:

```python
handle = tempfile.NamedTemporaryFile(
    mode = "w", suffix = suffix, delete = False, encoding = "utf-8")
try:
    handle.write(block.code)
    handle.close()
    ...
finally:
    try:
        os.unlink(handle.name)
    except OSError:
        pass
```

`delete = False` plus explicit close is needed because the verifier is a
separate process that must be able to open the path.

## What never happens

- **Silent fallback.** See [invariants.md](invariants.md#4-degrade-loudly).
- **`print` for an error.** Findings are `Diagnostic` objects; tool faults
  go to stderr via `cli.fail`.
- **Swallowing without a trace.** If an exception is deliberately ignored,
  a comment says why.
