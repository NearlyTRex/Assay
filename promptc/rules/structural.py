# Structural rules: PC001-PC013.
#
# Everything in this module is decidable from the source tree plus, for
# PC006, the exit code of a program you configured. No model is consulted
# and no threshold is guessed.

# Imports
import os
import re

# Local imports
from ..diagnostics import Diagnostic, Severity

###########################################################
# PC001 -- dangling references
###########################################################
def check_references(index, fragments):
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
