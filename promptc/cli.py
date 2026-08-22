"""Command line interface.

Ergonomics here are aimed at an agent as the primary caller: every command
takes --format json, every diagnostic carries a fix hint, exit codes are
meaningful, and nothing waits on a TTY.

This module holds no logic beyond argument marshalling and dispatch, which
is what lets the test suite exercise everything else in-process and reserve
subprocess tests for the CLI contract itself.

Two conventions are load-bearing, both with tests pinning them: findings go
to stdout while tool faults go to stderr, and the exit code is 0 for clean,
1 for errors found, 2 for a bad invocation, 130 for an interrupt. Every
`command_*` function returns a code rather than calling sys.exit.
"""

# Imports
import argparse
import json
import os
import sys

# Local imports
from . import assemble as assemble_module
from . import calibrate as calibrate_module
from . import config as config_module
from . import fragment as fragment_module
from . import graph as graph_module
from . import index as index_module
from . import split as split_module
from . import tokens as tokens_module
from .rules import base as rules_base
from .rules import run_check

VERSION = "0.1.0"

###########################################################
# Helpers
###########################################################
def fail(message, code = 2):
    """Report a tool fault on stderr and return an exit code.

    Findings never go through here -- they are diagnostics on stdout. This
    is for the tool itself being unable to proceed.

    Args:
        message: What went wrong, and ideally what to do about it.
        code: Exit code. Defaults to 2, meaning a bad invocation.

    Returns:
        int: The code, for the caller to return.
    """
    print(message, file = sys.stderr)
    return code

def load(args):
    """Load the project config named by --config, or found upward."""
    return config_module.load_config(getattr(args, "config", None))

def build_index(config):
    """Parse the library and build an Index.

    Returns:
        tuple: (index, parse_errors). Parse errors are returned rather than
        raised so each command can decide whether they are fatal for it.
    """
    fragments, parse_errors = fragment_module.load_library(config.library_path())
    return index_module.Index(fragments), parse_errors

def parse_triggers(value):
    """Split a comma-separated --triggers value into names.

    Args:
        value: The raw option, or None.

    Returns:
        list: Stripped names, with empties dropped so a trailing comma is
        harmless.
    """
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]

def counter_for(config, profile_name):
    """Build a token counter for a profile, falling back silently.

    Unlike run_check, this raises no PC014: the commands using it are
    reporting token costs rather than deciding whether a budget is met, so
    an estimate is acceptable and the counter's own label says as much.

    Args:
        config: Loaded Config.
        profile_name: Profile name, or None for character estimation.

    Returns:
        Counter.
    """
    profile = config.profile(profile_name) if profile_name else None
    spec = profile.tokenizer if profile else "chars"
    try:
        return tokens_module.counter(spec)
    except tokens_module.TokenizerUnavailable:
        return tokens_module.counter("chars")

###########################################################
# init
###########################################################
TEMPLATE_CONFIG = """# promptc project configuration.
#
# This file is the entire domain boundary. promptc knows how to run a command
# you give it and read an exit code; everything it knows about your language,
# toolchain or project arrives through here.

library: promptlib
contracts: contracts

# Commands that decide whether an example block is valid. {file} is replaced
# with a temp file holding the extracted block.
verifiers:
  - id: example-builds
    match: cpp
    command: ["./verify.sh", "{file}"]
    timeout: 120

# Target models. `context` and `tokenizer` make PC004 meaningful.
profiles:
  local:
    context: 32768
    tokenizer: chars        # chars | tiktoken:<enc> | hf:<name> | llamacpp:<url>
    reserve: 9000           # tokens held back for the runtime work item
    endpoint: http://127.0.0.1:8080
    backend: llamacpp

# What `promptc eval` runs and how it is scored.
eval:
  task: ""                  # id of the task fragment to assemble
  verifiers: []             # verifier ids run against model output
  extract: fence
  suffix: .txt
  attempts: 1
  baseline_profile: ""      # denominator of the portability index

# The labelled corpus. Golden files are never shown to the model.
corpus:
  root: .
  discover: ""              # e.g. "**/*.expected.txt"
  golden_suffix: ""         # e.g. ".expected.txt"
  inputs: []                # e.g. ["{stem}.cpp", "{stem}.asm"]
  triggers_command: []      # argv emitting one trigger name per line
  stratify_by: triggers
  holdout: 0.2
  seed: 20260822

# Canonical term -> names that must not be used for it (drives PC104).
vocabulary: {}
"""

