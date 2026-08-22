# Threshold calibration.
#
# The heuristic rules ship as guesses. This is what turns them into
# measurements, or deletes them.
#
# One eval run already gives many data points: each routed recipe has its
# own measured pass rate in the scorecard, and its own lint feature values.
# Correlating those across recipes says whether a feature predicts anything
# before you ever tune a threshold on it.

# Imports
import json
import math

# Local imports
from .rules import heuristic

###########################################################
# Features
###########################################################
# Each feature is (rule id, extractor). Extractors take a fragment and a
# token counter and return a float, or None when not applicable.
def _hedge_density(item, counter, config):
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
    statements = heuristic.imperatives(item.prose())
    if len(statements) < 4:
        return None
    negative = [s for s in statements if heuristic.NEGATIVE_PATTERN.search(s)]
    return len(negative) / len(statements)

def _instruction_count(item, counter, config):
    return float(len(heuristic.imperatives(item.prose())))

def _grade_level(item, counter, config):
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

# Two-sided significance of r, approximated via a t statistic. Reported so a
# correlation from six recipes is not mistaken for evidence.
def significance(r, n):
    if r is None or n < 4 or abs(r) >= 1.0:
        return None
    t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
    # Normal approximation is adequate for the "is this worth believing" call
    return math.erfc(t / math.sqrt(2))

# Threshold proposal: the feature value above which the mean pass rate falls
# below the overall mean. Deliberately crude -- it is a starting point for a
# human, not an automatic setting.
def propose_threshold(pairs):
    if len(pairs) < 6:
        return None
    ordered = sorted(pairs, key = lambda pair: pair[0])
    overall = sum(rate for _, rate in ordered) / len(ordered)

    best = None
    for index in range(2, len(ordered) - 2):
        cut = ordered[index][0]
        above = [rate for value, rate in ordered if value > cut]
        if len(above) < 2:
            continue
        mean_above = sum(above) / len(above)
        if mean_above < overall:
            gap = overall - mean_above
            if best is None or gap > best[1]:
                best = (cut, gap)
    return best[0] if best else None

###########################################################
# Calibration
###########################################################
def calibrate(config, index, counter, run_payload):
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
    return json.dumps({"findings": findings}, indent = 2)
