"""Heuristic rules: PC100-PC105.

These measure surface features that plausibly predict how well a smaller
open-weight model follows a prompt. None of them is validated on arrival.
Thresholds ship loose, every finding is a WARN, and `promptc calibrate` is
what decides whether a rule stays, tightens, or gets deleted.

Two habits keep them honest. Every check abstains when there is too little
text to measure, rather than reporting a density derived from one sentence.
And every message states the measurement alongside the threshold, so a
reader can tell a real finding from a miscalibrated rule without re-running
anything.
"""

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
    """Remove fenced and inline code from text.

    Prose metrics must not measure code samples: a recipe with a long
    example is not a badly written recipe, and `generally` inside backticks
    is a literal rather than a hedge.

    Args:
        text: Markdown text.

    Returns:
        str: The text with code replaced by spaces, preserving length
        roughly enough that density figures stay meaningful.
    """
    text = FENCE_PATTERN.sub(" ", text)
    text = INLINE_CODE_PATTERN.sub(" ", text)
    return text

SENTENCE_PATTERN = re.compile(r"[^.!?\n]+[.!?]?")

def sentences(text):
    """Split text into sentences.

    Deliberately crude -- newlines end a sentence, which suits list items
    and numbered steps better than a linguistic splitter would.

    Args:
        text: Text to split, ideally already passed through prose_only.

    Returns:
        list: Stripped sentences, with empties dropped.
    """
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
    """Find sentences that read as instructions.

    A sentence counts when it opens with a verb from IMPERATIVE_VERBS or
    contains a modal ("must", "never", "should"). Approximate by design:
    the figure feeds a warning threshold, not a decision.

    Args:
        text: Fragment body. Code is stripped internally.

    Returns:
        list: The matching sentences, in document order. List markers and
        step numbers are ignored when testing the opening word, so
        "1. Set the field." counts.
    """
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
    """Report fragments dense in hedging phrases (PC100).

    Hedges ask the reader to infer intent. Large models resolve them from
    context; smaller open-weight models tend to pick a reading at random,
    and the failure is silent because the output still looks confident.

    Args:
        config: Loaded Config, supplying the hedge list and threshold.
        fragments: Fragments to check.
        counter: Counter used to normalise hits per 1,000 tokens.

    Returns:
        list: PC100 diagnostics, WARN severity. Fragments under 100 tokens
        are skipped, since a density derived from one sentence is noise.
    """
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
    """Report fragments phrased mostly as prohibitions (PC101).

    Positive instructions transfer better than negative ones. "Never do X"
    leaves the space of acceptable actions undefined, and a model that
    complies still has to invent what to do instead.

    Args:
        config: Loaded Config, supplying the threshold.
        fragments: Fragments to check.

    Returns:
        list: PC101 diagnostics, WARN severity. Fragments with fewer than
        eight instructions are skipped, since the ratio is unstable there.
    """
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
    """Report fragments carrying too many separate instructions (PC102).

    Instruction-following degrades with count well before it degrades with
    length, and the instructions lost are usually the middle ones.

    Args:
        config: Loaded Config, supplying the threshold.
        fragments: Fragments to check.

    Returns:
        list: PC102 diagnostics, WARN severity.
    """
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
    """Report fragments with long or heavily subordinated sentences (PC103).

    Multi-clause conditionals are where small models drop a qualifier and
    apply a rule in a case it was scoped out of.

    Args:
        config: Loaded Config, supplying the threshold.
        fragments: Fragments to check.

    Returns:
        list: PC103 diagnostics, WARN severity. Empty when textstat is not
        installed -- the rule abstains rather than failing, since it is
        optional. Fragments under 400 characters are skipped.
    """
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
    """Report banned synonyms for a canonical term (PC104).

    Synonyms for a term of art force the model to decide whether two names
    mean the same thing. It sometimes decides they do not.

    Args:
        config: Loaded Config, supplying the canonical-to-synonyms map.
        fragments: Fragments to check.

    Returns:
        list: PC104 diagnostics, WARN severity, one per canonical term per
        fragment. Empty when no vocabulary is configured.
    """
    found = []
    if not config.vocabulary:
        return found

    for item in fragments:
        prose = item.prose()
        for canonical, synonyms in sorted(config.vocabulary.items()):

            # Blank out the canonical term first, keeping the text the same
            # length so offsets stay valid. Without this, a synonym that is
            # a substring of the canonical term ("the keep" inside "the keep
            # file") makes correct usage report itself.
            canonical_pattern = re.compile(
                r"(?<![\w-])" + re.escape(canonical) + r"(?![\w-])", re.I)
            text = canonical_pattern.sub(lambda m: " " * len(m.group(0)), prose)

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
def check_critical_position(config, assembly, counter):
    """Report hard constraints buried mid-assembly (PC105).

    Attention to the middle of a long context is measurably weaker than to
    either end, and hard constraints are exactly what you cannot afford to
    lose.

    Measured against a whole assembly rather than a fragment, because
    position only means anything once the prompt is built. The diagnostic
    therefore carries the pseudo-path `<assembly:task-id>` instead of a
    file, and is the only rule that does so.

    Args:
        config: Loaded Config, supplying the threshold.
        assembly: The built Assembly to measure.
        counter: Accepted for signature symmetry with the other checks;
            position is measured in characters, not tokens.

    Returns:
        list: At most one PC105 diagnostic, WARN severity. Assemblies under
        4,000 characters are skipped, having no meaningful middle.
    """
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
