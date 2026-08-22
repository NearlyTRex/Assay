"""Mechanical decomposition of a monolithic prompt.

`split` proposes structure and stops. It slices on the heading tree,
derives ids, wires `requires` to the parent section, and rewrites the
section-number references it can resolve exactly. It never rewrites prose
-- that is the authoring model's job, gated by `check`.

The boundary is deliberate. Everything here is derivable from the document:
which heading owns which text, which `§20` maps to which section, which
slug collides with which. The moment the tool starts making editorial calls
it becomes another thing you have to verify. Anything it cannot resolve is
reported rather than guessed at, and becomes a PC001 error until a human or
an authoring model fixes it.
"""

# Imports
import dataclasses
import os
import re

# Local imports
from . import fragment as fragment_module

HEADING_PATTERN = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<title>.+?)[ \t]*$", re.M)

# "### 20. Unchecked return value" -> legacy section number 20
NUMBERED_PATTERN = re.compile(r"^(?P<number>\d+)[.)]\s*(?P<rest>.+)$")

###########################################################
# Slugging
###########################################################
def slugify(text, limit = 48):
    """Convert a heading into a fragment id.

    Args:
        text: Heading text. Backticks are unwrapped rather than dropped, so
            `` `memcpy` `` keeps its word.
        limit: Maximum length. Truncation falls back to a word boundary, so
            an id never ends mid-word.

    Returns:
        str: A lowercase kebab-case slug, never empty -- a heading of pure
        punctuation yields "section". Uniqueness is plan_split's problem.
    """
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > limit:
        cut = text[:limit].rsplit("-", 1)[0]
        text = cut or text[:limit]
    return text or "section"

###########################################################
# Sections
###########################################################
@dataclasses.dataclass
class Section:
    """One heading and the text beneath it.

    Attributes:
        level: Heading depth -- 1 for `#`, 2 for `##`, and so on.
        title: Heading text, with any leading section number removed.
        body: Everything up to the next heading of any level.
        line: 1-indexed line of the heading in the source document.
        number: Leading section number, e.g. 20 from "20. Missing memcpy".
            Zero when unnumbered. This is what makes `§20` resolvable.
        slug: Derived fragment id, assigned by plan_split.
        parent: Slug of the enclosing shallower section, or empty.
        kind: Fragment kind to emit.
    """

    level: int
    title: str
    body: str
    line: int
    number: int = 0
    slug: str = ""
    parent: str = ""
    kind: str = "recipe"

def parse_sections(text):
    """Split a document into sections on its heading tree.

    Args:
        text: The whole document.

    Returns:
        list: Section objects in document order, with `number` extracted
        from numbered headings and stripped from the title. Slugs and
        parents are not yet assigned.
    """
    matches = list(HEADING_PATTERN.finditer(text))
    sections = []

    for position, match in enumerate(matches):
        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        title = match.group("title").strip()
        line = text.count("\n", 0, match.start()) + 1

        number = 0
        numbered = NUMBERED_PATTERN.match(title)
        if numbered:
            number = int(numbered.group("number"))
            title = numbered.group("rest").strip()

        sections.append(Section(
            level = len(match.group("hashes")),
            title = title,
            body = text[start:end].strip("\n"),
            line = line,
            number = number,
        ))
    return sections

###########################################################
# Planning
###########################################################
@dataclasses.dataclass
class Plan:
    """What a split produced, or would produce on a dry run.

    Attributes:
        fragments: (path, content, section) triples, in document order.
        number_map: Legacy section number to fragment id, used for
            reference rewriting and reported so a reader can check it.
        unresolved_refs: (fragment_slug, reference_text) pairs for section
            numbers that mapped to nothing. Left untouched in the body, and
            each becomes a PC001 error until rewritten.
    """

    fragments: list
    number_map: dict
    unresolved_refs: list

def plan_split(sections, level = 3, kind_for_leaf = "recipe"):
    """Assign ids, kinds and parents to the parsed sections.

    Sections at or below `level` become leaf fragments; shallower ones
    become the parents they hang off. The single `#` title is skipped, as
    it names the document rather than a section of it.

    Args:
        sections: Sections from parse_sections. Mutated in place to set
            `slug`, `parent` and `kind`.
        level: Heading depth that becomes a leaf fragment.
        kind_for_leaf: Fragment kind assigned to leaves.

    Returns:
        tuple: (chosen_sections, number_map). Slugs are deduplicated by
        suffixing -- `overview`, `overview-2` -- so two identically titled
        sections do not collide.
    """
    chosen = []
    ancestors = {}
    used = {}

    for section in sections:
        if section.level == 1:
            continue

        base = slugify(section.title)
        slug = base
        counter = 2
        while slug in used:
            slug = f"{base}-{counter}"
            counter += 1
        used[slug] = True
        section.slug = slug

        ancestors[section.level] = slug
        for deeper in [key for key in ancestors if key > section.level]:
            ancestors.pop(deeper, None)

        parent_levels = [key for key in ancestors if key < section.level]
        section.parent = ancestors[max(parent_levels)] if parent_levels else ""

        if section.level >= level:
            section.kind = kind_for_leaf
        elif section.level == 2:
            section.kind = "rule"
        else:
            section.kind = "rule"

        chosen.append(section)

    number_map = {s.number: s.slug for s in chosen if s.number}
    return chosen, number_map

