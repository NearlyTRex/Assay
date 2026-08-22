"""Structural rules: PC001-PC013.

Everything in this module is decidable from the source tree plus, for
PC006, the exit code of a program you configured. No model is consulted and
no threshold is guessed.

Each check takes what it needs and returns a list of Diagnostic. None of
them raises, prints, or short-circuits on the first fault -- a check run
must be able to report everything wrong at once.
"""

# Imports
import os
import re

# Local imports
from ..diagnostics import Diagnostic, Severity

###########################################################
# PC001 -- dangling references
###########################################################
def check_references(index, fragments):
    """Report references that cannot resolve (PC001).

    Two distinct faults share this id. An explicit `{{ref:id}}` naming a
    fragment not in `requires` is absent from any assembly that does not
    happen to route it. A prose reference -- "see above", a section number
    -- can never resolve, because fragments assemble in different
    combinations per task.

    Args:
        index: Built Index, used to tell an unknown id from an undeclared
            one so the message can say which.
        fragments: Fragments to check.

    Returns:
        list: PC001 diagnostics, ERROR severity.
    """
    found = []
    for item in fragments:
        available = set(item.requires)

        for target, line in item.explicit_refs():
            if target in available:
                continue
            if index.get(target) is None:
                message = f"Reference to `{target}` names no known fragment."
                hint = "check the id, or create it with `promptc new`."
            else:
                message = (f"Reference to `{target}` is not declared in `requires`, "
                           f"so it is absent from assemblies that do not route it.")
                hint = f"add `{target}` to this fragment's `requires`."
            found.append(Diagnostic(
                rule = "PC001", severity = Severity.ERROR,
                message = message, file = item.path, line = line,
                fix_hint = hint, data = {"target": target},
            ))

        for text, label, line in item.prose_refs():
            found.append(Diagnostic(
                rule = "PC001", severity = Severity.ERROR,
                message = f"Unresolvable {label}: \"{text}\".",
                file = item.path, line = line,
                fix_hint = ("fragments assemble in different combinations, so positional "
                            "references cannot resolve; use `{{ref:id}}` or inline the fact."),
                data = {"text": text, "kind": label},
            ))
    return found

###########################################################
# PC002 -- unresolved requires
###########################################################
def check_requires(index, fragments):
    """Report `requires` entries naming no known fragment (PC002).

    Args:
        index: Built Index.
        fragments: Fragments to check.

    Returns:
        list: PC002 diagnostics, ERROR severity.
    """
    found = []
    for item in fragments:
        for required in item.requires:
            if index.get(required) is None:
                found.append(Diagnostic(
                    rule = "PC002", severity = Severity.ERROR,
                    message = f"`requires` names unknown fragment `{required}`.",
                    file = item.path, line = 1,
                    fix_hint = f"correct the id, or run `promptc new recipe {required}`.",
                    data = {"missing": required},
                ))
    return found

###########################################################
# PC005 / PC013 -- output contracts
###########################################################
from .base import CATALOGUE  # noqa: E402  (kept local to avoid a cycle at import time)
from ..fragment import CONTRACT_REQUIRED_KINDS  # noqa: E402

def check_contracts(config, fragments):
    """Report missing or unresolvable output contracts (PC005, PC013).

    A task without a contract cannot fail closed, so malformed output
    reaches the pipeline and has to be caught later by something else. A
    contract path that does not exist is worse: the prompt only appears to
    fail closed.

    Args:
        config: Loaded Config, for resolving contract paths against root.
        fragments: Fragments to check.

    Returns:
        list: PC005 for a task with no contract, PC013 for a declared
        contract whose file is absent. Both ERROR severity.
    """
    found = []
    for item in fragments:
        if not item.contract:
            if item.kind in CONTRACT_REQUIRED_KINDS:
                found.append(Diagnostic(
                    rule = "PC005", severity = Severity.ERROR,
                    message = f"Task `{item.id}` declares no output contract.",
                    file = item.path, line = 1,
                    fix_hint = "add `contract: contracts/<name>.gbnf` so generation can fail closed.",
                ))
            continue

        path = item.contract
        if not os.path.isabs(path):
            candidate = os.path.join(config.root, path)
        else:
            candidate = path

        if not os.path.exists(candidate):
            found.append(Diagnostic(
                rule = "PC013", severity = Severity.ERROR,
                message = f"Contract file `{item.contract}` does not exist.",
                file = item.path, line = 1,
                fix_hint = f"create {item.contract}, or correct the path.",
                data = {"contract": item.contract},
            ))
    return found

###########################################################
# PC007 -- glossary terms
###########################################################
# Only terms that some fragment actually declares via `provides` are
# checked. A term used by a fragment that cannot see its provider is an
# error; a word nobody declared is simply not a term of art.
def check_glossary(index, fragments):
    """Report terms of art used without their definition in scope (PC007).

    Only terms some fragment actually declares via `provides` are checked.
    A word nobody declared is not a term of art and is left alone -- which
    is what keeps this rule from firing on ordinary prose.

    Args:
        index: Built Index, supplying the term-to-provider map.
        fragments: Fragments to check.

    Returns:
        list: PC007 diagnostics, ERROR severity. Empty when the library
        declares no terms at all.
    """
    found = []
    if not index.providers:
        return found

    for item in fragments:
        visible = set()
        for dependency in index.closure([item.id]):
            visible.update(term.lower() for term in dependency.provides)

        prose = item.prose().lower()
        for term, providers in sorted(index.providers.items()):
            if term in visible:
                continue
            if item.id in providers:
                continue
            pattern = r"(?<![\w-])" + re.escape(term) + r"(?![\w-])"
            match = re.search(pattern, prose)
            if match is None:
                continue
            line = item.body_line(match.start())
            found.append(Diagnostic(
                rule = "PC007", severity = Severity.ERROR,
                message = (f"Uses term \"{term}\", defined in "
                           f"`{providers[0]}`, which this fragment does not require."),
                file = item.path, line = line,
                fix_hint = f"add `{providers[0]}` to `requires`.",
                data = {"term": term, "provider": providers[0]},
            ))
    return found

