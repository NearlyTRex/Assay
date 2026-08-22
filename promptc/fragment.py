"""Fragment parsing.

A fragment is a markdown file with YAML frontmatter. The frontmatter is
what makes the structural checks decidable -- `requires` bounds what a
fragment may reference, `provides` builds the glossary, `triggers` gives
mechanical routing with no model judgement involved.

Parsing never aborts a run. A malformed fragment raises ParseError, which
load_library converts to a PC000 diagnostic so the other fifty-nine files
still get checked.
"""

# Imports
import dataclasses
import os
import re

# Third party
import yaml

# Local imports
from . import diagnostics

###########################################################
# Kinds
###########################################################
KINDS = ("task", "rule", "recipe", "workflow", "example", "glossary")

# Kinds that must declare an output contract -- these are the ones that can
# be the entry point of a generation, so they must be able to fail closed.
CONTRACT_REQUIRED_KINDS = ("task",)

###########################################################
# Reference syntax
###########################################################
# Explicit, checkable cross-reference.
REF_PATTERN = re.compile(r"\{\{\s*ref:\s*([A-Za-z0-9_-]+)\s*\}\}")

# Prose references that cannot be resolved once fragments are assembled in
# arbitrary order. These are always errors -- there is no way to check them,
# which is exactly why they must not exist.
PROSE_REF_PATTERNS = [
    (re.compile(r"§\s*\d+"), "section-number reference"),
    (re.compile(r"\bas (?:described|mentioned|noted|shown) above\b", re.I), "backward prose reference"),
    (re.compile(r"\b(?:see|per) (?:the )?(?:section |chapter )?above\b", re.I), "backward prose reference"),
    (re.compile(r"\bthe (?:previous|preceding|foregoing) section\b", re.I), "backward prose reference"),
    (re.compile(r"\b(?:the )?(?:section|list|table) below\b", re.I), "forward prose reference"),
    (re.compile(r"\bearlier in this (?:document|prompt|file)\b", re.I), "backward prose reference"),
]

###########################################################
# Suppression syntax
###########################################################
# <!-- promptc-disable PC100: justification text -->
SUPPRESS_PATTERN = re.compile(
    r"<!--\s*promptc-disable\s+(?P<rule>[A-Z]{2}\d{3})\s*(?::\s*(?P<why>.*?))?\s*-->",
    re.S,
)