###########################################################
# Reference rewriting
###########################################################
SECTION_REF_PATTERN = re.compile(r"§\s*(\d+)")

def rewrite_refs(body, number_map, section_slug):
    """Turn resolvable `§20` references into `{{ref:id}}`.

    Anything unmapped is reported, never guessed at. A section referring to
    itself becomes the words "this recipe", since a self-reference carries
    no information once the section is its own fragment.

    Args:
        body: Section body.
        number_map: Legacy section number to fragment id.
        section_slug: Slug of the section being rewritten, so a
            self-reference can be recognised.

    Returns:
        tuple: (rewritten_body, unresolved, resolved). `resolved` is the
        set of targets this call created references to -- a reference the
        function just made is a dependency it knows about, so wiring it
        into `requires` is bookkeeping rather than an editorial call.
    """
    unresolved = []
    resolved = []

    def replace(match):
        number = int(match.group(1))
        target = number_map.get(number)
        if target is None:
            unresolved.append((section_slug, match.group(0)))
            return match.group(0)
        if target == section_slug:
            return "this recipe"
        if target not in resolved:
            resolved.append(target)
        return "{{ref:" + target + "}}"

    return SECTION_REF_PATTERN.sub(replace, body), unresolved, resolved

###########################################################
# Emission
###########################################################
def render_fragment(section, requires, contract = ""):
    """Render a section as fragment source.

    `triggers` and `provides` are emitted empty with TODO comments rather
    than guessed at -- routing and vocabulary are editorial calls.

    Args:
        section: Section to render, with slug and kind assigned.
        requires: Fragment ids to declare, parent first.
        contract: Optional contract path.

    Returns:
        str: Complete fragment file content, ending in a newline.
    """
    lines = ["---", f"id: {section.slug}", f"kind: {section.kind}"]
    lines.append(f"title: {yaml_scalar(section.title)}")
    if section.number:
        lines.append(f"legacy_section: {section.number}")
    if requires:
        lines.append("requires: [" + ", ".join(requires) + "]")
    lines.append("triggers: []          # TODO: map detector names onto this recipe")
    lines.append("provides: []          # TODO: terms of art this fragment defines")
    if contract:
        lines.append(f"contract: {contract}")
    lines.append("---")
    lines.append("")
    lines.append(section.body.strip())
    lines.append("")
    return "\n".join(lines)

def yaml_scalar(text):
    """Quote a YAML scalar, but only when it needs it.

    Headings routinely contain colons ("Warning: do not do this"), which
    would otherwise produce frontmatter that does not parse.

    Args:
        text: Scalar value.

    Returns:
        str: The text unchanged when safe, else a double-quoted form with
        backslashes and quotes escaped.
    """
    if re.search(r"[:#\[\]{}&*!|>'\"%@`]|^\s|\s$", text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text

def split_file(path, out_dir, level = 3, kind_for_leaf = "recipe", dry_run = True):
    """Decompose a monolithic prompt into fragment skeletons.

    Args:
        path: The document to split.
        out_dir: Directory to write fragments into.
        level: Heading depth that becomes a leaf fragment.
        kind_for_leaf: Fragment kind assigned to leaves.
        dry_run: When True, nothing is written -- the returned Plan still
            describes exactly what would be. This is the default, because
            splitting overwrites by slug.

    Returns:
        Plan: Describing every fragment, the number map, and every
        reference that could not be resolved.
    """
    with open(path, "r", encoding = "utf-8") as handle:
        text = handle.read()

    sections = parse_sections(text)
    chosen, number_map = plan_split(sections, level, kind_for_leaf)

    written = []
    unresolved = []

    for section in chosen:
        body, missing, resolved = rewrite_refs(section.body, number_map, section.slug)
        unresolved.extend(missing)
        section.body = body

        requires = [section.parent] if section.parent else []
        for target in resolved:
            if target not in requires:
                requires.append(target)
        target = os.path.join(out_dir, f"{section.slug}.md")
        content = render_fragment(section, requires)

        written.append((target, content, section))
        if not dry_run:
            os.makedirs(os.path.dirname(target), exist_ok = True)
            with open(target, "w", encoding = "utf-8") as handle:
                handle.write(content)

    return Plan(
        fragments = written,
        number_map = number_map,
        unresolved_refs = unresolved,
    )
