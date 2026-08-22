"""Threshold calibration.

The heuristic rules ship as guesses. This is what turns them into
measurements, or deletes them.

One eval run already gives many data points: each routed recipe has its own
measured pass rate in the scorecard, and its own lint feature values.
Correlating those across recipes says whether a feature predicts anything
before you ever tune a threshold on it.

The `inverted` verdict is the one that earns the exercise -- it means a rule
has been firing on the thing that actually helps. `not-predictive` is
grounds for deleting a rule, not for tuning it.
"""

# Imports
import json
import math

# Local imports
from .rules import heuristic

###########################################################
# Features
###########################################################
# Each feature is (rule id, name, extractor). An extractor takes a fragment,
# a token counter and the config, and returns a float -- or None when the
# fragment is too small to measure. Returning None rather than zero is what
# keeps the correlation honest: a fragment with too little text must not
# contribute a data point at all.
def _hedge_density(item, counter, config):
    """Return hedge phrases per 1,000 tokens, or None if too short."""
    text = heuristic.prose_only(item.prose())
    tokens = counter.count(text)
    if tokens < 50:
        return None
    hits = 0
    import re
    for hedge in config.hedges:
        hits += len(re.findall(
            r"(?<![\w-])" + re.escape(hedge) + r"(?![\w-])", text, re.I))
    return hits / (tokens / 1000.0)

def _negation_ratio(item, counter, config):
    """Return prohibitions as a share of instructions, or None if too few."""
    statements = heuristic.imperatives(item.prose())
    if len(statements) < 4:
        return None
    negative = [s for s in statements if heuristic.NEGATIVE_PATTERN.search(s)]
    return len(negative) / len(statements)

def _instruction_count(item, counter, config):
    """Return the number of instruction sentences in the fragment."""
    return float(len(heuristic.imperatives(item.prose())))

def _grade_level(item, counter, config):
    """Return the Flesch-Kincaid grade, or None if unmeasurable.

    Returns None when textstat is absent, so an optional dependency never
    turns into a missing data point that looks like a zero.
    """
    try:
        import textstat
    except ImportError:
        return None
    text = heuristic.prose_only(item.prose()).strip()
    if len(text) < 200:
        return None
    try:
        return float(textstat.flesch_kincaid_grade(text))
    except Exception:
        return None

def _token_size(item, counter, config):
    """Return the fragment's size in tokens.

    Carries no rule id: it is a control. If size alone predicts pass rate
    as well as a rule's own feature does, that rule is measuring length
    with extra steps.
    """
    return float(counter.count(item.body))

FEATURES = [
    ("PC100", "hedge_density", _hedge_density),
    ("PC101", "negation_ratio", _negation_ratio),
    ("PC102", "instruction_count", _instruction_count),
    ("PC103", "grade_level", _grade_level),
    (None, "token_size", _token_size),
]

###########################################################
# Statistics
###########################################################
def pearson(xs, ys):
    """Return the Pearson correlation between two series.

    Args:
        xs: Feature values.
        ys: Matching pass rates.

    Returns:
        float: In [-1, 1], or None when there are fewer than three points
        or either series has no variance -- both cases where a correlation
        would be meaningless rather than merely weak.
    """
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    if denominator == 0:
        return None
    return numerator / denominator

def significance(r, n):
    """Approximate the two-sided p-value for a correlation.

    Reported so that a correlation drawn from six recipes is not mistaken
    for evidence. A normal approximation is adequate for the only question
    being asked -- is this worth believing.

    Args:
        r: Correlation coefficient.
        n: Number of points.

    Returns:
        float: Approximate p-value, or None when r is None, n is below
        four, or the correlation is perfect.
    """
    if r is None or n < 4 or abs(r) >= 1.0:
        return None
    t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
    # Normal approximation is adequate for the "is this worth believing" call
    return math.erfc(t / math.sqrt(2))

def propose_threshold(pairs):
    """Find the feature value where pass rate falls off hardest.

    The split maximises the separation between the two sides,
    (mean below - mean above), rather than the drop against the overall
    mean. Those sound equivalent and are not: because the worst items sit
    at the top, a gap measured against the overall mean keeps widening as
    the cut moves right, so it always reports the extreme instead of the
    cliff.

    Deliberately crude. The output is a recommendation to a human, never an
    automatic setting -- which is exactly why a subtly wrong one would be
    worse than none.

    Args:
        pairs: (feature_value, pass_rate) tuples.

    Returns:
        The proposed threshold, or None when there are fewer than six
        points or no cut separates the sides at all.
    """
    if len(pairs) < 6:
        return None
    ordered = sorted(pairs, key = lambda pair: pair[0])

    best = None
    for index in range(2, len(ordered) - 2):
        cut = ordered[index][0]
        below = [rate for value, rate in ordered if value <= cut]
        above = [rate for value, rate in ordered if value > cut]
        if len(below) < 2 or len(above) < 2:
            continue

        separation = (sum(below) / len(below)) - (sum(above) / len(above))
        if separation <= 0:
            continue
        if best is None or separation > best[1]:
            best = (cut, separation)

    return best[0] if best else None

