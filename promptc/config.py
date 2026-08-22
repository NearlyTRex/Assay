# Project configuration (promptc.yaml).
#
# This file is the entire domain boundary. The toolset knows how to run a
# command you gave it and read an exit code; everything it knows about C++,
# Ghidra, Python or anything else arrives through here.

# Imports
import dataclasses
import os

# Third party
import yaml

###########################################################
# Defaults for calibrated warnings
###########################################################
# Every one of these is a placeholder until `promptc calibrate` measures it
# against real pass rates. They are deliberately loose so an uncalibrated
# install does not drown an author in noise.
DEFAULT_THRESHOLDS = {
    "PC100": 6.0,    # hedge words per 1k tokens
    "PC101": 0.45,   # negative imperatives as a fraction of all imperatives
    "PC102": 30,     # imperative statements per fragment
    "PC103": 14.0,   # textstat grade level
    "PC105": 0.20,   # fraction of MUST/NEVER rules in the middle of a bundle
}

# Words that make a model infer intent rather than follow an instruction.
DEFAULT_HEDGES = [
    "if appropriate", "where appropriate", "when appropriate",
    "use judgement", "use judgment", "use your judgement", "use your judgment",
    "as needed", "if needed", "if necessary", "where possible", "if possible",
    "generally", "typically", "usually", "often", "sometimes", "may want to",
    "consider", "prefer", "preferably", "ideally", "reasonable", "reasonably",
    "appropriate", "sensible", "as applicable", "etc",
]

###########################################################
# Verifier
###########################################################
@dataclasses.dataclass
class Verifier:
    id: str
    command: list
    match: str = ""
    timeout: int = 120
    # Extension used when writing an extracted block to a temp file
    suffix: str = ""

###########################################################
# Profile
###########################################################
@dataclasses.dataclass
class Profile:
    name: str
    context: int = 32768
    tokenizer: str = "chars"
    # Tokens held back for the runtime payload (the work item)
    reserve: int = 0
    # Tokens held back for the model's own output
    output_reserve: int = 2048
    endpoint: str = ""
    model: str = ""
    # Backend selection and any backend-specific keys, passed through verbatim
    raw: dict = dataclasses.field(default_factory = dict)

    def budget(self):
        return self.context - self.reserve - self.output_reserve

###########################################################
# Corpus
###########################################################
@dataclasses.dataclass
class Corpus:
    root: str = ""
    # Glob that discovers golden files; each match defines one item
    discover: str = ""
    # Suffix stripped from a golden path to derive the item stem
    golden_suffix: str = ""
    # Input files shown to the model, as {stem}-templated paths
    inputs: list = dataclasses.field(default_factory = list)
    # Command emitting one trigger name per line for an item
    triggers_command: list = dataclasses.field(default_factory = list)
    stratify_by: str = "triggers"
    holdout: float = 0.2
    seed: int = 20260822

###########################################################
# Config
###########################################################
@dataclasses.dataclass
class EvalSettings:
    # Task fragment used as the prompt entry point
    task: str = ""
    # Verifier ids run against model output, in order; first failure wins
    verifiers: list = dataclasses.field(default_factory = list)
    # "fence" takes the first fenced block; "raw" uses the output as-is
    extract: str = "fence"
    # Suffix for the temp file handed to verifiers
    suffix: str = ".txt"
    # Attempts per item; pass@k is computed over these
    attempts: int = 1
    seeds: list = dataclasses.field(default_factory = list)
    temperature: float = 0.2
    max_tokens: int = 4096
    # Profile whose pass rate is the denominator of the portability index
    baseline_profile: str = ""
    # How the work item is rendered into the prompt
    payload_header: str = "\n\n## Work item\n\n"

@dataclasses.dataclass
class Config:
    root: str
    library: str = "promptlib"
    contracts: str = "contracts"
    verifiers: list = dataclasses.field(default_factory = list)
    eval: "EvalSettings" = dataclasses.field(default_factory = lambda: EvalSettings())
    profiles: dict = dataclasses.field(default_factory = dict)
    corpus: Corpus = dataclasses.field(default_factory = Corpus)
    thresholds: dict = dataclasses.field(default_factory = dict)
    hedges: list = dataclasses.field(default_factory = list)
    # canonical term -> [banned synonyms], drives PC104
    vocabulary: dict = dataclasses.field(default_factory = dict)

    def library_path(self):
        return os.path.join(self.root, self.library)

    def contracts_path(self):
        return os.path.join(self.root, self.contracts)

    def threshold(self, rule):
        return self.thresholds.get(rule, DEFAULT_THRESHOLDS.get(rule))

    def profile(self, name):
        return self.profiles.get(name)

    def verifier(self, verifier_id):
        for verifier in self.verifiers:
            if verifier.id == verifier_id:
                return verifier
        return None

###########################################################
# Loading
###########################################################
class ConfigError(Exception):
    pass

CONFIG_NAMES = ("promptc.yaml", "promptc.yml")

