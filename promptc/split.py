# Mechanical decomposition of a monolithic prompt.
#
# `split` proposes structure and stops. It slices on the heading tree,
# derives ids, wires `requires` to the parent section, and rewrites the
# section-number references it can resolve exactly. It never rewrites prose
# -- that is the authoring model's job, gated by `check`.

# Imports
import dataclasses
import os
import re

# Local imports
from . import fragment as fragment_module

HEADING_PATTERN = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<title>.+?)[ \t]*$", re.M)

# "### 20. Missing cave-block struct memcpy" -> legacy section number 20
NUMBERED_PATTERN = re.compile(r"^(?P<number>\d+)[.)]\s*(?P<rest>.+)$")

###########################################################
# Slugging
###########################################################
def slugify(text, limit = 48):
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
    level: int
    title: str
    body: str
    line: int
    number: int = 0
    slug: str = ""
    parent: str = ""
    kind: str = "recipe"

def parse_sections(text):
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
    fragments: list
    # legacy section number -> fragment id, for reference rewriting
    number_map: dict
    unresolved_refs: list

# Assign ids, kinds and parents. Sections at or below `level` become
# fragments; shallower ones become the parent they hang off.
def plan_split(sections, level = 3, kind_for_leaf = "recipe"):
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

# Rewrite "§20" to an explicit ref when the number maps to a section we
# actually found. Anything unmapped is reported, never guessed at.
#
# Also returns the set of targets it resolved: a reference this function
# created is a dependency this function knows about, so wiring it into
# `requires` is bookkeeping rather than an editorial call.
def rewrite_refs(body, number_map, section_slug):
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

# Quote a YAML scalar only when it needs it.
def yaml_scalar(text):
    if re.search(r"[:#\[\]{}&*!|>'\"%@`]|^\s|\s$", text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text

def split_file(path, out_dir, level = 3, kind_for_leaf = "recipe", dry_run = True):
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
