# Tests for promptc/rules/__init__.py -- check orchestration.
#
# These cover how run_check wires the rule modules together: what it skips,
# what it needs a profile for, and how suppressions are applied at the end.

# Local imports
from promptc.rules import run_check

###########################################################
# Empty and broken libraries
###########################################################
def test_missing_library_directory_is_an_error(project, write, load_config, rules_in):
    import os
    write(os.path.join(project, "promptc.yaml"), """
        library: nonexistent
        contracts: contracts
    """)
    report = run_check(load_config(), examples = False)
    assert "PC000" in rules_in(report)
    assert report.exit_code() == 1

def test_empty_library_is_not_an_error(project, load_config):
    """An empty but present library has nothing wrong with it yet."""
    report = run_check(load_config(), examples = False)
    assert report.exit_code() == 0

###########################################################
# Profiles
###########################################################
def test_no_profile_means_no_budget_check(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {"word " * 4000}
    """)
    report = run_check(load_config(), examples = False)
    assert "PC004" not in rules_in(report)

def test_unknown_profile_is_reported(project, load_config, rules_in):
    report = run_check(load_config(), profile_name = "nonexistent", examples = False)
    assert "PC000" in rules_in(report)
    finding = [d for d in report.diagnostics if d.rule == "PC000"][0]
    assert "Known profiles" in finding.message

def test_unavailable_tokenizer_falls_back_loudly(project, write, fragment_file, load_config, rules_in):
    import os
    write(os.path.join(project, "promptc.yaml"), """
        library: promptlib
        contracts: contracts
        profiles:
          broken:
            context: 4000
            output_reserve: 200
            tokenizer: nonsense:thing
    """)
    fragment_file("task-a", """
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        Body.
    """)
    report = run_check(load_config(), profile_name = "broken", examples = False)
    assert "PC014" in rules_in(report)
    # The run continues on estimation rather than aborting
    assert report.exit_code() == 0

###########################################################
# Task filtering
###########################################################
def test_task_filter_limits_assembly_checks(project, fragment_file, load_config, rules_in):
    fragment_file("task-big", f"""
        ---
        id: task-big
        kind: task
        contract: contracts/out.gbnf
        ---
        {"word " * 4000}
    """)
    fragment_file("task-small", """
        ---
        id: task-small
        kind: task
        contract: contracts/out.gbnf
        ---
        Short.
    """)
    # Checking only the small task must not surface the big task's overrun
    report = run_check(load_config(), profile_name = "small",
                       tasks = ["task-small"], examples = False)
    assert "PC004" not in rules_in(report)

    report = run_check(load_config(), profile_name = "small",
                       tasks = ["task-big"], examples = False)
    assert "PC004" in rules_in(report)

###########################################################
# Suppressions
###########################################################
HEDGED = "You should generally prefer the reasonable option where appropriate. " * 40

def test_suppression_actually_suppresses(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        {HEDGED}
    """)
    assert "PC100" in rules_in(run_check(load_config(), examples = False))

    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        <!-- promptc-disable PC100: domain vocabulary, verified in run 2026-08-22 -->
        {HEDGED}
    """)
    assert "PC100" not in rules_in(run_check(load_config(), examples = False))

def test_no_suppress_reports_findings_anyway(project, fragment_file, load_config, rules_in):
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        contract: contracts/out.gbnf
        ---
        <!-- promptc-disable PC100: domain vocabulary, verified in run 2026-08-22 -->
        {HEDGED}
    """)
    report = run_check(load_config(), examples = False, honour_suppressions = False)
    assert "PC100" in rules_in(report)

def test_suppression_does_not_leak_across_files(project, fragment_file, load_config, rules_in):
    fragment_file("suppressed", f"""
        ---
        id: suppressed
        kind: rule
        ---
        <!-- promptc-disable PC100: justified for this fragment only -->
        {HEDGED}
    """)
    fragment_file("task-a", f"""
        ---
        id: task-a
        kind: task
        requires: [suppressed]
        contract: contracts/out.gbnf
        ---
        {HEDGED}
    """)
    report = run_check(load_config(), examples = False)
    # The task's own hedging is still reported
    findings = [d for d in report.diagnostics if d.rule == "PC100"]
    assert [d.file for d in findings] == ["task-a.md"]
