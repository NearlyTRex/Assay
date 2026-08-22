# Tests for promptc/fragment.py -- frontmatter parsing and reference extraction.

# Imports
import os

# Third party
import pytest

# Local imports
from promptc import fragment

###########################################################
# Parsing
###########################################################
def test_parses_frontmatter_and_tracks_line_numbers(project, fragment_file):
    fragment_file("alpha", """
        ---
        id: alpha
        kind: rule
        title: Alpha
        provides: [widget]
        ---

        Body line one.
        Body line two.
    """)
    fragments, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert errors == []
    assert len(fragments) == 1

    item = fragments[0]
    assert item.id == "alpha"
    assert item.kind == "rule"
    assert item.provides == ["widget"]

    # "Body line one." is the 8th line of the file; diagnostics point at the
    # file, not at an offset into the body.
    offset = item.body.index("Body line one.")
    assert item.body_line(offset) == 8

def test_missing_frontmatter_is_a_parse_error(project, fragment_file):
    fragment_file("bad", "no frontmatter here\n")
    _, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert len(errors) == 1
    assert errors[0].rule == "PC000"
    assert errors[0].fix_hint

def test_unclosed_frontmatter_is_a_parse_error(project, fragment_file):
    fragment_file("bad", """
        ---
        id: bad
        kind: rule

        body with no closing marker
    """)
    _, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert len(errors) == 1
    assert "never closed" in errors[0].message

def test_unknown_kind_rejected(project, fragment_file):
    fragment_file("bad", """
        ---
        id: bad
        kind: nonsense
        ---
        body
    """)
    _, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert len(errors) == 1
    assert "Unknown kind" in errors[0].message

def test_missing_id_rejected(project, fragment_file):
    fragment_file("bad", """
        ---
        kind: rule
        ---
        body
    """)
    _, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert len(errors) == 1
    assert "`id`" in errors[0].message

def test_invalid_yaml_rejected(project, fragment_file):
    fragment_file("bad", """
        ---
        id: bad
        kind: [unclosed
        ---
        body
    """)
    _, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert len(errors) == 1
    assert "not valid YAML" in errors[0].message

def test_scalar_fields_coerce_to_lists(project, fragment_file):
    fragment_file("alpha", """
        ---
        id: alpha
        kind: recipe
        triggers: single_trigger
        requires: one-thing
        ---
        Body.
    """)
    fragments, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert errors == []
    assert fragments[0].triggers == ["single_trigger"]
    assert fragments[0].requires == ["one-thing"]

###########################################################
# References
###########################################################
def test_explicit_refs_are_extracted_with_locations(project, fragment_file):
    fragment_file("alpha", """
        ---
        id: alpha
        kind: rule
        ---
        See {{ref:other-thing}} for the rest.
    """)
    fragments, _ = fragment.load_library(os.path.join(project, "promptlib"))
    refs = fragments[0].explicit_refs()
    assert refs == [("other-thing", 5)]

@pytest.mark.parametrize("text,label", [
    ("Apply §20 to the input.", "section-number reference"),
    ("As described above, do it.", "backward prose reference"),
    ("See the section above.", "backward prose reference"),
    ("The previous section covers it.", "backward prose reference"),
    ("Use the list below.", "forward prose reference"),
    ("Earlier in this document we said so.", "backward prose reference"),
])
def test_prose_reference_forms_are_detected(project, fragment_file, text, label):
    fragment_file("alpha", f"""
        ---
        id: alpha
        kind: rule
        ---
        {text}
    """)
    fragments, _ = fragment.load_library(os.path.join(project, "promptlib"))
    found = fragments[0].prose_refs()
    assert len(found) == 1
    assert found[0][1] == label

###########################################################
# Suppressions
###########################################################
def test_suppression_is_parsed_with_justification(project, fragment_file):
    fragment_file("alpha", """
        ---
        id: alpha
        kind: rule
        ---
        <!-- promptc-disable PC100: measured, no delta on n=480 -->
        Body.
    """)
    fragments, _ = fragment.load_library(os.path.join(project, "promptlib"))
    suppressions = fragments[0].suppressions()
    assert len(suppressions) == 1
    assert suppressions[0].rule == "PC100"
    assert suppressions[0].justification == "measured, no delta on n=480"

def test_prose_excludes_suppression_comments(project, fragment_file):
    fragment_file("alpha", """
        ---
        id: alpha
        kind: rule
        ---
        <!-- promptc-disable PC100: a reason that is long enough -->
        Real body text.
    """)
    fragments, _ = fragment.load_library(os.path.join(project, "promptlib"))
    assert "promptc-disable" not in fragments[0].prose()
    assert "Real body text." in fragments[0].prose()

###########################################################
# Library loading
###########################################################
def test_load_library_walks_subdirectories(project, write):
    write(os.path.join(project, "promptlib", "nested", "deep", "a.md"), """
        ---
        id: deep-one
        kind: rule
        ---
        Body.
    """)
    fragments, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert errors == []
    assert [item.id for item in fragments] == ["deep-one"]

def test_one_bad_file_does_not_abort_the_rest(project, fragment_file):
    fragment_file("good", """
        ---
        id: good
        kind: rule
        ---
        Body.
    """)
    fragment_file("bad", "not a fragment\n")
    fragments, errors = fragment.load_library(os.path.join(project, "promptlib"))
    assert [item.id for item in fragments] == ["good"]
    assert len(errors) == 1