def command_init(args):
    """Create promptc.yaml and the library layout.

    The result passes its own `check`, so a fresh project starts green.

    Returns:
        int: 0, or 2 if a config already exists and --force was not given.
    """
    target = os.path.join(os.path.abspath(args.directory), "promptc.yaml")
    if os.path.exists(target) and not args.force:
        return fail(f"{target} already exists. Pass --force to overwrite.")

    os.makedirs(os.path.dirname(target), exist_ok = True)
    with open(target, "w", encoding = "utf-8") as handle:
        handle.write(TEMPLATE_CONFIG)

    library = os.path.join(os.path.dirname(target), "promptlib")
    contracts = os.path.join(os.path.dirname(target), "contracts")
    os.makedirs(library, exist_ok = True)
    os.makedirs(contracts, exist_ok = True)

    print(f"created {target}")
    print(f"created {library}/")
    print(f"created {contracts}/")
    print("\nNext: `promptc new task <id>` to create an entry point.")
    return 0

###########################################################
# new
###########################################################
def template_path(kind):
    """Return the path to a fragment template for this kind."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "templates", f"{kind}.md")

def command_new(args):
    """Scaffold a fragment that is structurally valid on creation.

    An agent starting from this cannot produce a fragment that fails to
    parse, which removes an entire class of first-iteration failure.

    Returns:
        int: 0 and the created path on stdout, or 2 on an unknown kind or
        an existing file without --force.
    """
    config = load(args)
    if args.kind not in fragment_module.KINDS:
        return fail(f"Unknown kind `{args.kind}`. One of: {', '.join(fragment_module.KINDS)}")

    path = template_path(args.kind)
    if not os.path.exists(path):
        path = template_path("recipe")
    with open(path, "r", encoding = "utf-8") as handle:
        body = handle.read()

    title = args.title or args.id.replace("-", " ").capitalize()
    body = body.replace("{{id}}", args.id).replace("{{title}}", title)

    target = os.path.join(config.library_path(), args.subdir or "", f"{args.id}.md")
    if os.path.exists(target) and not args.force:
        return fail(f"{target} already exists. Pass --force to overwrite.")

    os.makedirs(os.path.dirname(target), exist_ok = True)
    with open(target, "w", encoding = "utf-8") as handle:
        handle.write(body)

    print(target)
    return 0

###########################################################
# build
###########################################################
def command_build(args):
    """Assemble a task into a prompt.

    With --explain, prints the token cost of each fragment worst-first
    instead of the prompt itself -- which is how you find what to cut when
    PC004 fires.

    Returns:
        int: 0, or 1 if the library failed to parse, or 2 for an unknown
        task. Unresolved fragments are a warning on stderr, not a failure:
        the partial prompt is still worth seeing.
    """
    config = load(args)
    index, parse_errors = build_index(config)
    if parse_errors:
        for diagnostic in parse_errors:
            print(f"{diagnostic.file}:{diagnostic.line}: {diagnostic.message}", file = sys.stderr)
        return 1

    if index.get(args.task) is None:
        known = ", ".join(sorted(task.id for task in index.tasks())) or "none"
        return fail(f"Unknown task `{args.task}`. Known tasks: {known}")

    assembly = assemble_module.assemble(index, args.task, parse_triggers(args.triggers))
    counter = counter_for(config, args.profile)

    if assembly.missing:
        for missing in assembly.missing:
            print(f"warning: unresolved fragment `{missing}`", file = sys.stderr)

    if args.manifest:
        with open(args.manifest, "w", encoding = "utf-8") as handle:
            handle.write(assembly.manifest_json(counter))

    if args.explain:
        rows = [(counter.count(item.body), item) for item in assembly.fragments]
        total = counter.count(assembly.text)
        width = max((len(item.id) for _, item in rows), default = 4)
        for size, item in sorted(rows, reverse = True, key = lambda row: row[0]):
            share = size / total if total else 0
            print(f"  {item.kind:<9} {item.id:<{width}}  {size:>7,} tok  {share:>5.1%}")
        print(f"\n  total {total:,} tok ({counter.describe()})")
        if args.profile:
            profile = config.profile(args.profile)
            if profile:
                print(f"  budget {profile.budget():,} tok for profile `{profile.name}`")
        return 0

    if args.out:
        with open(args.out, "w", encoding = "utf-8") as handle:
            handle.write(assembly.text)
        print(args.out)
    else:
        sys.stdout.write(assembly.text)
    return 0

###########################################################
# check
###########################################################
def command_check(args):
    """Run the gate and report findings.

    The loop an authoring agent sits in. Findings go to stdout in either
    format, so the exit code is what signals failure rather than the
    presence of output.

    Returns:
        int: 1 when any error was found, else 0. Warnings never fail.
    """
    config = load(args)
    report = run_check(
        config,
        profile_name = args.profile,
        examples = not args.no_examples,
        tasks = args.task,
        honour_suppressions = not args.no_suppress,
        triggers = parse_triggers(args.triggers),
    )

    if args.format == "json":
        print(report.render_json())
    else:
        print(report.render_text())
    return report.exit_code()

###########################################################
# verify-examples
###########################################################
def command_verify_examples(args):
    """Run external verifiers over example blocks, on their own.

    `check` does this too; the standalone command exists for iterating on
    one fragment's examples via --fragment without re-running everything.

    Returns:
        int: 1 if any block failed, 0 otherwise, or 2 when no verifiers are
        configured -- an empty run would otherwise look like a pass.
    """
    from . import verify

    config = load(args)
    fragments, parse_errors = fragment_module.load_library(config.library_path())
    if parse_errors:
        for diagnostic in parse_errors:
            print(f"{diagnostic.file}:{diagnostic.line}: {diagnostic.message}", file = sys.stderr)
        return 1

    if not config.verifiers:
        return fail("No verifiers configured. Add a `verifiers:` block to promptc.yaml.")

    diagnostics, results = verify.check_examples(config, fragments, args.fragment)

    if args.format == "json":
        print(json.dumps({
            "checked": len(results),
            "failed": sum(1 for result in results if not result.ok),
            "diagnostics": [d.to_dict() for d in diagnostics],
        }, indent = 2))
    else:
        passed = sum(1 for result in results if result.ok)
        for diagnostic in diagnostics:
            print(f"{diagnostic.file}:{diagnostic.line}: {diagnostic.message}")
        print(f"\n{passed}/{len(results)} example blocks verified")
    return 1 if diagnostics else 0

###########################################################
# split
###########################################################
def command_split(args):
    """Propose a fragment split of a monolithic prompt.

    Dry run by default, because splitting overwrites by slug. Unresolved
    section references are listed explicitly, since each becomes a PC001
    error until rewritten.

    Returns:
        int: 0. Split reports rather than fails -- the resulting library is
        expected to have work outstanding, and `check` is what grades it.
    """
    config = load(args)
    out_dir = args.out or os.path.join(config.library_path(), "split")

    plan = split_module.split_file(
        args.file, out_dir, level = args.level,
        kind_for_leaf = args.kind, dry_run = not args.apply)

    if args.format == "json":
        print(json.dumps({
            "fragments": [
                {"path": path, "id": section.slug, "kind": section.kind,
                 "title": section.title, "legacy_section": section.number,
                 "chars": len(content)}
                for path, content, section in plan.fragments
            ],
            "number_map": {str(k): v for k, v in plan.number_map.items()},
            "unresolved_refs": [
                {"fragment": fragment, "ref": ref} for fragment, ref in plan.unresolved_refs
            ],
            "applied": bool(args.apply),
        }, indent = 2))
        return 0

    print(f"{len(plan.fragments)} fragment(s) from {args.file}")
    print(f"{len(plan.number_map)} numbered section(s) mapped for reference rewriting\n")

    for path, content, section in plan.fragments:
        marker = "" if args.apply else "[dry-run] "
        print(f"  {marker}{section.kind:<9} {section.slug:<44} {len(content):>7,} B")

    if plan.unresolved_refs:
        print(f"\n{len(plan.unresolved_refs)} unresolved section reference(s) — "
              f"these become PC001 errors until rewritten:")
        for fragment, ref in plan.unresolved_refs[:20]:
            print(f"  {fragment}: {ref}")
        if len(plan.unresolved_refs) > 20:
            print(f"  ... and {len(plan.unresolved_refs) - 20} more")

    if not args.apply:
        print("\nNothing written. Re-run with --apply.")
    return 0

###########################################################
# graph
###########################################################
def command_graph(args):
    """Report dependency and routing coverage.

    Returns:
        int: 0. Parse errors are a warning here rather than a failure --
        a partial graph still answers "what routes to what".
    """
    config = load(args)
    index, parse_errors = build_index(config)
    if parse_errors and args.format != "json":
        print(f"warning: {len(parse_errors)} fragment(s) failed to parse", file = sys.stderr)

    if args.format == "json":
        print(graph_module.render_json(index))
    elif args.format == "dot":
        print(graph_module.render_dot(index))
    else:
        print(graph_module.render_text(index, show_orphans_only = args.orphans))
    return 0

###########################################################
# explain
###########################################################
def command_explain(args):
    """Print a rule's rationale and remedy, or list every rule.

    Exists so an agent that hit a diagnostic never needs the documentation
    in its context to act on it.

    Returns:
        int: 0, or 2 for an unknown rule id.
    """
    if not args.rule:
        rules = rules_base.all_rules()
        if args.format == "json":
            print(json.dumps([{
                "id": rule.id, "name": rule.name,
                "severity": rule.severity.value, "summary": rule.summary,
                "calibrated": rule.calibrated,
            } for rule in rules], indent = 2))
            return 0
        for rule in rules:
            marker = " (threshold uncalibrated)" if rule.calibrated else ""
            print(f"{rule.id}  {rule.severity.value:<5}  {rule.name}{marker}")
            print(f"        {rule.summary}")
        return 0

    rule = rules_base.get(args.rule)
    if rule is None:
        return fail(f"Unknown rule `{args.rule}`. Run `promptc explain` to list all.")

    if args.format == "json":
        print(json.dumps({
            "id": rule.id, "name": rule.name, "severity": rule.severity.value,
            "summary": rule.summary, "rationale": rule.rationale,
            "remedy": rule.remedy, "calibrated": rule.calibrated,
        }, indent = 2))
        return 0

    print(f"{rule.id}  {rule.name}  [{rule.severity.value}]")
    print(f"\n{rule.summary}")
    print(f"\nWhy\n  {rule.rationale}")
    print(f"\nFix\n  {rule.remedy}")
    if rule.calibrated:
        print("\nNote\n  This threshold is a placeholder until `promptc calibrate`")
        print("  measures whether the feature predicts pass rate on your corpus.")
    return 0

###########################################################
# eval
###########################################################
def command_eval(args):
    """Measure prompts against the corpus by running a model.

    One run per --profile, so a single invocation can produce a portability
    index. Progress goes to stderr, leaving stdout clean for the report.

    Returns:
        int: 0, or 2 if any profile's run could not start. A low pass rate
        is a finding, not a failure -- that is what the report is for.
    """
    from . import evalharness
    from .evalharness import report as report_module

    config = load(args)
    profiles = args.profile or []
    if not profiles:
        return fail("Pass at least one --profile.")

    def progress(position, total, item_result):
        if args.format == "json" or args.quiet:
            return
        mark = "pass" if item_result.passed() else item_result.outcome()
        print(f"  [{position:>4}/{total}] {item_result.stem[:56]:<56} {mark}",
              file = sys.stderr)

    runs = []
    for profile_name in profiles:
        try:
            run = evalharness.run_eval(
                config, profile_name, limit = args.limit,
                per_group = args.per_group, split = args.split,
                attempts = args.attempts, progress = progress)
        except (evalharness.EvalError, Exception) as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            return fail(f"eval failed for profile `{profile_name}`: {error}")
        runs.append(run)

    baseline = args.baseline or config.eval.baseline_profile

    if args.format == "json":
        output = report_module.render_json(runs, baseline, include_items = args.items)
    else:
        output = report_module.render_text(runs, baseline)

    if args.out:
        with open(args.out, "w", encoding = "utf-8") as handle:
            handle.write(report_module.render_json(runs, baseline, include_items = True))
        if args.format != "json":
            print(output)
            print(f"\nfull results written to {args.out}")
            return 0

    print(output)
    return 0

###########################################################
# calibrate
###########################################################
def command_calibrate(args):
    """Test whether heuristic rules predict measured pass rate.

    Accepts several result files, merging their scorecards, so evidence
    accumulates across runs rather than each being judged alone.

    Returns:
        int: 0, or 2 when the given files contain no runs.
    """
    config = load(args)
    index, _ = build_index(config)
    counter = counter_for(config, args.profile)

    merged = {"runs": []}
    for path in args.results:
        with open(path, "r", encoding = "utf-8") as handle:
            payload = json.load(handle)
        merged["runs"].extend(payload.get("runs", []))

    if not merged["runs"]:
        return fail("No runs found in the given result files.")

    findings = calibrate_module.calibrate(config, index, counter, merged)

    if args.format == "json":
        print(calibrate_module.render_json(findings))
    else:
        print(calibrate_module.render_text(findings))
    return 0

###########################################################
# Parser
###########################################################
def build_parser():
    """Build the argument parser for every command.

    Returns:
        argparse.ArgumentParser: With a required subcommand, so invoking
        promptc bare is an error rather than a silent no-op.
    """
    parser = argparse.ArgumentParser(
        prog = "promptc",
        description = "A compiler for prompts: assemble fragments, validate them "
                      "against decidable rules, and measure them with external verifiers.")
    parser.add_argument("--version", action = "version", version = f"promptc {VERSION}")
    parser.add_argument("--config", help = "path to promptc.yaml (default: search upward)")

    subparsers = parser.add_subparsers(dest = "command", required = True)

    # init
    sub = subparsers.add_parser("init", help = "create promptc.yaml and the library layout")
    sub.add_argument("directory", nargs = "?", default = ".")
    sub.add_argument("--force", action = "store_true")
    sub.set_defaults(func = command_init)

    # new
    sub = subparsers.add_parser("new", help = "scaffold a fragment that is valid on creation")
    sub.add_argument("kind", choices = list(fragment_module.KINDS))
    sub.add_argument("id")
    sub.add_argument("--title")
    sub.add_argument("--subdir", help = "subdirectory within the library")
    sub.add_argument("--force", action = "store_true")
    sub.set_defaults(func = command_new)

    # build
    sub = subparsers.add_parser("build", help = "assemble a task into a prompt")
    sub.add_argument("task")
    sub.add_argument("--triggers", help = "comma-separated trigger names to route")
    sub.add_argument("--profile")
    sub.add_argument("--out", help = "write the prompt here instead of stdout")
    sub.add_argument("--manifest", help = "write the assembly manifest here")
    sub.add_argument("--explain", action = "store_true",
                     help = "print the token cost of each fragment instead of the prompt")
    sub.set_defaults(func = command_build)

    # check
    sub = subparsers.add_parser("check", help = "validate the library (the gate)")
    sub.add_argument("--profile", help = "target model profile, required for PC004")
    sub.add_argument("--task", action = "append", help = "limit assembly checks to this task")
    sub.add_argument("--triggers", help = "comma-separated triggers to route while checking")
    sub.add_argument("--no-examples", action = "store_true",
                     help = "skip PC006; no subprocesses are run")
    sub.add_argument("--no-suppress", action = "store_true",
                     help = "report findings even where a suppression exists")
    sub.add_argument("--format", choices = ["text", "json"], default = "text")
    sub.set_defaults(func = command_check)

    # verify-examples
    sub = subparsers.add_parser("verify-examples",
                                help = "run external verifiers over example blocks")
    sub.add_argument("--fragment", help = "limit to one fragment id")
    sub.add_argument("--format", choices = ["text", "json"], default = "text")
    sub.set_defaults(func = command_verify_examples)

    # split
    sub = subparsers.add_parser("split", help = "propose a fragment split of a monolithic prompt")
    sub.add_argument("file")
    sub.add_argument("--out", help = "output directory (default: <library>/split)")
    sub.add_argument("--level", type = int, default = 3,
                     help = "heading level that becomes a leaf fragment (default 3)")
    sub.add_argument("--kind", default = "recipe", choices = list(fragment_module.KINDS))
    sub.add_argument("--apply", action = "store_true", help = "write files (default: dry run)")
    sub.add_argument("--format", choices = ["text", "json"], default = "text")
    sub.set_defaults(func = command_split)

    # graph
    sub = subparsers.add_parser("graph", help = "dependency and routing coverage")
    sub.add_argument("--orphans", action = "store_true", help = "list unreachable fragments only")
    sub.add_argument("--format", choices = ["text", "json", "dot"], default = "text")
    sub.set_defaults(func = command_graph)

    # explain
    sub = subparsers.add_parser("explain", help = "what a rule means and how to fix it")
    sub.add_argument("rule", nargs = "?")
    sub.add_argument("--format", choices = ["text", "json"], default = "text")
    sub.set_defaults(func = command_explain)

    # eval
    sub = subparsers.add_parser("eval", help = "measure a prompt against a corpus (runs a model)")
    sub.add_argument("--profile", action = "append", help = "repeatable; one run per profile")
    sub.add_argument("--split", choices = ["dev", "test", "all"], default = "dev")
    sub.add_argument("--limit", type = int, default = 0)
    sub.add_argument("--per-group", type = int, default = 0,
                     help = "sample at most N items per stratum")
    sub.add_argument("--attempts", type = int, default = 0, help = "override eval.attempts")
    sub.add_argument("--baseline", help = "profile used as the portability denominator")
    sub.add_argument("--items", action = "store_true", help = "include per-item rows in JSON")
    sub.add_argument("--out", help = "write full JSON results here")
    sub.add_argument("--quiet", action = "store_true")
    sub.add_argument("--format", choices = ["text", "json"], default = "text")
    sub.set_defaults(func = command_eval)

    # calibrate
    sub = subparsers.add_parser("calibrate",
                                help = "test whether heuristic rules predict pass rate")
    sub.add_argument("results", nargs = "+", help = "eval result JSON files")
    sub.add_argument("--profile", help = "profile whose tokenizer is used for features")
    sub.add_argument("--format", choices = ["text", "json"], default = "text")
    sub.set_defaults(func = command_calibrate)

    return parser

###########################################################
# Entry point
###########################################################
def main(argv = None):
    """Parse arguments and dispatch to a command.

    ConfigError is caught here so a YAML typo prints a remedy rather than a
    traceback -- it is a user error, not a crash.

    Args:
        argv: Argument list. None reads sys.argv.

    Returns:
        int: Exit code. 130 on interrupt, matching shell convention.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except config_module.ConfigError as error:
        return fail(str(error))
    except KeyboardInterrupt:
        return 130

if __name__ == "__main__":
    sys.exit(main())
