# Fragment parsing.
#
# A fragment is a markdown file with YAML frontmatter. The frontmatter is
# what makes the structural checks decidable -- `requires` bounds what a
# fragment may reference, `provides` builds the glossary, `triggers` gives
# mechanical routing with no model judgement involved.

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
    id: str
    kind: str
    path: str
    body: str
    # Line number (1-indexed) in the file where the body starts
    body_start: int = 1
    title: str = ""
    triggers: list = dataclasses.field(default_factory = list)
    requires: list = dataclasses.field(default_factory = list)
    provides: list = dataclasses.field(default_factory = list)
    contract: str = ""
    budget: int = 0
    priority: int = 0
    raw: dict = dataclasses.field(default_factory = dict)

    # Translate a 0-indexed offset within the body to a 1-indexed file line
    def body_line(self, offset):
        return self.body_start + self.body.count("\n", 0, offset)

    def explicit_refs(self):
        found = []
        for match in REF_PATTERN.finditer(self.body):
            found.append((match.group(1), self.body_line(match.start())))
        return found

    def prose_refs(self):
        found = []
        for pattern, label in PROSE_REF_PATTERNS:
            for match in pattern.finditer(self.body):
                found.append((match.group(0).strip(), label, self.body_line(match.start())))
        return found

    def suppressions(self):
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

    # Body with suppression comments removed, for text metrics
    def prose(self):
        return SUPPRESS_PATTERN.sub("", self.body)

###########################################################
# Parse errors
###########################################################
class ParseError(Exception):
    def __init__(self, path, line, message, fix_hint = ""):
        super().__init__(message)
        self.path = path
        self.line = line
        self.message = message
        self.fix_hint = fix_hint

    def to_diagnostic(self):
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
# Split a file into (frontmatter_text, body, body_start_line).
def split_frontmatter(text, path):
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

# Coerce a scalar-or-list field into a list of strings
def as_list(value, field, path):
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

# Walk a library directory and parse everything that looks like a fragment.
# Returns (fragments, parse_diagnostics) so a malformed file reports rather
# than aborting the whole run.
def load_library(root):
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
