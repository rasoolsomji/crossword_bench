"""Cryptic crossword benchmark tasks for Inspect AI."""

import hashlib
import json
from glob import glob
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample, json_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.solver import generate, system_message

from crossword_bench.scorer import cryptic_scorer

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_EFFORT = "medium"

SYSTEM_PROMPT = """\
You are solving a cryptic crossword clue. The number in parentheses \
indicates the length of the answer.

Analyse the clue by identifying the definition and wordplay components, \
then work through the wordplay to find the answer. Rely only on your own \
reasoning: do not use tools or look anything up.

Give your final answer in uppercase on its own line, like this:

ANSWER: EXAMPLE"""


def resolve_dataset_files(spec: str | None) -> list[Path]:
    """Expand a dataset spec (file, directory, glob, or comma-separated mix)."""
    if spec is None:
        # Real clue data is private and gitignored; fall back to the
        # committed sample so a fresh clone still runs.
        default = DATA_DIR / "clues.json"
        return [default if default.exists() else DATA_DIR / "sample_clues.json"]

    files: list[Path] = []
    for part in spec.split(","):
        path = Path(part.strip()).expanduser()
        # Inspect runs task files from their own directory, so relative
        # specs are resolved against the project root.
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.is_dir():
            matches = sorted(path.glob("*.json"))
        else:
            matches = sorted(Path(match) for match in glob(str(path)))
        if not matches:
            raise FileNotFoundError(f"No dataset files match '{part.strip()}'")
        files.extend(matches)
    return files


def load_samples(files: list[Path]) -> list[Sample]:
    samples: list[Sample] = []
    for file in files:
        samples.extend(json_dataset(str(file)))
    for sample in samples:
        if sample.id is None:
            # Derived from the clue rather than its position, so editing or
            # dropping other clues in the file leaves this id unchanged.
            sample.id = content_digest([sample.input, sample.target])[:12]
    ids = [sample.id for sample in samples]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate sample ids across dataset files")
    return samples


def content_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@task
def cryptic_crossword(
    dataset: str | None = None,
    label: str | None = None,
    cot: bool = False,
):
    """Cryptic crossword benchmark.

    Args:
        dataset: Clues JSON file, directory, glob, or comma-separated list
            of those. Defaults to data/clues.json.
        label: Cohort name shown on the leaderboard. Models are only
            comparable within the same cohort (identical clues). Defaults
            to the dataset file name plus a hash of its clues.
        cot: If True, prepend a chain-of-thought solver.
    """
    files = resolve_dataset_files(dataset)
    samples = load_samples(files)
    if label is None:
        label = files[0].stem if len(files) == 1 else f"{files[0].stem}..{files[-1].stem}"
        # A changed clue set gets a new default cohort instead of joining
        # runs made on the old one.
        digest = content_digest([[s.id, s.input, s.target] for s in samples])
        label = f"{label}-{digest[:8]}"

    solvers = [system_message(SYSTEM_PROMPT)]

    if cot:
        from inspect_ai.solver import chain_of_thought

        solvers.append(chain_of_thought())

    solvers.append(generate())

    return Task(
        dataset=MemoryDataset(samples, name=label),
        solver=solvers,
        scorer=cryptic_scorer(),
        # Provider defaults differ and are not logged, and Claude only returns
        # readable thinking summaries when an effort is set, so every run
        # records one. --reasoning-effort overrides it.
        config=GenerateConfig(reasoning_effort=DEFAULT_EFFORT),
    )
