"""Diagnostic records and reporting.

Every rule emits Diagnostic objects. Nothing in the toolset prints
free-form errors -- if it is a finding, it has a stable rule id, a location,
and a fix hint, so an agent can act on it without reading the docs.

Rendering is deliberately separate from producing findings: the same Report
serves a human as text and an agent as JSON, and neither format is allowed
to be the only place a piece of information exists.
"""

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
    """How a finding affects the build.

    Only ERROR affects the exit code. A heuristic rule may never be an
    ERROR -- see docs/coding-standard/invariants.md.
    """

    ERROR = "error"
    WARN = "warn"
    INFO = "info"

    def is_fatal(self):
        """Return True if this severity should fail the build."""
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
    """One finding, addressed to whoever has to act on it.

    Attributes:
        rule: Stable rule id, `PC` plus three digits.
        severity: Severity. Only ERROR affects the exit code.
        message: What was found. States the measurement and the threshold
            where there is one, so the reader can judge it without
            re-running anything. May span several lines.
        file: Project-relative path, so findings are stable across machines.
            The pseudo-path `<assembly:task-id>` is used for findings about
            an assembly rather than a file.
        line: 1-indexed line in the file, or 0 when not applicable.
        col: 1-indexed column, or 0 when not applicable.
        fix_hint: The concrete edit that resolves this. An agent acts on it
            without loading documentation, so it names the change rather
            than restating the problem.
        data: Structured payload for tooling -- anything a caller might
            compare, sort or threshold. Never rendered in text mode, and
            omitted from JSON when empty.
    """

    rule: str
    severity: Severity
    message: str
    file: str = ""
    line: int = 0
    col: int = 0
    fix_hint: str = ""
    data: dict = dataclasses.field(default_factory=dict)

    def sort_key(self):
        """Return the ordering key: severity, then location, then rule."""
        return (SEVERITY_RANK[self.severity], self.file, self.line, self.col, self.rule)

    def to_dict(self):
        """Return the JSON representation.

        Returns:
            dict: Always carries rule, severity, message, file, line, col
            and fix_hint. `data` is present only when non-empty, so
            consumers must treat it as optional.
        """
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
    """A `promptc-disable` comment found in a fragment.

    Suppressions are scoped to their file and their rule. `used` is set by
    Report.apply_suppressions so that stale ones can be reported as PC012 --
    a suppression matching nothing hides the fact that the problem was
    fixed, and will silently mask the rule if it recurs.

    Attributes:
        rule: Rule id being silenced.
        justification: The written reason. An empty or near-empty
            justification is itself an error (PC011).
        file: Project-relative path of the fragment carrying the comment.
        line: 1-indexed line of the comment.
        used: Whether any diagnostic was actually suppressed by this.
    """

    rule: str
    justification: str
    file: str
    line: int
    used: bool = False

###########################################################
# Colour handling
###########################################################
def use_colour(stream = None):
    """Return True if ANSI colour should be emitted.

    Colour is used only when attached to a TTY and not explicitly disabled,
    so piped output stays parseable.

    Args:
        stream: Stream to test. Defaults to stdout.

    Returns:
        bool: False when NO_COLOR or PROMPTC_NO_COLOR is set in the
        environment, or the stream is not a terminal.
    """
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
    """A collection of findings, plus the suppressions applied to them."""

    def __init__(self):
        """Create an empty report."""
        self.diagnostics = []
        self.suppressions = []

    def add(self, diagnostic):
        """Append one diagnostic."""
        self.diagnostics.append(diagnostic)

    def extend(self, diagnostics):
        """Append many diagnostics."""
        self.diagnostics.extend(diagnostics)

    def apply_suppressions(self, suppressions):
        """Drop diagnostics matched by a suppression comment.

        Matching is by rule id and file, so a suppression in one fragment
        never silences the same rule in another. Each matched suppression is
        marked used, which is what lets check_unused_suppressions report the
        stale ones afterwards.

        Args:
            suppressions: Suppression objects gathered from every fragment.
                Stored on the report, and mutated in place to set `used`.
        """
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
        """Return a count per severity.

        Returns:
            dict: Every Severity is present, including those at zero.
        """
        counts = {severity: 0 for severity in Severity}
        for diagnostic in self.diagnostics:
            counts[diagnostic.severity] += 1
        return counts

    def has_errors(self):
        """Return True if any finding is fatal."""
        return any(d.severity.is_fatal() for d in self.diagnostics)

    def exit_code(self):
        """Return the process exit code: 1 when errors were found, else 0.

        Warnings never fail the build, however many there are.
        """
        return 1 if self.has_errors() else 0

    def sorted(self):
        """Return findings ordered by severity, location, then rule id.

        Deterministic, so a diff between two runs is a real change.
        """
        return sorted(self.diagnostics, key = lambda d: d.sort_key())

    ###########################################################
    # Rendering
    ###########################################################
    def render_json(self):
        """Render findings as JSON, for an agent.

        Returns:
            str: An object with `diagnostics`, a `summary` of counts
            including how many were suppressed, and `ok` -- which reflects
            errors only, matching the exit code rather than the total
            number of findings.
        """
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
        """Render findings as text, for a human.

        Multi-line messages are indented under their heading, and the fix
        hint is dimmed so the finding itself reads first.

        Args:
            colour: Force colour on or off. Defaults to autodetecting the
                terminal via use_colour.

        Returns:
            str: The findings followed by a summary line. The summary reads
            "no findings" when the report is empty.
        """
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
