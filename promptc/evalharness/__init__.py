"""Eval orchestration.

The one part of the toolset that runs a model -- and even here the model is
the subject, never the judge. Pass and fail come from the verifier commands
in promptc.yaml.

Two properties are load-bearing. Each item's prompt is assembled from *its
own* triggers, so a recipe is measured only on the cases it was routed for.
And the golden answer is read but never rendered into a prompt: if it
leaked, every pass rate the tool has ever reported would be meaningless,
which is why a test asserts on the captured prompt directly.
"""

# Imports
import os
import time

# Local imports
from .. import assemble as assemble_module
from .. import fragment as fragment_module
from .. import index as index_module
from .. import tokens as tokens_module
from . import corpus as corpus_module
from . import report as report_module
from . import runner as runner_module
from . import score as score_module

###########################################################
# Prompt construction
###########################################################
def render_payload(config, item, root):
    """Render one work item's input files into the prompt payload.

    Each input becomes a headed, fenced block so the model can tell the
    files apart. The golden answer is deliberately not among them.

    Args:
        config: Loaded Config, supplying `eval.payload_header`.
        item: The work Item.
        root: Absolute corpus root.

    Returns:
        str: The header followed by one block per existing input file.
    """
    parts = []
    for relative, text in item.read_inputs(root):
        language = os.path.splitext(relative)[1].lstrip(".")
        parts.append(f"### {relative}\n\n```{language}\n{text.rstrip()}\n```")
    return config.eval.payload_header + "\n\n".join(parts) + "\n"

###########################################################
# Run
###########################################################
class EvalError(Exception):
    """The evaluation cannot start.

    Raised only for faults that make the whole run meaningless -- no task,
    no verifier, an empty corpus. Anything that goes wrong for a single
    item becomes a taxonomy bucket instead.
    """

def run_eval(config, profile_name, limit = 0, per_group = 0, split = "dev",
             attempts = 0, progress = None):
    """Run a model over the corpus and score it with external verifiers.

    Each item is assembled with its own triggers, generated up to `attempts`
    times with a fixed seed per attempt, and stopped at the first success.

    Args:
        config: Loaded Config.
        profile_name: Profile naming the model and backend.
        limit: Cap the item count after sampling. Zero means no cap.
        per_group: Sample at most this many items per stratum. Zero takes
            everything.
        split: `dev` to tune on, `test` to report from, `all` for one-off
            inspection.
        attempts: Override `eval.attempts`. Zero uses the configured value.
        progress: Optional callable(position, total, item_result), invoked
            after each item.

    Returns:
        RunResult: Carrying per-item outcomes, the scorecard and the
        taxonomy.

    Raises:
        EvalError: Unknown profile or split, `eval.task` unset or missing
            from the library, `eval.verifiers` empty, the library failing
            to parse, or the corpus glob matching nothing.
    """
    profile = config.profile(profile_name)
    if profile is None:
        known = ", ".join(sorted(config.profiles)) or "none defined"
        raise EvalError(f"Unknown profile `{profile_name}`. Known: {known}.")

    settings = config.eval
    if not settings.task:
        raise EvalError("promptc.yaml: `eval.task` is not set — nothing to assemble.")
    if not settings.verifiers:
        raise EvalError(
            "promptc.yaml: `eval.verifiers` is empty.\n"
            "Without an external verifier there is nothing scoring the output, "
            "which is the entire point of the harness.")

    fragments, parse_errors = fragment_module.load_library(config.library_path())
    if parse_errors:
        raise EvalError(
            f"{len(parse_errors)} fragment(s) failed to parse. Run `promptc check` first.")

    index = index_module.Index(fragments)
    if index.get(settings.task) is None:
        raise EvalError(f"Task `{settings.task}` not found in {config.library}.")

    items, root = corpus_module.discover(config, limit = 0)
    if not items:
        raise EvalError(f"Corpus glob matched nothing under {root}.")

    # Detection can take a while on a first run, so say what is happening
    # rather than appearing to hang.
    def detect_progress(position, total, item):
        if progress and (position == 1 or position % 25 == 0 or position == total):
            progress(position, total, None)

    # Split before detecting. Detection runs the project's own analysis per
    # item and is by far the most expensive step, so it must not be paid for
    # items that were never going to be evaluated.
    dev, test = corpus_module.holdout(items, config.corpus.holdout, config.corpus.seed)
    pool = {"dev": dev, "test": test, "all": items}.get(split)
    if pool is None:
        raise EvalError("`split` must be one of dev, test, all.")

    if per_group:
        # Stratifying needs every candidate's triggers, so detection cannot
        # be narrowed here. A plain --limit is applied first to bound it.
        if limit:
            pool = pool[:limit]
        corpus_module.annotate_triggers(config, pool, root, progress = detect_progress)
        pool = corpus_module.sample(pool, per_group, config.corpus.seed,
                                    config.corpus.stratify_by)
    else:
        if limit:
            pool = pool[:limit]
        corpus_module.annotate_triggers(config, pool, root, progress = detect_progress)

    backend = runner_module.make_backend(profile, profile.raw, cwd = config.root)

    try:
        counter = tokens_module.counter(profile.tokenizer)
    except tokens_module.TokenizerUnavailable:
        counter = tokens_module.counter("chars")

    grammar = _load_grammar(config, index.get(settings.task))
    attempt_count = attempts or settings.attempts
    seeds = settings.seeds[:attempt_count]

    results = []
    prompt_tokens_total = 0

    for position, item in enumerate(pool, start = 1):
        assembly = assemble_module.assemble(index, settings.task, item.triggers)
        prompt = assembly.text + render_payload(config, item, root)
        prompt_tokens_total += counter.count(prompt)
        golden = item.read_golden(root)

        item_result = score_module.ItemResult(stem = item.stem, triggers = item.triggers)

        for seed in seeds:
            sampling = runner_module.Sampling(
                temperature = settings.temperature,
                seed = seed,
                max_tokens = settings.max_tokens,
                grammar = grammar,
            )
            started = time.monotonic()
            generation = backend.generate(prompt, sampling)
            generation.elapsed = time.monotonic() - started

            attempt = score_module.score_generation(config, generation, golden, seed)
            item_result.attempts.append(attempt)
            if attempt.passed():
                break

        results.append(item_result)
        if progress:
            progress(position, len(pool), item_result)

    return report_module.RunResult(
        profile = profile_name,
        task = settings.task,
        split = split,
        items = results,
        attempts = attempt_count,
        prompt_tokens = int(prompt_tokens_total / len(pool)) if pool else 0,
        tokenizer = counter.describe(),
    )

###########################################################
# Grammar
###########################################################
def _load_grammar(config, task):
    """Load a task's GBNF grammar, if it has one.

    Only GBNF is passed to the backend. A JSON Schema contract is validated
    by a verifier instead, since not every backend can enforce one.

    Args:
        config: Loaded Config, for resolving the contract path.
        task: The task Fragment.

    Returns:
        str: The grammar text, or empty when the task has no contract, the
        contract is not GBNF, or the file is absent. A missing file is
        PC013's problem, so this stays quiet.
    """
    if not task or not task.contract:
        return ""
    if not task.contract.endswith(".gbnf"):
        return ""
    path = task.contract
    if not os.path.isabs(path):
        path = os.path.join(config.root, path)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding = "utf-8") as handle:
        return handle.read()
