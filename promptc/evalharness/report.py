"""Aggregation and reporting.

Three outputs matter: the headline pass rate, the per-trigger scorecard
that says which recipe to rewrite next, and the failure taxonomy that says
what kind of fix each failure needs.

The scorecard is the actionable one. A pass rate alone tells you the prompt
is imperfect; a per-recipe breakdown tells you which of fifty recipes to
open first.
"""

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
    """Everything one profile's run over one split produced.

    Attributes:
        profile: Profile name this run used.
        task: Task fragment assembled as the prompt.
        split: `dev`, `test` or `all`.
        items: ItemResult per work item.
        attempts: Attempts allowed per item, i.e. the k in pass@k.
        prompt_tokens: Mean prompt size across items.
        tokenizer: Label from the counter, marked when it estimates.
    """

    profile: str
    task: str
    split: str
    items: list = dataclasses.field(default_factory = list)
    attempts: int = 1
    prompt_tokens: int = 0
    tokenizer: str = ""

    def pass_rate(self):
        """Return pass@k -- the share of items that passed within k tries.

        Returns:
            float: In [0, 1]. Zero for an empty run rather than raising.
        """
        if not self.items:
            return 0.0
        return sum(1 for item in self.items if item.passed()) / len(self.items)

    def pass_at_1(self):
        """Return the share that passed on their first attempt.

        Compared against pass_rate, the gap is what retries are buying --
        which is nearly free locally and is not free through an API.
        """
        if not self.items:
            return 0.0
        first = sum(1 for item in self.items
                    if item.attempts and item.attempts[0].passed())
        return first / len(self.items)

    def mean_attempts_to_green(self):
        """Return the mean attempts needed by the items that passed.

        Failures are excluded: they consumed every attempt by definition,
        and averaging them in would say more about `attempts` than about
        the prompt.
        """
        greens = [item.attempts_to_green() for item in self.items if item.passed()]
        return sum(greens) / len(greens) if greens else 0.0

    ###########################################################
    # Per-trigger scorecard
    ###########################################################
    def scorecard(self):
        """Return the pass rate per routed recipe, worst first.

        An item counts towards every trigger that fired for it, so a
        recipe's score reflects every case it was asked to handle rather
        than only the ones where it was the primary match.

        Returns:
            list: Dicts with trigger, total, passed and pass_rate. Sorted
            by ascending pass rate, then descending volume, so the recipe
            most worth rewriting is first.
        """
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
        """Return a count per outcome bucket, most common first.

        Verifier failures are keyed as `verifier_failed:<id>`, so the
        report names which check rejected the output rather than only that
        something did.

        Returns:
            dict: Outcome to count.
        """
        buckets = {}
        for item in self.items:
            outcome = item.outcome()
            if outcome == score.OUTCOME_VERIFIER and item.failing_verifier():
                outcome = f"{outcome}:{item.failing_verifier()}"
            buckets[outcome] = buckets.get(outcome, 0) + 1
        return dict(sorted(buckets.items(), key = lambda pair: -pair[1]))

    def to_dict(self, include_items = False):
        """Return the run as a JSON-ready mapping.

        Args:
            include_items: Include a row per work item. Off by default,
                since a large corpus makes the summary unreadable.

        Returns:
            dict: Headline figures, taxonomy and scorecard, plus `results`
            when per-item rows are requested.
        """
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
def portability(runs, baseline_profile):
    """Compare each run's pass rate against a baseline profile.

    This is the number that answers "is this prompt optimised for
    open-weight models?" -- and it is scored entirely by external
    verifiers, with no model judging anything.

    Args:
        runs: RunResult objects from the same corpus and split.
        baseline_profile: Profile name forming the denominator.

    Returns:
        list: One row per non-baseline run. Empty when the baseline is
        absent or scored zero, since dividing by a baseline that failed
        everything says nothing.
    """
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
    """Render runs as JSON.

    Args:
        runs: RunResult objects.
        baseline_profile: When given, adds a `portability` block.
        include_items: Include per-item rows.

    Returns:
        str: Indented JSON.
    """
    payload = {
        "runs": [run.to_dict(include_items) for run in runs],
    }
    if baseline_profile:
        payload["portability"] = portability(runs, baseline_profile)
    return json.dumps(payload, indent = 2)

def _bar(rate, width = 18):
    """Render a pass rate as an ASCII bar."""
    filled = int(round(rate * width))
    return "#" * filled + "." * (width - filled)

def render_text(runs, baseline_profile = ""):
    """Render runs for a terminal.

    Args:
        runs: RunResult objects.
        baseline_profile: When given, appends the portability index.

    Returns:
        str: Headline figures, taxonomy, scorecard with bars, and
        portability. Trailing whitespace is stripped.
    """
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
