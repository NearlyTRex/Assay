# Tests for promptc/split.py -- mechanical decomposition.
#
# The boundary under test: split proposes structure and rewrites references
# it can resolve exactly. It never rewrites prose or invents metadata, and
# anything it cannot resolve is reported rather than guessed at.

# Imports
import os

# Local imports
from promptc import split

###########################################################
# Fixtures
###########################################################
MONOLITH = """
# Big Prompt

## Rules

Always be careful.

### Fidelity Requirements

Match the original exactly.

### 20. Unchecked return value

Guard the result. See §21 for the related case.

### 21. Null dereference

Check before use. Related to §20.

### 99. References something absent

See §77 for details.
"""

def write_monolith(tmp_path, text = MONOLITH):
    source = os.path.join(str(tmp_path), "mono.md")
    os.makedirs(os.path.dirname(source), exist_ok = True)
    with open(source, "w", encoding = "utf-8") as handle:
        handle.write(text)
    return source

###########################################################
# Slugging
###########################################################
def test_slugify_lowercases_and_hyphenates():
    assert split.slugify("Unchecked Return-Value Guard") == "unchecked-return-value-guard"

def test_slugify_strips_backticks():
    assert split.slugify("Use `memcpy` here") == "use-memcpy-here"

def test_slugify_truncates_at_a_word_boundary():
    result = split.slugify("a " * 60, limit = 20)
    assert len(result) <= 20

def test_slugify_never_returns_empty():
    assert split.slugify("!!!") == "section"

###########################################################
# Section parsing
###########################################################
def test_numbered_headings_yield_a_legacy_number(tmp_path):
    sections = split.parse_sections(MONOLITH)
    numbered = [s for s in sections if s.number]
    assert {s.number for s in numbered} == {20, 21, 99}
    # The number is stripped from the title
    assert not any(s.title.startswith("20.") for s in numbered)

###########################################################
# Splitting
###########################################################
def test_split_maps_sections_and_rewrites_refs(tmp_path):
    source = write_monolith(tmp_path)
    out = os.path.join(str(tmp_path), "out")

    plan = split.split_file(source, out, level = 3, dry_run = False)

    ids = {section.slug for _, _, section in plan.fragments}
    assert "rules" in ids
    assert "fidelity-requirements" in ids

    assert plan.number_map[20] == "unchecked-return-value"
    assert plan.number_map[21] == "null-dereference"

    bodies = {section.slug: content for _, content, section in plan.fragments}
    assert "{{ref:null-dereference}}" in bodies["unchecked-return-value"]
    assert "{{ref:unchecked-return-value}}" in bodies["null-dereference"]

def test_rewritten_refs_are_added_to_requires(tmp_path):
    """A reference split just created is a dependency it knows about."""
    source = write_monolith(tmp_path)
    plan = split.split_file(source, os.path.join(str(tmp_path), "out"), dry_run = True)

    bodies = {section.slug: content for _, content, section in plan.fragments}
    assert "null-dereference" in bodies["unchecked-return-value"].split("---")[1]

def test_unresolvable_refs_are_reported_not_guessed(tmp_path):
    source = write_monolith(tmp_path)
    plan = split.split_file(source, os.path.join(str(tmp_path), "out"), dry_run = True)

    assert any(ref == "§77" for _, ref in plan.unresolved_refs)
    # And left untouched in the body
    bodies = {section.slug: content for _, content, section in plan.fragments}
    assert "§77" in bodies["references-something-absent"]

def test_children_hang_off_their_parent_section(tmp_path):
    source = write_monolith(tmp_path)
    plan = split.split_file(source, os.path.join(str(tmp_path), "out"), dry_run = True)

    bodies = {section.slug: content for _, content, section in plan.fragments}
    assert "requires: [rules]" in bodies["fidelity-requirements"]

def test_self_reference_becomes_prose(tmp_path):
    source = write_monolith(tmp_path, """
        # Doc

        ## Rules

        ### 5. Self referential

        As covered in §5, do the thing.
    """.replace("\n        ", "\n"))
    plan = split.split_file(source, os.path.join(str(tmp_path), "out"), dry_run = True)
    bodies = {section.slug: content for _, content, section in plan.fragments}
    assert "this recipe" in bodies["self-referential"]
    assert "{{ref:self-referential}}" not in bodies["self-referential"]

def test_duplicate_titles_get_distinct_ids(tmp_path):
    source = write_monolith(tmp_path, """
        # Doc

        ## Rules

        ### Overview

        First.

        ## Other

        ### Overview

        Second.
    """.replace("\n        ", "\n"))
    plan = split.split_file(source, os.path.join(str(tmp_path), "out"), dry_run = True)
    slugs = [section.slug for _, _, section in plan.fragments]
    assert len(slugs) == len(set(slugs))
    assert "overview" in slugs
    assert "overview-2" in slugs

###########################################################
# Dry run
###########################################################
def test_dry_run_writes_nothing(tmp_path):
    source = write_monolith(tmp_path)
    out = os.path.join(str(tmp_path), "out")
    split.split_file(source, out, dry_run = True)
    assert not os.path.exists(out)

def test_apply_writes_parseable_fragments(tmp_path):
    from promptc import fragment as fragment_module

    source = write_monolith(tmp_path)
    out = os.path.join(str(tmp_path), "out")
    split.split_file(source, out, dry_run = False)

    fragments, errors = fragment_module.load_library(out)
    assert errors == []
    assert len(fragments) >= 5

###########################################################
# YAML safety
###########################################################
def test_titles_with_colons_are_quoted(tmp_path):
    source = write_monolith(tmp_path, """
        # Doc

        ## Rules

        ### Warning: do not do this

        Body.
    """.replace("\n        ", "\n"))
    out = os.path.join(str(tmp_path), "out")
    split.split_file(source, out, dry_run = False)

    from promptc import fragment as fragment_module
    fragments, errors = fragment_module.load_library(out)
    assert errors == []
    titles = [item.title for item in fragments]
    assert "Warning: do not do this" in titles