# Walk upward from `start` looking for a project config.
def find_config(start = "."):
    current = os.path.abspath(start)
    while True:
        for name in CONFIG_NAMES:
            candidate = os.path.join(current, name)
            if os.path.exists(candidate):
                return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent

def _parse_verifiers(raw, path):
    verifiers = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: each entry under `verifiers` must be a mapping.")
        if "id" not in entry:
            raise ConfigError(f"{path}: a verifier is missing `id`.")
        command = entry.get("command")
        if not isinstance(command, list) or not command:
            raise ConfigError(
                f"{path}: verifier `{entry['id']}` needs `command` as a non-empty list "
                f"(argv form, e.g. [\"./build.sh\", \"{{file}}\"]).")
        verifiers.append(Verifier(
            id = str(entry["id"]),
            command = [str(part) for part in command],
            match = str(entry.get("match", "")),
            timeout = int(entry.get("timeout", 120)),
            suffix = str(entry.get("suffix", "")),
        ))
    return verifiers

def _parse_profiles(raw, path):
    profiles = {}
    for name, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: profile `{name}` must be a mapping.")
        profiles[str(name)] = Profile(
            name = str(name),
            context = int(entry.get("context", 32768)),
            tokenizer = str(entry.get("tokenizer", "chars")),
            reserve = int(entry.get("reserve", 0)),
            output_reserve = int(entry.get("output_reserve", 2048)),
            endpoint = str(entry.get("endpoint", "")),
            model = str(entry.get("model", "")),
            raw = dict(entry),
        )
    return profiles

def _parse_corpus(raw, path):
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: `corpus` must be a mapping.")
    triggers = raw.get("triggers_command") or []
    if triggers and not isinstance(triggers, list):
        raise ConfigError(f"{path}: `corpus.triggers_command` must be a list (argv form).")
    return Corpus(
        root = str(raw.get("root", "")),
        discover = str(raw.get("discover", "")),
        golden_suffix = str(raw.get("golden_suffix", "")),
        inputs = [str(item) for item in raw.get("inputs", [])],
        triggers_command = [str(part) for part in triggers],
        stratify_by = str(raw.get("stratify_by", "triggers")),
        holdout = float(raw.get("holdout", 0.2)),
        seed = int(raw.get("seed", 20260822)),
    )

def _parse_eval(raw, path):
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: `eval` must be a mapping.")

    extract = str(raw.get("extract", "fence"))
    if extract not in ("fence", "raw"):
        raise ConfigError(f"{path}: `eval.extract` must be `fence` or `raw`.")

    attempts = int(raw.get("attempts", 1))
    seeds = [int(seed) for seed in (raw.get("seeds") or [])]
    if not seeds:
        # Fixed seed list so pass@k is reproducible run to run
        seeds = [1000 + index for index in range(attempts)]
    if len(seeds) < attempts:
        raise ConfigError(
            f"{path}: `eval.seeds` has {len(seeds)} entries but `attempts` is {attempts}. "
            f"Give at least one seed per attempt so runs stay reproducible.")

    return EvalSettings(
        task = str(raw.get("task", "")),
        verifiers = [str(item) for item in (raw.get("verifiers") or [])],
        extract = extract,
        suffix = str(raw.get("suffix", ".txt")),
        attempts = attempts,
        seeds = seeds,
        temperature = float(raw.get("temperature", 0.2)),
        max_tokens = int(raw.get("max_tokens", 4096)),
        baseline_profile = str(raw.get("baseline_profile", "")),
        payload_header = str(raw.get("payload_header", "\n\n## Work item\n\n")),
    )

def load_config(path = None, start = "."):
    path = path or find_config(start)
    if path is None:
        raise ConfigError(
            "No promptc.yaml found in this directory or any parent.\n"
            "Run `promptc init` to create one.")

    with open(path, "r", encoding = "utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a YAML mapping.")

    thresholds = raw.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        raise ConfigError(f"{path}: `thresholds` must be a mapping of rule id to number.")

    vocabulary = raw.get("vocabulary") or {}
    if not isinstance(vocabulary, dict):
        raise ConfigError(f"{path}: `vocabulary` must be a mapping of canonical term to synonyms.")

    normalised_vocabulary = {}
    for canonical, synonyms in vocabulary.items():
        if isinstance(synonyms, str):
            synonyms = [synonyms]
        normalised_vocabulary[str(canonical)] = [str(item) for item in (synonyms or [])]

    return Config(
        root = os.path.dirname(os.path.abspath(path)),
        library = str(raw.get("library", "promptlib")),
        contracts = str(raw.get("contracts", "contracts")),
        eval = _parse_eval(raw.get("eval"), path),
        verifiers = _parse_verifiers(raw.get("verifiers"), path),
        profiles = _parse_profiles(raw.get("profiles"), path),
        corpus = _parse_corpus(raw.get("corpus"), path),
        thresholds = {str(key): value for key, value in thresholds.items()},
        hedges = [str(item) for item in (raw.get("hedges") or DEFAULT_HEDGES)],
        vocabulary = normalised_vocabulary,
    )
