# Heuristic rules: PC100-PC105.
#
# These measure surface features that plausibly predict how well a smaller
# open-weight model follows a prompt. None of them is validated on arrival.
# Thresholds ship loose, every finding is a WARN, and `promptc calibrate`
# is what decides whether a rule stays, tightens, or gets deleted.

# Imports
import re

# Local imports
from ..diagnostics import Diagnostic, Severity

###########################################################
# Text utilities
###########################################################
# Strip fenced code so prose metrics do not measure code samples.
FENCE_PATTERN = re.compile(r"```.*?```", re.S)
INLINE_CODE_PATTERN = re.compile(r"`[^`]*`")

def prose_only(text):
    text = FENCE_PATTERN.sub(" ", text)
    text = INLINE_CODE_PATTERN.sub(" ", text)
    return text

SENTENCE_PATTERN = re.compile(r"[^.!?\n]+[.!?]?")

def sentences(text):
    return [s.strip() for s in SENTENCE_PATTERN.findall(text) if s.strip()]

# Verbs that open an instruction in this kind of document.
IMPERATIVE_VERBS = {
    "add", "apply", "avoid", "build", "call", "cast", "change", "check",
    "compare", "compile", "confirm", "convert", "copy", "create", "declare",
    "define", "delete", "do", "emit", "ensure", "extract", "find", "fix",
    "follow", "generate", "give", "ignore", "include", "inline", "insert",
    "keep", "leave", "list", "look", "make", "mark", "match", "merge", "move",
    "name", "note", "omit", "open", "prefer", "preserve", "read", "record",
    "reduce", "remove", "rename", "repeat", "replace", "report", "require",
    "resolve", "return", "rewrite", "run", "set", "skip", "sort", "split",
    "start", "stop", "store", "treat", "trim", "update", "use", "verify",
    "write", "never", "always",
}

MODAL_PATTERN = re.compile(r"\b(must|must not|never|always|shall|should|do not|don't)\b", re.I)
NEGATIVE_PATTERN = re.compile(r"\b(must not|never|do not|don't|avoid|refrain|without)\b", re.I)

def imperatives(text):
    found = []
    for sentence in sentences(prose_only(text)):
        stripped = sentence.lstrip("-*0123456789. \t")
        if not stripped:
            continue
        first = re.split(r"[^A-Za-z']+", stripped, maxsplit = 1)[0].lower()
        if first in IMPERATIVE_VERBS or MODAL_PATTERN.search(sentence):
            found.append(sentence)
    return found

###########################################################
# PC100 -- hedge density
###########################################################
def check_hedges(config, fragments, counter):
    found = []
    threshold = config.threshold("PC100")
    if threshold is None:
        return found

    patterns = [(hedge, re.compile(r"(?<![\w-])" + re.escape(hedge) + r"(?![\w-])", re.I))
                for hedge in config.hedges]

    for item in fragments:
        text = prose_only(item.prose())
        tokens = counter.count(text)
        if tokens < 100:
            continue

        hits = []
        for hedge, pattern in patterns:
            for match in pattern.finditer(text):
                hits.append((hedge, match.start()))
        if not hits:
            continue

        density = len(hits) / (tokens / 1000.0)
        if density <= threshold:
            continue

        distinct = sorted({hedge for hedge, _ in hits})
        found.append(Diagnostic(
            rule = "PC100", severity = Severity.WARN,
            message = (f"Hedge density {density:.1f}/1k tok, threshold {threshold:.1f} "
                       f"({len(hits)} hits in {tokens:,} tok).\n"
                       f"Most frequent: {', '.join(repr(h) for h in distinct[:6])}."),
            file = item.path, line = 1,
            fix_hint = "replace each hedge with an explicit condition and a definite action.",
            data = {"density": round(density, 2), "threshold": threshold, "hits": len(hits)},
        ))
    return found

###########################################################
# PC101 -- negation density
###########################################################
def check_negations(config, fragments):
    found = []
    threshold = config.threshold("PC101")
    if threshold is None:
        return found

    for item in fragments:
        statements = imperatives(item.prose())
        if len(statements) < 8:
            continue
        negative = [s for s in statements if NEGATIVE_PATTERN.search(s)]
        ratio = len(negative) / len(statements)
        if ratio <= threshold:
            continue
        found.append(Diagnostic(
            rule = "PC101", severity = Severity.WARN,
            message = (f"{len(negative)} of {len(statements)} instructions are "
                       f"prohibitions ({ratio:.0%}, threshold {threshold:.0%})."),
            file = item.path, line = 1,
            fix_hint = "for each prohibition, state the action to take instead.",
            data = {"ratio": round(ratio, 3), "threshold": threshold,
                    "negative": len(negative), "total": len(statements)},
        ))
    return found

