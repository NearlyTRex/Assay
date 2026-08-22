# Rule catalogue.
#
# Every rule has a stable id, a rationale and a remedy, so `promptc explain`
# can answer an agent's question without the docs being in context.
#
# The split matters: ERROR rules are decidable facts about the source tree
# or about an external program's exit code. WARN rules are heuristics, and
# every heuristic marked `calibrated` is a placeholder until `promptc
# calibrate` measures whether it predicts pass rate.

# Imports
import dataclasses

# Local imports
from ..diagnostics import Severity

###########################################################
# Rule metadata
###########################################################
@dataclasses.dataclass
class Rule:
    id: str
    name: str
    severity: Severity
    summary: str
    rationale: str
    remedy: str
    # True when the threshold is a guess until eval data exists
    calibrated: bool = False

CATALOGUE = {}

def register(rule):
    CATALOGUE[rule.id] = rule
    return rule

def get(rule_id):
    return CATALOGUE.get(rule_id.upper())

def all_rules():
    return [CATALOGUE[key] for key in sorted(CATALOGUE)]

###########################################################
# Structural rules -- decidable
###########################################################
register(Rule(
    "PC000", "parse-error", Severity.ERROR,
    "Fragment could not be parsed.",
    "A fragment that does not parse cannot be assembled or checked, so every "
    "other guarantee is void for it.",
    "Fix the frontmatter. `promptc new <kind> <id>` emits a valid skeleton.",
))

register(Rule(
    "PC001", "dangling-reference", Severity.ERROR,
    "A reference does not resolve.",
    "Fragments are assembled in different combinations per task, so a prose "
    "reference like 'see above' or a section number points at nothing in most "
    "assemblies. This is the single most common breakage when a monolithic "
    "prompt is split, and it is silent -- the model reads an instruction to "
    "consult something it cannot see, and improvises.",
    "Use `{{ref:fragment-id}}` and add that id to `requires`, or inline the "
    "fact directly. Prose references are never checkable and are always errors.",
))

register(Rule(
    "PC002", "unresolved-require", Severity.ERROR,
    "A `requires` entry names no known fragment.",
    "A missing dependency means the assembled prompt is short a piece it was "
    "written to assume.",
    "Correct the id, or create the fragment with `promptc new`.",
))

register(Rule(
    "PC003", "circular-require", Severity.ERROR,
    "Fragments depend on each other in a cycle.",
    "A cycle has no valid assembly order, and usually means two fragments are "
    "really one concept, or a shared part wants extracting.",
    "Extract the shared portion into its own fragment that both require.",
))

register(Rule(
    "PC004", "token-budget-exceeded", Severity.ERROR,
    "The assembled prompt does not fit the target model.",
    "Exceeding the window is not a soft failure. The runtime silently truncates "
    "or errors, and truncation removes whichever end of your prompt the runtime "
    "chose -- often the output contract.",
    "Route fewer fragments, shrink the largest ones, or raise the profile's "
    "`context`. `promptc build --explain` shows the token cost per fragment.",
))

register(Rule(
    "PC005", "missing-output-contract", Severity.ERROR,
    "A task declares no output contract.",
    "Without a grammar or schema the prompt cannot fail closed: malformed output "
    "reaches your pipeline and has to be detected later, by something else.",
    "Add `contract: contracts/<name>.gbnf` (or `.json` for a JSON Schema).",
))

register(Rule(
    "PC006", "example-verification-failed", Severity.ERROR,
    "An example block failed its external verifier.",
    "A worked example that no longer compiles is worse than no example -- it "
    "teaches a pattern the toolchain rejects, and small models copy examples "
    "far more literally than they follow prose.",
    "Fix the example, or update the verifier if the toolchain moved.",
))

register(Rule(
    "PC007", "undefined-glossary-term", Severity.ERROR,
    "A fragment uses a term it cannot see defined.",
    "Project vocabulary that is defined in a fragment the assembly does not "
    "include leaves the model guessing at a term of art.",
    "Add the providing fragment to `requires`, or define the term where it is used.",
))

register(Rule(
    "PC008", "duplicate-fragment-id", Severity.ERROR,
    "Two fragments share an id.",
    "Ids are the addressing scheme for `requires` and `{{ref:}}`. A duplicate "
    "makes resolution arbitrary.",
    "Rename one of them.",
))

