# Diagnostic records and reporting.
#
# Every rule emits Diagnostic objects. Nothing in the toolset prints
# free-form errors -- if it is a finding, it has a stable rule ID, a
# location, and a fix hint, so an agent can act on it without reading
# the docs.

# Imports
import dataclasses
import enum
import json
import os
import sys

###########################################################
# Severity
###########################################################
class Severity(enum.Enum):
    ERROR = "error"
    WARN = "warn"
    INFO = "info"

    # Only errors fail the build
    def is_fatal(self):
        return self is Severity.ERROR

# Rank used for stable sorting (most severe first)
SEVERITY_RANK = {
    Severity.ERROR: 0,
    Severity.WARN: 1,
    Severity.INFO: 2,
}

###########################################################
# Diagnostic
###########################################################
@dataclasses.dataclass
class Diagnostic:
    rule: str
    severity: Severity
    message: str
    file: str = ""
    line: int = 0
    col: int = 0
    fix_hint: str = ""
    # Free-form structured payload for tooling (never rendered in text mode)
    data: dict = dataclasses.field(default_factory=dict)

    # Sort key: severity, then location, then rule
    def sort_key(self):
        return (SEVERITY_RANK[self.severity], self.file, self.line, self.col, self.rule)

    def to_dict(self):
        out = {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "fix_hint": self.fix_hint,
        }
        if self.data:
            out["data"] = self.data
        return out

###########################################################
# Suppression
###########################################################
@dataclasses.dataclass
class Suppression:
    rule: str
    justification: str
    file: str
    line: int
    used: bool = False

###########################################################
# Colour handling
###########################################################
# Colour only when attached to a TTY and not explicitly disabled.
def use_colour(stream = None):
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("PROMPTC_NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()

COLOURS = {
    Severity.ERROR: "\033[31;1m",
    Severity.WARN: "\033[33;1m",
    Severity.INFO: "\033[36;1m",
}
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

###########################################################
# Report
###########################################################
class Report:
    def __init__(self):
        self.diagnostics = []
        self.suppressions = []

    def add(self, diagnostic):
        self.diagnostics.append(diagnostic)

    def extend(self, diagnostics):
        self.diagnostics.extend(diagnostics)

    # Drop diagnostics matched by a suppression comment, marking each
    # suppression used so unused ones can be reported in turn.
    def apply_suppressions(self, suppressions):
        self.suppressions = list(suppressions)
        by_file = {}
        for suppression in self.suppressions:
            by_file.setdefault(suppression.file, []).append(suppression)

        kept = []
        for diagnostic in self.diagnostics:
            match = None
            for suppression in by_file.get(diagnostic.file, []):
                if suppression.rule == diagnostic.rule:
                    match = suppression
                    break
            if match is None:
                kept.append(diagnostic)
            else:
                match.used = True
        self.diagnostics = kept

    def counts(self):
        counts = {severity: 0 for severity in Severity}
        for diagnostic in self.diagnostics:
            counts[diagnostic.severity] += 1
        return counts

    def has_errors(self):
        return any(d.severity.is_fatal() for d in self.diagnostics)

    def exit_code(self):
        return 1 if self.has_errors() else 0

    def sorted(self):
        return sorted(self.diagnostics, key = lambda d: d.sort_key())

    ###########################################################
    # Rendering
    ###########################################################
    def render_json(self):
        counts = self.counts()
        payload = {
            "diagnostics": [d.to_dict() for d in self.sorted()],
            "summary": {
                "errors": counts[Severity.ERROR],
                "warnings": counts[Severity.WARN],
                "info": counts[Severity.INFO],
                "suppressed": sum(1 for s in self.suppressions if s.used),
            },
            "ok": not self.has_errors(),
        }
        return json.dumps(payload, indent = 2, sort_keys = False)

    def render_text(self, colour = None):
        if colour is None:
            colour = use_colour()

        def paint(text, code):
            return f"{code}{text}{RESET}" if colour else text

        lines = []
        for diagnostic in self.sorted():
            location = diagnostic.file
            if diagnostic.line:
                location += f":{diagnostic.line}"
                if diagnostic.col:
                    location += f":{diagnostic.col}"

            severity = paint(f"{diagnostic.severity.value:<7}", COLOURS[diagnostic.severity])
            rule = paint(diagnostic.rule, BOLD)
            lines.append(f"{severity} {rule}  {location}")
            for message_line in diagnostic.message.splitlines():
                lines.append(f"        {message_line}")
            if diagnostic.fix_hint:
                lines.append(paint(f"        fix: {diagnostic.fix_hint}", DIM))
            lines.append("")

        counts = self.counts()
        parts = []
        if counts[Severity.ERROR]:
            parts.append(f"{counts[Severity.ERROR]} error" + ("s" if counts[Severity.ERROR] != 1 else ""))
        if counts[Severity.WARN]:
            parts.append(f"{counts[Severity.WARN]} warning" + ("s" if counts[Severity.WARN] != 1 else ""))
        if counts[Severity.INFO]:
            parts.append(f"{counts[Severity.INFO]} info")

        suppressed = sum(1 for s in self.suppressions if s.used)
        if suppressed:
            parts.append(f"{suppressed} suppressed")

        summary = ", ".join(parts) if parts else "no findings"
        code = COLOURS[Severity.ERROR] if self.has_errors() else "\033[32;1m"
        lines.append(paint(summary, code) + paint(f" — exit {self.exit_code()}", DIM))
        return "\n".join(lines)
