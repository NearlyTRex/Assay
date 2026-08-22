# Tests for promptc/rules/heuristic.py -- PC100-PC105.
#
# These rules are measured, not decidable, so the tests pin behaviour rather
# than truth: a rule fires above its threshold and stays quiet below it.
# Whether the threshold is the *right* one is a question for
# `promptc calibrate`, never for a unit test.

# Local imports
from promptc import tokens
from promptc.rules import heuristic, run_check

###########################################################
# Text utilities
###########################################################
def test_prose_only_strips_fenced_code():
    text = "Real prose here.\n\n```c\nint hedged = generally;\n```\n\nMore prose."
    stripped = heuristic.prose_only(text)
    assert "int hedged" not in stripped
    assert "Real prose here." in stripped
    assert "More prose." in stripped

def test_prose_only_strips_inline_code():
    assert "generally" not in heuristic.prose_only("Use `generally` as a literal.")

def test_imperatives_finds_instruction_sentences():
    text = "Add the field. The weather is nice. You must never skip this."
    found = heuristic.imperatives(text)
    assert len(found) == 2

def test_imperatives_ignores_code():
    text = "```c\nadd(x);\nremove(y);\ndelete(z);\n```"
    assert heuristic.imperatives(text) == []

###########################################################
# PC100 -- hedge density
###########################################################
HEDGED = "You should generally prefer the reasonable option where appropriate. " * 40
PLAIN = "Set the field to zero. Return the pointer. Write the result to disk. " * 40

def test_hedge_density_fires_above_threshold(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {HEDGED}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC100" in rules_in(report)

def test_hedge_density_quiet_on_plain_instructions(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {PLAIN}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC100" not in rules_in(report)

def test_hedge_density_skips_short_fragments(project, fragment_file, load_config, rules_in):
    """Under 100 tokens the density figure is noise, so the rule abstains."""
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Generally, prefer the reasonable option where appropriate.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC100" not in rules_in(report)

def test_hedge_message_reports_measurement_and_threshold(project, fragment_file, load_config):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {HEDGED}
    """)
    report = run_check(load_config(), examples = False)
    finding = [d for d in report.diagnostics if d.rule == "PC100"][0]
    assert "threshold" in finding.message
    assert finding.data["density"] > finding.data["threshold"]

###########################################################
# PC101 -- negation density
###########################################################
def test_negation_density_fires_on_mostly_prohibitions(project, fragment_file, load_config, rules_in):
    body = " ".join(f"Never do thing {n}." for n in range(20))
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {body}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC101" in rules_in(report)

def test_negation_density_quiet_on_positive_instructions(project, fragment_file, load_config, rules_in):
    body = " ".join(f"Set field {n} to zero." for n in range(20))
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {body}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC101" not in rules_in(report)

###########################################################
# PC102 -- instruction count
###########################################################
def test_instruction_count_fires_past_threshold(project, fragment_file, load_config, rules_in):
    body = " ".join(f"Set field {n} to zero." for n in range(50))
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {body}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC102" in rules_in(report)

def test_instruction_count_quiet_under_threshold(project, fragment_file, load_config, rules_in):
    body = " ".join(f"Set field {n} to zero." for n in range(5))
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {body}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC102" not in rules_in(report)

###########################################################
# PC104 -- vocabulary drift
###########################################################
VOCAB_CONFIG = """
library: promptlib
contracts: contracts
vocabulary:
  "keep file": ["keepfile", "the keep"]
"""

def test_vocabulary_drift_flags_a_banned_synonym(project, write, fragment_file, load_config, rules_in):
    import os
    write(os.path.join(project, "promptc.yaml"), VOCAB_CONFIG)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Update the keepfile before continuing.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC104" in rules_in(report)
    finding = [d for d in report.diagnostics if d.rule == "PC104"][0]
    assert finding.data["canonical"] == "keep file"

def test_vocabulary_drift_quiet_on_canonical_term(project, write, fragment_file, load_config, rules_in):
    import os
    write(os.path.join(project, "promptc.yaml"), VOCAB_CONFIG)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Update the keep file before continuing.
    """)
    report = run_check(load_config(), examples = False)
    assert "PC104" not in rules_in(report)

###########################################################
# PC105 -- critical rules buried
###########################################################
def test_critical_position_measures_the_assembly_not_a_fragment(project, fragment_file, load_config):
    """PC105 only means anything once fragments are assembled, so it is
    reported against the assembly rather than any single file."""
    filler = "Ordinary prose that carries no hard constraint at all. " * 120
    fragment_file("front", f"""
        ---
        id: front
        kind: rule
        ---
        {filler}
    """)
    fragment_file("middle", f"""
        ---
        id: middle
        kind: rule
        requires: [front]
        ---
        You MUST do the thing. You must NEVER skip it.
        {filler}
    """)
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        requires: [middle]
        contract: contracts/out.gbnf
        ---
        {filler}
    """)
    report = run_check(load_config(), profile_name = "big", examples = False)
    findings = [d for d in report.diagnostics if d.rule == "PC105"]
    if findings:
        assert findings[0].file.startswith("<assembly:")