###########################################################
# PC010 -- orphans
###########################################################
def check_orphans(index):
    """Report fragments no task or trigger can reach (PC010).

    A warning rather than an error: an orphan is usually dead weight, but
    it is sometimes a routing rule someone forgot to add, and failing the
    build on that would be wrong.

    Args:
        index: Built Index.

    Returns:
        list: PC010 diagnostics, WARN severity.
    """
    found = []
    for item in index.orphans():
        found.append(Diagnostic(
            rule = "PC010", severity = Severity.WARN,
            message = f"Fragment `{item.id}` is unreachable from any task.",
            file = item.path, line = 1,
            fix_hint = "add a `triggers:` entry, reference it from a task's `requires`, or delete it.",
            data = {"id": item.id},
        ))
    return found

###########################################################
# PC011 / PC012 -- suppressions
###########################################################
def check_suppression_justifications(suppressions):
    """Report suppressions with no usable reason (PC011).

    A gate an agent loops against is a gate an agent learns to satisfy
    cheaply, and a bare `promptc-disable` is the cheapest possible way.
    Requiring a written reason keeps every silenced rule reviewable.

    Args:
        suppressions: Suppression objects gathered from every fragment.

    Returns:
        list: PC011 diagnostics, ERROR severity, for justifications under
        twelve characters.
    """
    found = []
    for suppression in suppressions:
        if len(suppression.justification) < 12:
            found.append(Diagnostic(
                rule = "PC011", severity = Severity.ERROR,
                message = f"Suppression of {suppression.rule} gives no usable reason.",
                file = suppression.file, line = suppression.line,
                fix_hint = ("write `<!-- promptc-disable "
                            f"{suppression.rule}: why, and what evidence -->`."),
                data = {"rule": suppression.rule},
            ))
    return found

def check_unused_suppressions(suppressions):
    """Report suppressions that matched nothing (PC012).

    Call after Report.apply_suppressions, which sets `used`.

    Args:
        suppressions: Suppression objects, already applied to a report.

    Returns:
        list: PC012 diagnostics, WARN severity.
    """
    found = []
    for suppression in suppressions:
        if suppression.used:
            continue
        found.append(Diagnostic(
            rule = "PC012", severity = Severity.WARN,
            message = f"Suppression of {suppression.rule} matches no diagnostic.",
            file = suppression.file, line = suppression.line,
            fix_hint = "delete it; the underlying finding is gone.",
            data = {"rule": suppression.rule},
        ))
    return found

###########################################################
# PC004 -- token budget
###########################################################
def check_budget(assembly, profile, counter):
    """Report assemblies and fragments over their token budget (PC004).

    The per-fragment breakdown matters more than the total: knowing you are
    4,000 tokens over is useless without knowing which three fragments to
    cut, so the message names the three largest.

    Args:
        assembly: Assembly to measure.
        profile: Target Profile, supplying context size and reserves.
        counter: Counter for the profile's tokenizer. May be an estimate,
            in which case PC014 will already have been raised.

    Returns:
        list: One ERROR when the whole assembly exceeds the profile budget,
        plus one WARN per fragment over its own declared `budget`.
    """
    found = []
    total = counter.count(assembly.text)
    budget = profile.budget()

    if total > budget:
        over = total - budget
        heaviest = sorted(
            ((counter.count(item.body), item) for item in assembly.fragments),
            reverse = True, key = lambda entry: entry[0])[:3]
        breakdown = ", ".join(f"`{item.id}` {size:,}" for size, item in heaviest)
        found.append(Diagnostic(
            rule = "PC004", severity = Severity.ERROR,
            message = (
                f"Assembled prompt is {total:,} tok; budget is {budget:,} "
                f"(context {profile.context:,} − payload {profile.reserve:,} "
                f"− output {profile.output_reserve:,}). Over by {over:,}.\n"
                f"Largest fragments: {breakdown}."),
            file = assembly.fragments[-1].path if assembly.fragments else "",
            line = 1,
            fix_hint = "route fewer fragments, split the largest, or raise the profile's context.",
            data = {
                "tokens": total, "budget": budget, "over": over,
                "tokenizer": counter.describe(), "profile": profile.name,
            },
        ))

    for item in assembly.fragments:
        if not item.budget:
            continue
        size = counter.count(item.body)
        if size > item.budget:
            found.append(Diagnostic(
                rule = "PC004", severity = Severity.WARN,
                message = (f"Fragment `{item.id}` is {size:,} tok, over its "
                           f"declared budget of {item.budget:,}."),
                file = item.path, line = 1,
                fix_hint = "trim the fragment, or raise its `budget:`.",
                data = {"id": item.id, "tokens": size, "budget": item.budget},
            ))
    return found
