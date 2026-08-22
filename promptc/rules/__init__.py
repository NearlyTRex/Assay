# Check orchestration.
#
# `run_check` is the gate. It is a pure function of the source tree plus,
# when examples are enabled, the exit codes of the verifier commands the
# project configured. Nothing here consults a model.

# Imports
import os

# Local imports
from .. import assemble as assemble_module
from .. import fragment as fragment_module
from .. import index as index_module
from .. import tokens as tokens_module
from ..diagnostics import Diagnostic, Report, Severity
from . import base, heuristic, structural

###########################################################
# Tokenizer resolution
###########################################################
# A missing tokenizer degrades to estimation, loudly. Silently estimating
# would make PC004 meaningless while still appearing to pass.
def resolve_counter(profile, report):
    spec = profile.tokenizer if profile else "chars"
    try:
        return tokens_module.counter(spec)
    except tokens_module.TokenizerUnavailable as error:
        report.add(Diagnostic(
            rule = "PC014", severity = Severity.WARN,
            message = f"{error.reason}\nFalling back to character estimation; PC004 is approximate.",
            file = "promptc.yaml", line = 0,
            fix_hint = error.fix_hint,
            data = {"spec": error.spec},
        ))
        return tokens_module.counter("chars")

###########################################################
# Check
###########################################################
def run_check(config, profile_name = None, examples = True, tasks = None,
              honour_suppressions = True, triggers = None):
    report = Report()

    # --- parse ------------------------------------------------------
    fragments, parse_errors = fragment_module.load_library(config.library_path())
    report.extend(parse_errors)

    if not fragments:
        if not os.path.isdir(config.library_path()):
            report.add(Diagnostic(
                rule = "PC000", severity = Severity.ERROR,
                message = f"Library directory `{config.library}` does not exist.",
                file = "promptc.yaml", line = 0,
                fix_hint = "create it, or point `library:` at the right directory.",
            ))
        return report

    index = index_module.Index(fragments)

    # --- identity, cycles, routing ----------------------------------
    report.extend(index_module.index_diagnostics(index))

    # --- structure --------------------------------------------------
    report.extend(structural.check_references(index, fragments))
    report.extend(structural.check_requires(index, fragments))
    report.extend(structural.check_contracts(config, fragments))
    report.extend(structural.check_glossary(index, fragments))
    report.extend(structural.check_orphans(index))

    # --- suppressions ------------------------------------------------
    suppressions = []
    for item in fragments:
        suppressions.extend(item.suppressions())
    report.extend(structural.check_suppression_justifications(suppressions))

    # --- profile and token budget -----------------------------------
    profile = None
    if profile_name:
        profile = config.profile(profile_name)
        if profile is None:
            known = ", ".join(sorted(config.profiles)) or "none defined"
            report.add(Diagnostic(
                rule = "PC000", severity = Severity.ERROR,
                message = f"Unknown profile `{profile_name}`. Known profiles: {known}.",
                file = "promptc.yaml", line = 0,
                fix_hint = "add it under `profiles:` in promptc.yaml.",
            ))

    counter = resolve_counter(profile, report)

    # --- heuristics (per fragment) ----------------------------------
    report.extend(heuristic.check_hedges(config, fragments, counter))
    report.extend(heuristic.check_negations(config, fragments))
    report.extend(heuristic.check_instruction_count(config, fragments))
    report.extend(heuristic.check_complexity(config, fragments))
    report.extend(heuristic.check_vocabulary(config, fragments))

    # --- per-task assembly checks -----------------------------------
    if profile is not None:
        selected = index.tasks()
        if tasks:
            selected = [task for task in selected if task.id in set(tasks)]

        for task in selected:
            assembly = assemble_module.assemble(index, task.id, triggers or ())
            report.extend(structural.check_budget(assembly, profile, counter))
            report.extend(heuristic.check_critical_position(config, assembly, counter))

    # --- examples ----------------------------------------------------
    if examples:
        example_diagnostics, _ = verify_examples(config, fragments)
        report.extend(example_diagnostics)

    # --- suppression bookkeeping -------------------------------------
    if honour_suppressions:
        report.apply_suppressions(suppressions)
        report.extend(structural.check_unused_suppressions(suppressions))
    else:
        report.suppressions = suppressions

    return report

# Imported lazily so `promptc check --no-examples` never needs subprocess
def verify_examples(config, fragments):
    from .. import verify
    return verify.check_examples(config, fragments)