###########################################################
# Calibration
###########################################################
def calibrate(config, index, counter, run_payload):
    """Test whether each heuristic feature predicts measured pass rate.

    Each routed recipe contributes one data point: its feature value
    against the pass rate its trigger achieved. Triggers with fewer than
    three observations are dropped, since a rate from two items says
    nothing.

    Args:
        config: Loaded Config, for hedge lists and current thresholds.
        index: Built Index, for mapping a trigger back to its recipe.
        counter: Counter used by the size-sensitive extractors.
        run_payload: Parsed eval result JSON. Scorecards from several runs
            are merged by weighted total.

    Returns:
        list: One finding per feature, with `r`, `p`, `n` and a verdict of
        predictive, inverted, not-predictive, weak, no-variance or
        insufficient-data. A proposed threshold is included only for a
        predictive feature that maps to a rule.
    """
    scorecard = []
    for run in run_payload.get("runs", []):
        scorecard.extend(run.get("scorecard", []))

    # trigger -> pass rate, merged across runs by weighted mean
    rates = {}
    for row in scorecard:
        entry = rates.setdefault(row["trigger"], {"passed": 0, "total": 0})
        entry["passed"] += row["passed"]
        entry["total"] += row["total"]

    # Map each trigger onto the recipe that serves it
    samples = []
    for trigger, entry in rates.items():
        if entry["total"] < 3:
            continue
        matches = index.by_trigger.get(trigger)
        if not matches:
            continue
        samples.append((matches[0], entry["passed"] / entry["total"], entry["total"]))

    findings = []
    for rule_id, name, extractor in FEATURES:
        pairs = []
        for fragment, rate, _ in samples:
            value = extractor(fragment, counter, config)
            if value is None:
                continue
            pairs.append((value, rate))

        if len(pairs) < 3:
            findings.append({
                "rule": rule_id, "feature": name, "n": len(pairs),
                "verdict": "insufficient-data",
            })
            continue

        xs = [value for value, _ in pairs]
        ys = [rate for _, rate in pairs]
        r = pearson(xs, ys)
        p = significance(r, len(pairs))

        if r is None:
            verdict = "no-variance"
        elif p is not None and p > 0.10:
            verdict = "not-predictive"
        elif r < -0.3:
            verdict = "predictive"
        elif r > 0.3:
            verdict = "inverted"
        else:
            verdict = "weak"

        finding = {
            "rule": rule_id,
            "feature": name,
            "n": len(pairs),
            "r": round(r, 3) if r is not None else None,
            "p": round(p, 4) if p is not None else None,
            "verdict": verdict,
        }
        if rule_id and verdict == "predictive":
            proposal = propose_threshold(pairs)
            if proposal is not None:
                finding["current_threshold"] = config.threshold(rule_id)
                finding["proposed_threshold"] = round(proposal, 3)
        findings.append(finding)

    return findings

###########################################################
# Rendering
###########################################################
VERDICT_NOTE = {
    "predictive": "higher values track lower pass rates — keep the rule",
    "inverted": "higher values track HIGHER pass rates — the rule is backwards",
    "not-predictive": "no measurable relationship — demote to info or delete",
    "weak": "relationship too weak to act on — gather more data",
    "no-variance": "every fragment scores the same — the feature is inert here",
    "insufficient-data": "too few routed recipes to say anything",
}

def render_text(findings):
    """Render calibration findings for a terminal.

    Each verdict is followed by what it means for the rule, and the closing
    note says plainly that proposals are starting points -- the numbers
    read as more authoritative than they are.

    Args:
        findings: Findings from calibrate.

    Returns:
        str: A table, per-verdict guidance, and the caveat.
    """
    lines = ["feature                r        p       n    verdict", ""]
    for finding in findings:
        r = f"{finding['r']:+.3f}" if finding.get("r") is not None else "   -  "
        p = f"{finding['p']:.3f}" if finding.get("p") is not None else "  -  "
        lines.append(f"{finding['feature']:<20} {r}   {p}  {finding['n']:>3}    "
                     f"{finding['verdict']}")
        note = VERDICT_NOTE.get(finding["verdict"], "")
        if note:
            lines.append(f"                     {note}")
        if "proposed_threshold" in finding:
            current = finding.get("current_threshold")
            lines.append(f"                     {finding['rule']}: "
                         f"{current} -> {finding['proposed_threshold']} (proposed)")
        lines.append("")

    lines.append("Proposals are starting points, not settings. Apply one at a time and")
    lines.append("re-run eval on the held-out split to confirm the change is real.")
    return "\n".join(lines)

def render_json(findings):
    """Render calibration findings as indented JSON."""
    return json.dumps({"findings": findings}, indent = 2)
