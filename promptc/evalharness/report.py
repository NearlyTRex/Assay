# Aggregation and reporting.
#
# Three outputs matter: the headline pass rate, the per-trigger scorecard
# that says which recipe to rewrite next, and the failure taxonomy that
# says what kind of fix each failure needs.

# Imports
import dataclasses
import json

# Local imports
from . import score

###########################################################
# Run result
###########################################################
@dataclasses.dataclass
class RunResult:
    profile: str
    task: str
    split: str
    items: list = dataclasses.field(default_factory = list)
    attempts: int = 1
    prompt_tokens: int = 0
    tokenizer: str = ""

    def pass_rate(self):
        if not self.items:
            return 0.0
        return sum(1 for item in self.items if item.passed()) / len(self.items)

    # pass@1 uses only the first attempt of each item
    def pass_at_1(self):
        if not self.items:
            return 0.0
        first = sum(1 for item in self.items
                    if item.attempts and item.attempts[0].passed())
        return first / len(self.items)

    def mean_attempts_to_green(self):
        greens = [item.attempts_to_green() for item in self.items if item.passed()]
        return sum(greens) / len(greens) if greens else 0.0

    ###########################################################
    # Per-trigger scorecard
    ###########################################################
    # An item counts towards every trigger that fired for it, so a recipe's
    # score reflects every case it was asked to handle.
    def scorecard(self):
        buckets = {}
        for item in self.items:
            keys = item.triggers or ["<none>"]
            for key in keys:
                entry = buckets.setdefault(key, {"total": 0, "passed": 0})
                entry["total"] += 1
                if item.passed():
                    entry["passed"] += 1

        rows = []
        for trigger, entry in sorted(buckets.items()):
            rate = entry["passed"] / entry["total"] if entry["total"] else 0.0
            rows.append({
                "trigger": trigger,
                "total": entry["total"],
                "passed": entry["passed"],
                "pass_rate": round(rate, 4),
            })
        rows.sort(key = lambda row: (row["pass_rate"], -row["total"]))
        return rows

    ###########################################################
    # Failure taxonomy
    ###########################################################
    def taxonomy(self):
        buckets = {}
        for item in self.items:
            outcome = item.outcome()
            if outcome == score.OUTCOME_VERIFIER and item.failing_verifier():
                outcome = f"{outcome}:{item.failing_verifier()}"
            buckets[outcome] = buckets.get(outcome, 0) + 1
        return dict(sorted(buckets.items(), key = lambda pair: -pair[1]))

    def to_dict(self, include_items = False):
        payload = {
            "profile": self.profile,
            "task": self.task,
            "split": self.split,
            "items": len(self.items),
            "attempts": self.attempts,
            "prompt_tokens": self.prompt_tokens,
            "tokenizer": self.tokenizer,
            "pass_at_1": round(self.pass_at_1(), 4),
            "pass_at_k": round(self.pass_rate(), 4),
            "mean_attempts_to_green": round(self.mean_attempts_to_green(), 2),
            "taxonomy": self.taxonomy(),
            "scorecard": self.scorecard(),
        }
        if include_items:
            payload["results"] = [
                {
                    "stem": item.stem,
                    "triggers": item.triggers,
                    "passed": item.passed(),
                    "attempts_to_green": item.attempts_to_green(),
                    "outcome": item.outcome(),
                    "failing_verifier": item.failing_verifier(),
                    "similarity": round(
                        max((a.similarity for a in item.attempts), default = 0.0), 3),
                }
                for item in self.items
            ]
        return payload

###########################################################
# Portability
###########################################################
# The number that answers "is this prompt optimised for open weights?".
# Scored entirely by external verifiers -- no model judges anything.
def portability(runs, baseline_profile):
    baseline = next((run for run in runs if run.profile == baseline_profile), None)
    if baseline is None or baseline.pass_rate() == 0:
        return []

    rows = []
    for run in runs:
        if run.profile == baseline_profile:
            continue
        rows.append({
            "profile": run.profile,
            "pass_at_k": round(run.pass_rate(), 4),
            "baseline": baseline_profile,
            "baseline_pass_at_k": round(baseline.pass_rate(), 4),
            "portability_index": round(run.pass_rate() / baseline.pass_rate(), 3),
        })
    return rows

###########################################################
# Rendering
###########################################################
def render_json(runs, baseline_profile = "", include_items = False):
    payload = {
        "runs": [run.to_dict(include_items) for run in runs],
    }
    if baseline_profile:
        payload["portability"] = portability(runs, baseline_profile)
    return json.dumps(payload, indent = 2)

def _bar(rate, width = 18):
    filled = int(round(rate * width))
    return "#" * filled + "." * (width - filled)

def render_text(runs, baseline_profile = ""):
    lines = []
    for run in runs:
        lines.append(f"profile {run.profile}   task {run.task}   split {run.split}")
        lines.append(f"  items {len(run.items)}   attempts/item {run.attempts}"
                     f"   prompt {run.prompt_tokens:,} tok ({run.tokenizer})")
        lines.append(f"  pass@1 {run.pass_at_1():.1%}    "
                     f"pass@{run.attempts} {run.pass_rate():.1%}    "
                     f"mean attempts to green {run.mean_attempts_to_green():.2f}")
        lines.append("")

        lines.append("  failure taxonomy")
        for outcome, count in run.taxonomy().items():
            lines.append(f"    {count:>5}  {outcome}")
        lines.append("")

        rows = run.scorecard()
        if rows:
            lines.append("  per-trigger scorecard (worst first)")
            width = max(len(row["trigger"]) for row in rows)
            for row in rows:
                lines.append(
                    f"    {row['trigger']:<{width}}  {_bar(row['pass_rate'])}  "
                    f"{row['pass_rate']:>6.1%}  ({row['passed']}/{row['total']})")
            lines.append("")

    if baseline_profile:
        rows = portability(runs, baseline_profile)
        if rows:
            lines.append(f"  portability index (vs {baseline_profile})")
            for row in rows:
                lines.append(f"    {row['profile']:<16} {row['portability_index']:>6.3f}"
                             f"   ({row['pass_at_k']:.1%} / {row['baseline_pass_at_k']:.1%})")
            lines.append("")

    return "\n".join(lines).rstrip()