###########################################################
# PC102 -- instruction count
###########################################################
def check_instruction_count(config, fragments):
    found = []
    threshold = config.threshold("PC102")
    if threshold is None:
        return found

    for item in fragments:
        statements = imperatives(item.prose())
        if len(statements) <= threshold:
            continue
        found.append(Diagnostic(
            rule = "PC102", severity = Severity.WARN,
            message = (f"{len(statements)} separate instructions in one fragment "
                       f"(threshold {threshold})."),
            file = item.path, line = 1,
            fix_hint = "split into narrower fragments, each routed by its own trigger.",
            data = {"count": len(statements), "threshold": threshold},
        ))
    return found

###########################################################
# PC103 -- sentence complexity
###########################################################
def check_complexity(config, fragments):
    found = []
    threshold = config.threshold("PC103")
    if threshold is None:
        return found

    try:
        import textstat
    except ImportError:
        return found

    for item in fragments:
        text = prose_only(item.prose()).strip()
        if len(text) < 400:
            continue
        try:
            grade = textstat.flesch_kincaid_grade(text)
        except Exception:
            continue
        if grade <= threshold:
            continue

        longest = max(sentences(text), key = len, default = "")
        found.append(Diagnostic(
            rule = "PC103", severity = Severity.WARN,
            message = (f"Flesch-Kincaid grade {grade:.1f}, threshold {threshold:.1f}.\n"
                       f"Longest sentence is {len(longest.split())} words."),
            file = item.path, line = 1,
            fix_hint = "break multi-clause conditionals into numbered steps, one action each.",
            data = {"grade": round(grade, 1), "threshold": threshold},
        ))
    return found

###########################################################
# PC104 -- vocabulary drift
###########################################################
def check_vocabulary(config, fragments):
    found = []
    if not config.vocabulary:
        return found

    for item in fragments:
        text = item.prose()
        for canonical, synonyms in sorted(config.vocabulary.items()):
            for synonym in synonyms:
                pattern = re.compile(r"(?<![\w-])" + re.escape(synonym) + r"(?![\w-])", re.I)
                match = pattern.search(text)
                if match is None:
                    continue
                found.append(Diagnostic(
                    rule = "PC104", severity = Severity.WARN,
                    message = f"Uses \"{synonym}\" where the canonical term is \"{canonical}\".",
                    file = item.path, line = item.body_line(match.start()),
                    fix_hint = f"replace with \"{canonical}\".",
                    data = {"canonical": canonical, "found": synonym},
                ))
    return found

###########################################################
# PC105 -- critical rules buried
###########################################################
# Measured against a whole assembly rather than a fragment, because
# position only means anything once the prompt is built.
def check_critical_position(config, assembly, counter):
    found = []
    threshold = config.threshold("PC105")
    if threshold is None or not assembly.text:
        return found

    total = len(assembly.text)
    if total < 4000:
        return found

    buried = []
    for match in re.finditer(r"\b(MUST NOT|MUST|NEVER|ALWAYS)\b", assembly.text):
        position = match.start() / total
        if 0.25 < position < 0.75:
            buried.append((match.group(0), position))

    hard_rules = len(re.findall(r"\b(MUST NOT|MUST|NEVER|ALWAYS)\b", assembly.text))
    if not hard_rules:
        return found

    ratio = len(buried) / hard_rules
    if ratio <= threshold:
        return found

    found.append(Diagnostic(
        rule = "PC105", severity = Severity.WARN,
        message = (f"{len(buried)} of {hard_rules} hard constraints sit in the middle "
                   f"half of the assembly ({ratio:.0%}, threshold {threshold:.0%})."),
        file = f"<assembly:{assembly.task}>", line = 0,
        fix_hint = "move hard constraints into a fragment that sorts to the front or back.",
        data = {"ratio": round(ratio, 3), "threshold": threshold,
                "buried": len(buried), "total": hard_rules},
    ))
    return found