###########################################################
# Fragment
###########################################################
@dataclasses.dataclass
class Fragment:
    """One parsed fragment: its metadata and its body.

    Attributes:
        id: Unique addressing name, used by `requires` and `{{ref:}}`.
        kind: One of KINDS. Sets assembly order, and whether a contract is
            required.
        path: Project-relative path, used verbatim in diagnostics so
            findings are stable across machines.
        body: Everything after the closing frontmatter marker, unmodified.
            Includes any suppression comments -- use prose() to exclude
            them from text measurement.
        body_start: 1-indexed file line where the body begins. Needed
            because every offset within `body` must be reported as a
            location in the *file*.
        title: Heading text used when assembled. Falls back to `id`.
        triggers: Detector names routing to this fragment.
        requires: Fragment ids this one depends on. Bounds what it may
            reference; resolved transitively at assembly.
        provides: Terms of art this fragment defines, feeding the glossary
            that PC007 checks.
        contract: Path to a grammar or schema, project-relative. Required
            on tasks.
        budget: Optional per-fragment token ceiling. Zero means unset.
        priority: Breaks a trigger tie; higher wins.
        raw: The frontmatter mapping as parsed, for fields this class does
            not model.
    """

    id: str
    kind: str
    path: str
    body: str
    body_start: int = 1
    title: str = ""
    triggers: list = dataclasses.field(default_factory = list)
    requires: list = dataclasses.field(default_factory = list)
    provides: list = dataclasses.field(default_factory = list)
    contract: str = ""
    budget: int = 0
    priority: int = 0
    raw: dict = dataclasses.field(default_factory = dict)

    def body_line(self, offset):
        """Translate an offset within the body to a file line number.

        Args:
            offset: 0-indexed character offset into `body`.

        Returns:
            int: 1-indexed line in the file, accounting for the
            frontmatter block above the body.
        """
        return self.body_start + self.body.count("\n", 0, offset)

    def explicit_refs(self):
        """Find `{{ref:id}}` references in the body.

        Returns:
            list: (target_id, line) pairs, in document order. Whether a
            target is legitimate is PC001's question, not this one's.
        """
        found = []
        for match in REF_PATTERN.finditer(self.body):
            found.append((match.group(1), self.body_line(match.start())))
        return found

    def prose_refs(self):
        """Find positional references that can never resolve.

        Fragments assemble in different combinations per task, so "see
        above" or a section number points at nothing in most assemblies.

        Returns:
            list: (matched_text, label, line) triples. The label names the
            kind of reference, for the diagnostic message.
        """
        found = []
        for pattern, label in PROSE_REF_PATTERNS:
            for match in pattern.finditer(self.body):
                found.append((match.group(0).strip(), label, self.body_line(match.start())))
        return found

    def suppressions(self):
        """Find `promptc-disable` comments in the body.

        Returns:
            list: Suppression objects. Whitespace in the justification is
            collapsed, so a comment wrapped across lines still yields one
            readable reason. An empty justification is PC011's problem.
        """
        found = []
        for match in SUPPRESS_PATTERN.finditer(self.body):
            why = (match.group("why") or "").strip()
            found.append(diagnostics.Suppression(
                rule = match.group("rule"),
                justification = " ".join(why.split()),
                file = self.path,
                line = self.body_line(match.start()),
            ))
        return found

    def prose(self):
        """Return the body with suppression comments removed.

        Used by every text metric, so that a long justification cannot
        change a fragment's hedge density or instruction count.

        Returns:
            str: The body, minus suppression comments. Offsets no longer
            line up with the file, so do not pair this with body_line.
        """
        return SUPPRESS_PATTERN.sub("", self.body)

###########################################################
# Parse errors
###########################################################
class ParseError(Exception):
    """A fragment could not be parsed.

    Carries a location and a remedy so load_library can turn it into a
    PC000 diagnostic without inventing either.

    Attributes:
        path: Project-relative path of the offending file.
        line: 1-indexed line, or 1 when the fault is the file as a whole.
        message: What is wrong.
        fix_hint: The concrete remedy. May be empty where the message
            already says everything.
    """

    def __init__(self, path, line, message, fix_hint = ""):
        """Record where the parse failed and how to fix it."""
        super().__init__(message)
        self.path = path
        self.line = line
        self.message = message
        self.fix_hint = fix_hint

    def to_diagnostic(self):
        """Convert to a PC000 diagnostic.

        Returns:
            Diagnostic: ERROR severity, carrying this error's location and
            fix hint.
        """
        return diagnostics.Diagnostic(
            rule = "PC000",
            severity = diagnostics.Severity.ERROR,
            message = self.message,
            file = self.path,
            line = self.line,
            fix_hint = self.fix_hint,
        )

