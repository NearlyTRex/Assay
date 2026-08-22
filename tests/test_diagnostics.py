# Tests for promptc/diagnostics.py -- findings, reports, rendering.

# Imports
import json

# Third party
import pytest

# Local imports
from promptc import diagnostics
from promptc.diagnostics import Diagnostic, Report, Severity, Suppression

###########################################################
# Helpers
###########################################################
def make(rule = "PC001", severity = Severity.ERROR, file = "a.md", line = 1):
    return Diagnostic(
        rule = rule, severity = severity, message = f"{rule} fired",
        file = file, line = line, fix_hint = "do the thing")

###########################################################
# Severity
###########################################################
def test_only_errors_are_fatal():
    assert Severity.ERROR.is_fatal()
    assert not Severity.WARN.is_fatal()
    assert not Severity.INFO.is_fatal()

###########################################################
# Sorting
###########################################################
def test_sorted_puts_errors_first():
    report = Report()
    report.add(make("PC100", Severity.WARN))
    report.add(make("PC001", Severity.ERROR))
    assert [d.rule for d in report.sorted()] == ["PC001", "PC100"]

def test_sort_is_stable_by_location_then_rule():
    report = Report()
    report.add(make("PC002", file = "b.md", line = 1))
    report.add(make("PC001", file = "a.md", line = 9))
    report.add(make("PC001", file = "a.md", line = 2))
    assert [(d.file, d.line) for d in report.sorted()] == [
        ("a.md", 2), ("a.md", 9), ("b.md", 1)]

###########################################################
# Exit codes
###########################################################
def test_warnings_alone_do_not_fail():
    report = Report()
    report.add(make("PC100", Severity.WARN))
    assert not report.has_errors()
    assert report.exit_code() == 0

def test_any_error_fails():
    report = Report()
    report.add(make("PC100", Severity.WARN))
    report.add(make("PC001", Severity.ERROR))
    assert report.exit_code() == 1

def test_empty_report_passes():
    assert Report().exit_code() == 0

###########################################################
# Suppressions
###########################################################
def test_matching_suppression_removes_the_finding():
    report = Report()
    report.add(make("PC100", Severity.WARN, file = "a.md"))
    suppression = Suppression("PC100", "a good reason", "a.md", 3)

    report.apply_suppressions([suppression])
    assert report.diagnostics == []
    assert suppression.used

def test_suppression_is_scoped_to_its_file():
    report = Report()
    report.add(make("PC100", Severity.WARN, file = "other.md"))
    suppression = Suppression("PC100", "a good reason", "a.md", 3)

    report.apply_suppressions([suppression])
    assert len(report.diagnostics) == 1
    assert not suppression.used

def test_suppression_is_scoped_to_its_rule():
    report = Report()
    report.add(make("PC101", Severity.WARN, file = "a.md"))
    suppression = Suppression("PC100", "a good reason", "a.md", 3)

    report.apply_suppressions([suppression])
    assert len(report.diagnostics) == 1
    assert not suppression.used

###########################################################
# Counting
###########################################################
def test_counts_by_severity():
    report = Report()
    report.add(make("PC001", Severity.ERROR))
    report.add(make("PC002", Severity.ERROR))
    report.add(make("PC100", Severity.WARN))
    counts = report.counts()
    assert counts[Severity.ERROR] == 2
    assert counts[Severity.WARN] == 1
    assert counts[Severity.INFO] == 0

###########################################################
# Rendering
###########################################################
def test_json_render_is_parseable_and_complete():
    report = Report()
    report.add(make("PC001", Severity.ERROR))
    payload = json.loads(report.render_json())

    assert payload["ok"] is False
    assert payload["summary"]["errors"] == 1
    entry = payload["diagnostics"][0]
    for key in ("rule", "severity", "message", "file", "line", "col", "fix_hint"):
        assert key in entry

def test_json_reports_ok_when_clean():
    payload = json.loads(Report().render_json())
    assert payload["ok"] is True
    assert payload["diagnostics"] == []

def test_json_includes_suppressed_count():
    report = Report()
    report.add(make("PC100", Severity.WARN, file = "a.md"))
    report.apply_suppressions([Suppression("PC100", "a good reason", "a.md", 3)])
    payload = json.loads(report.render_json())
    assert payload["summary"]["suppressed"] == 1

def test_text_render_carries_rule_location_and_hint():
    report = Report()
    report.add(make("PC001", Severity.ERROR, file = "a.md", line = 41))
    text = report.render_text(colour = False)
    assert "PC001" in text
    assert "a.md:41" in text
    assert "fix: do the thing" in text
    assert "exit 1" in text

def test_text_render_says_no_findings_when_clean():
    assert "no findings" in Report().render_text(colour = False)

def test_colour_disabled_by_env(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert not diagnostics.use_colour()

def test_data_omitted_from_json_when_empty():
    entry = make().to_dict()
    assert "data" not in entry

def test_data_included_when_present():
    finding = make()
    finding.data = {"tokens": 10}
    assert finding.to_dict()["data"] == {"tokens": 10}
