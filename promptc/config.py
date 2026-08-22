"""Project configuration (promptc.yaml).

This file is the entire domain boundary. The toolset knows how to run a
command you gave it and read an exit code; everything it knows about your
language, toolchain or project arrives through here.

Validation happens at parse time wherever a fault would otherwise surface
later as a confusing diagnostic. A profile whose reserves exceed its
context is the clearest case: left alone it produces a negative budget, and
PC004 then blames the prompt for what is really a configuration error.
"""

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
    """An external program that decides whether some text is valid.

    Attributes:
        id: Name used to reference this verifier from `eval.verifiers`.
        command: Argv list. `{file}` is replaced with a temp file holding
            the text. Argv rather than a shell string, so nothing is
            word-split or expanded behind the caller's back.
        match: Compared against a fence info string to decide whether this
            verifier applies to a block. Empty matches every block.
        timeout: Seconds before the run is abandoned and treated as exit
            124.
        suffix: Extension for the temp file. Empty means derive it from the
            fence language, so a ```cpp block becomes `.cpp` with no
            configuration.
    """

    id: str
    command: list
    match: str = ""
    timeout: int = 120
    suffix: str = ""

###########################################################
# Profile
###########################################################
@dataclasses.dataclass
class Profile:
    """A target model: how big its window is and how to reach it.

    Attributes:
        name: Profile name, as used by `--profile`.
        context: Total context window in tokens.
        tokenizer: Spec passed to tokens.counter. `chars` estimates.
        reserve: Tokens held back for the runtime work item, which is not
            part of the assembled prompt but must still fit beside it.
        output_reserve: Tokens held back for the model's own output.
        endpoint: Base URL, for the llamacpp and openai backends.
        model: Model name, for the openai backend.
        raw: The profile mapping as written, passed to make_backend so
            backend-specific keys need no schema here.
    """

    name: str
    context: int = 32768
    tokenizer: str = "chars"
    reserve: int = 0
    output_reserve: int = 2048
    endpoint: str = ""
    model: str = ""
    raw: dict = dataclasses.field(default_factory = dict)

    def budget(self):
        """Return the tokens available to the assembled prompt.

        Returns:
            int: `context` minus both reserves. Guaranteed positive --
            a non-positive budget is rejected at parse time.
        """
        return self.context - self.reserve - self.output_reserve

###########################################################
# Corpus
###########################################################
@dataclasses.dataclass
class Corpus:
    """Where the labelled work items live and how to split them.

    Attributes:
        root: Directory containing the corpus, relative to the project
            root.
        discover: Recursive glob finding golden files. Each match defines
            one work item.
        golden_suffix: Suffix stripped from a golden path to derive the
            item stem, e.g. `.expected.txt`.
        inputs: `{stem}`-templated paths shown to the model. A path that
            does not exist is skipped rather than failing the item.
        triggers_command: Argv emitting one trigger name per line.
            `{stem}`, `{golden}` and `{input}` are substituted.
        stratify_by: Currently only `triggers`.
        holdout: Fraction assigned to the test split.
        seed: Makes the split reproducible across runs and machines.
    """

    root: str = ""
    discover: str = ""
    golden_suffix: str = ""
    inputs: list = dataclasses.field(default_factory = list)
    triggers_command: list = dataclasses.field(default_factory = list)
    stratify_by: str = "triggers"
    holdout: float = 0.2
    seed: int = 20260822

###########################################################
# Config
###########################################################
@dataclasses.dataclass
class EvalSettings:
    """How `promptc eval` builds prompts and scores what comes back.

    Attributes:
        task: Id of the task fragment used as the prompt entry point.
        verifiers: Verifier ids run against model output, in order. The
            first failure wins and is what the taxonomy names.
        extract: `fence` takes the first fenced block; `raw` uses the
            output as-is.
        suffix: Extension for the temp file handed to verifiers.
        attempts: Attempts per item. pass@k is computed over these, and an
            item stops at its first success.
        seeds: One seed per attempt, so pass@k is reproducible. Generated
            when not given.
        temperature: Sampling temperature.
        max_tokens: Generation cap.
        baseline_profile: Profile whose pass rate is the denominator of the
            portability index.
        payload_header: Text separating the assembled instructions from the
            rendered work item.
    """

    task: str = ""
    verifiers: list = dataclasses.field(default_factory = list)
    extract: str = "fence"
    suffix: str = ".txt"
    attempts: int = 1
    seeds: list = dataclasses.field(default_factory = list)
    temperature: float = 0.2
    max_tokens: int = 4096
    baseline_profile: str = ""
    payload_header: str = "\n\n## Work item\n\n"