###########################################################
# Parsing
###########################################################
def split_frontmatter(text, path):
    """Split a fragment file into its frontmatter and body.

    Args:
        text: Full file contents.
        path: Project-relative path, for error reporting.

    Returns:
        tuple: (frontmatter_text, body, body_start_line). The body start is
        1-indexed and accounts for both `---` markers.

    Raises:
        ParseError: The file does not open with `---`, or the frontmatter
            block is never closed.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ParseError(
            path, 1,
            "Fragment has no YAML frontmatter.",
            "start the file with a `---` line; run `promptc new` for a valid skeleton.",
        )

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:])
            return frontmatter, body, index + 2

    raise ParseError(
        path, 1,
        "Frontmatter block is never closed.",
        "add a closing `---` line after the metadata.",
    )

def as_list(value, field, path):
    """Coerce a scalar-or-list frontmatter field into a list of strings.

    Writing `triggers: one_thing` is natural and common enough to accept
    rather than reject.

    Args:
        value: The raw YAML value. None yields an empty list.
        field: Field name, for error reporting.
        path: Project-relative path, for error reporting.

    Returns:
        list: Strings. Integers are stringified, since a numeric-looking
        trigger name is still a name.

    Raises:
        ParseError: The value is neither a scalar nor a list of scalars.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if not isinstance(item, (str, int)):
                raise ParseError(path, 1, f"`{field}` must be a list of strings.")
            out.append(str(item))
        return out
    raise ParseError(path, 1, f"`{field}` must be a string or list of strings.")

def parse_fragment(path, root = ""):
    """Parse one fragment file.

    Args:
        path: Absolute path to the file.
        root: Library root. When given, the fragment's recorded path is
            made relative to it, so diagnostics do not leak absolute paths.

    Returns:
        Fragment: Fully populated. Whether its metadata is *coherent* --
        references resolving, requires existing -- is the rules' question,
        not this function's.

    Raises:
        ParseError: Missing or malformed frontmatter, missing `id` or
            `kind`, an unknown kind, or a mistyped field.
    """
    with open(path, "r", encoding = "utf-8") as handle:
        text = handle.read()

    display = os.path.relpath(path, root) if root else path
    frontmatter_text, body, body_start = split_frontmatter(text, display)

    try:
        meta = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as error:
        raise ParseError(display, 1, f"Frontmatter is not valid YAML: {error}")

    if not isinstance(meta, dict):
        raise ParseError(display, 1, "Frontmatter must be a YAML mapping.")

    fragment_id = meta.get("id")
    if not fragment_id:
        raise ParseError(
            display, 1,
            "Fragment is missing required field `id`.",
            "add `id: <slug>` matching the filename stem.",
        )

    kind = meta.get("kind")
    if not kind:
        raise ParseError(
            display, 1,
            "Fragment is missing required field `kind`.",
            f"add `kind:` — one of {', '.join(KINDS)}.",
        )
    if kind not in KINDS:
        raise ParseError(
            display, 1,
            f"Unknown kind `{kind}`.",
            f"use one of {', '.join(KINDS)}.",
        )

    budget = meta.get("budget", 0)
    if not isinstance(budget, int):
        raise ParseError(display, 1, "`budget` must be an integer token count.")

    priority = meta.get("priority", 0)
    if not isinstance(priority, int):
        raise ParseError(display, 1, "`priority` must be an integer.")

    return Fragment(
        id = str(fragment_id),
        kind = kind,
        path = display,
        body = body,
        body_start = body_start,
        title = str(meta.get("title", "")),
        triggers = as_list(meta.get("triggers"), "triggers", display),
        requires = as_list(meta.get("requires"), "requires", display),
        provides = as_list(meta.get("provides"), "provides", display),
        contract = str(meta.get("contract", "")),
        budget = budget,
        priority = priority,
        raw = meta,
    )

def load_library(root):
    """Parse every fragment under a library directory.

    Walks recursively and in sorted order, so the result is deterministic
    regardless of filesystem ordering.

    Args:
        root: Library directory. A path that does not exist yields two
            empty lists rather than raising; the caller decides whether
            that is a configuration error.

    Returns:
        tuple: (fragments, diagnostics). A malformed file contributes a
        PC000 diagnostic instead of aborting, so one bad fragment out of
        sixty does not hide the state of the other fifty-nine.
    """
    fragments = []
    errors = []
    for directory, _, filenames in sorted(os.walk(root)):
        for filename in sorted(filenames):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(directory, filename)
            try:
                fragments.append(parse_fragment(path, root))
            except ParseError as error:
                errors.append(error.to_diagnostic())
    return fragments, errors