register(Rule(
    "PC009", "trigger-collision", Severity.ERROR,
    "One trigger routes to several fragments at equal priority.",
    "Routing must be a dictionary lookup with a single answer. A tie means the "
    "selection depends on file order, which is not a decision anyone made.",
    "Give one fragment a higher `priority:`, or narrow the trigger sets.",
))

register(Rule(
    "PC010", "orphan-fragment", Severity.WARN,
    "A fragment is unreachable from any task.",
    "Unreachable fragments are dead weight that still gets maintained, and they "
    "often mark a routing rule someone forgot to add.",
    "Add a trigger, add it to a task's `requires`, or delete it.",
))

register(Rule(
    "PC011", "suppression-without-justification", Severity.ERROR,
    "A suppression comment gives no reason.",
    "A gate an agent loops against is a gate an agent will learn to satisfy "
    "cheaply. Requiring a written reason keeps every silenced rule reviewable.",
    "Write `<!-- promptc-disable PC100: why, and what evidence -->`.",
))

register(Rule(
    "PC012", "unused-suppression", Severity.WARN,
    "A suppression matches no diagnostic.",
    "A stale suppression hides the fact that the underlying problem was fixed, "
    "and will silently mask the rule if it recurs.",
    "Delete the comment.",
))

register(Rule(
    "PC013", "missing-contract-file", Severity.ERROR,
    "A declared contract file does not exist.",
    "A contract path that does not resolve cannot constrain generation, so the "
    "prompt only appears to fail closed.",
    "Create the grammar or schema, or correct the path.",
))

register(Rule(
    "PC014", "tokenizer-unavailable", Severity.WARN,
    "The target model's tokenizer could not be loaded.",
    "PC004 is only meaningful against the real tokenizer. Estimating silently "
    "would leave the budget check appearing to pass while measuring the wrong "
    "thing, so the fallback announces itself.",
    "Install the tokenizer package, start llama-server, or set `tokenizer: chars` "
    "to accept estimation deliberately.",
))

###########################################################
# Heuristic rules -- must earn their thresholds
###########################################################
register(Rule(
    "PC100", "hedge-density", Severity.WARN,
    "Too many hedging phrases.",
    "Hedges ask the reader to infer intent. Large models resolve them from "
    "context; smaller open-weight models tend to pick a reading at random, and "
    "the failure is silent because the output still looks confident.",
    "Replace 'prefer X where appropriate' with an explicit condition and action.",
    calibrated = True,
))

register(Rule(
    "PC101", "negation-density", Severity.WARN,
    "Too many instructions phrased as prohibitions.",
    "Positive instructions transfer better than negative ones. 'Never do X' "
    "leaves the space of acceptable actions undefined.",
    "State what to do instead of only what to avoid.",
    calibrated = True,
))

register(Rule(
    "PC102", "instruction-count", Severity.WARN,
    "A fragment carries too many separate instructions.",
    "Instruction-following degrades with count well before it degrades with "
    "length, and the instructions lost are usually the middle ones.",
    "Split the fragment, or move conditional branches into their own recipes.",
    calibrated = True,
))

register(Rule(
    "PC103", "sentence-complexity", Severity.WARN,
    "Sentences are long or heavily subordinated.",
    "Multi-clause conditionals are where small models drop a qualifier and "
    "apply a rule in a case it was scoped out of.",
    "Break into numbered steps, one action per step.",
    calibrated = True,
))

register(Rule(
    "PC104", "vocabulary-drift", Severity.WARN,
    "A concept is named several different ways.",
    "Synonyms for a term of art force the model to decide whether two names "
    "mean the same thing. It sometimes decides they do not.",
    "Use the canonical term declared in `vocabulary:` throughout.",
))

register(Rule(
    "PC105", "critical-rule-buried", Severity.WARN,
    "MUST/NEVER rules sit in the middle of a long assembly.",
    "Attention to the middle of a long context is measurably weaker than to "
    "either end, and hard constraints are exactly what you cannot afford to lose.",
    "Move hard constraints into a fragment that sorts to the front or back.",
    calibrated = True,
))
