# Eval orchestration.
#
# The one part of the toolset that runs a model -- and even here the model
# is the subject, never the judge. Pass and fail come from the verifier
# commands in promptc.yaml.

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
# Render one work item's input files into the payload appended to the
# assembled instructions.
def render_payload(config, item, root):
    parts = []
    for relative, text in item.read_inputs(root):
        language = os.path.splitext(relative)[1].lstrip(".")
        parts.append(f"### {relative}\n\n```{language}\n{text.rstrip()}\n```")
    return config.eval.payload_header + "\n\n".join(parts) + "\n"

###########################################################
# Run
###########################################################
class EvalError(Exception):
    pass

def run_eval(config, profile_name, limit = 0, per_group = 0, split = "dev",
             attempts = 0, progress = None):
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

    corpus_module.annotate_triggers(config, items, root)

    dev, test = corpus_module.holdout(items, config.corpus.holdout, config.corpus.seed)
    pool = {"dev": dev, "test": test, "all": items}.get(split)
    if pool is None:
        raise EvalError("`split` must be one of dev, test, all.")

    if per_group:
        pool = corpus_module.sample(pool, per_group, config.corpus.seed,
                                    config.corpus.stratify_by)
    if limit:
        pool = pool[:limit]

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
# Only GBNF is passed to the backend; a JSON Schema contract is validated
# by a verifier instead, since not every backend can enforce one.
def _load_grammar(config, task):
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