@dataclasses.dataclass
class Config:
    """A loaded promptc.yaml.

    Attributes:
        root: Absolute path to the directory holding promptc.yaml. Every
            relative path in the config resolves against it.
        library: Fragment directory, relative to root.
        contracts: Grammar and schema directory, relative to root.
        verifiers: Configured Verifier objects.
        eval: EvalSettings.
        profiles: Profile name to Profile.
        corpus: Corpus.
        thresholds: Rule id to threshold, overriding DEFAULT_THRESHOLDS.
        hedges: Phrases counted by PC100. Falls back to DEFAULT_HEDGES.
        vocabulary: Canonical term to banned synonyms, driving PC104.
    """

    root: str
    library: str = "promptlib"
    contracts: str = "contracts"
    verifiers: list = dataclasses.field(default_factory = list)
    eval: "EvalSettings" = dataclasses.field(default_factory = lambda: EvalSettings())
    profiles: dict = dataclasses.field(default_factory = dict)
    corpus: Corpus = dataclasses.field(default_factory = Corpus)
    thresholds: dict = dataclasses.field(default_factory = dict)
    hedges: list = dataclasses.field(default_factory = list)
    vocabulary: dict = dataclasses.field(default_factory = dict)

    def library_path(self):
        """Return the absolute path to the fragment library."""
        return os.path.join(self.root, self.library)

    def contracts_path(self):
        """Return the absolute path to the contracts directory."""
        return os.path.join(self.root, self.contracts)

    def threshold(self, rule):
        """Return the threshold for a heuristic rule.

        Args:
            rule: Rule id, e.g. `PC100`.

        Returns:
            The configured override, else the built-in default, else None.
            None means the rule has no threshold and should abstain.
        """
        return self.thresholds.get(rule, DEFAULT_THRESHOLDS.get(rule))

    def profile(self, name):
        """Return the named profile, or None."""
        return self.profiles.get(name)

    def verifier(self, verifier_id):
        """Return the verifier with this id, or None."""
        for verifier in self.verifiers:
            if verifier.id == verifier_id:
                return verifier
        return None

###########################################################
# Loading
###########################################################
class ConfigError(Exception):
    """The project configuration is invalid or missing.

    Raised with a message naming the file, what is wrong, and what correct
    looks like. cli.main catches it and prints it without a traceback,
    because a typo in YAML is a user error rather than a crash.
    """

CONFIG_NAMES = ("promptc.yaml", "promptc.yml")

def find_config(start = "."):
    """Search upward for a project config.

    Args:
        start: Directory to start from.

    Returns:
        str: Absolute path to the nearest config, or None if the search
        reaches the filesystem root without finding one.
    """
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
    """Parse the `verifiers` block.

    Args:
        raw: The raw list, or None.
        path: Config path, for error messages.

    Returns:
        list: Verifier objects.

    Raises:
        ConfigError: An entry is not a mapping, lacks `id`, or gives
            `command` as anything but a non-empty list.
    """
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
    """Parse the `profiles` block.

    Args:
        raw: The raw mapping, or None.
        path: Config path, for error messages.

    Returns:
        dict: Profile name to Profile.

    Raises:
        ConfigError: A profile is not a mapping, or leaves no room for a
            prompt once both reserves are subtracted from its context.
    """
    profiles = {}
    for name, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: profile `{name}` must be a mapping.")

        context = int(entry.get("context", 32768))
        reserve = int(entry.get("reserve", 0))
        output_reserve = int(entry.get("output_reserve", 2048))

        # A non-positive budget makes PC004 nonsense: every prompt "exceeds"
        # it, and the diagnostic then blames the prompt for what is really a
        # configuration fault.
        if context - reserve - output_reserve <= 0:
            raise ConfigError(
                f"{path}: profile `{name}` leaves no room for a prompt — context "
                f"{context:,} minus reserve {reserve:,} minus output_reserve "
                f"{output_reserve:,} is {context - reserve - output_reserve:,}.\n"
                f"Raise `context`, or lower the reserves "
                f"(`output_reserve` defaults to 2048).")

        profiles[str(name)] = Profile(
            name = str(name),
            context = context,
            tokenizer = str(entry.get("tokenizer", "chars")),
            reserve = reserve,
            output_reserve = output_reserve,
            endpoint = str(entry.get("endpoint", "")),
            model = str(entry.get("model", "")),
            raw = dict(entry),
        )
    return profiles

def _parse_corpus(raw, path):
    """Parse the `corpus` block.

    Args:
        raw: The raw mapping, or None.
        path: Config path, for error messages.

    Returns:
        Corpus: Defaults throughout when the block is absent. Missing
        required fields are reported later by corpus.discover, which can
        say what they are for.

    Raises:
        ConfigError: The block is not a mapping, or `triggers_command` is
            not a list.
    """
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
    """Parse the `eval` block.

    Seeds are generated when absent so that pass@k is reproducible without
    the author having to think about it, but a short explicit list is an
    error rather than being silently padded -- padding would make one run's
    figures incomparable with the next.

    Args:
        raw: The raw mapping, or None.
        path: Config path, for error messages.

    Returns:
        EvalSettings.

    Raises:
        ConfigError: The block is not a mapping, `extract` is not `fence`
            or `raw`, or fewer seeds are given than attempts.
    """
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
    """Load and validate a project configuration.

    Args:
        path: Explicit config path. When None, searches upward from
            `start`.
        start: Directory to search from when `path` is None.

    Returns:
        Config: With `root` set to the directory holding the file, so
        every relative path in it resolves correctly regardless of the
        working directory.

    Raises:
        ConfigError: No config was found, an explicit path does not exist,
            the top level is not a mapping, or any block fails validation.
    """
    path = path or find_config(start)
    if path is None:
        raise ConfigError(
            "No promptc.yaml found in this directory or any parent.\n"
            "Run `promptc init` to create one.")

    # An explicit --config that does not exist is a user typo, not a crash
    if not os.path.exists(path):
        raise ConfigError(
            f"Config file not found: {path}\n"
            f"Check the path, or run `promptc init` to create one.")

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
