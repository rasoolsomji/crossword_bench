"""Cryptic crossword benchmark tasks for Inspect AI."""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import json_dataset
from inspect_ai.solver import generate, system_message

from crossword_bench.scorer import cryptic_scorer

DATA_DIR = Path(__file__).parent.parent.parent / "data"

SYSTEM_PROMPT = """\
You are solving a cryptic crossword clue. The number in parentheses \
indicates the length of the answer.

Analyse the clue by identifying the definition and wordplay components, \
then work through the wordplay to find the answer.

Give your final answer in uppercase on its own line, like this:

ANSWER: EXAMPLE"""


@task
def cryptic_crossword(
    dataset: str | None = None,
    cot: bool = False,
):
    """Cryptic crossword benchmark.

    Args:
        dataset: Path to clues JSON file. Defaults to data/clues.json.
        cot: If True, prepend a chain-of-thought solver.
    """
    if dataset is None:
        # Real clue data is private and gitignored; fall back to the
        # committed sample so a fresh clone still runs.
        default = DATA_DIR / "clues.json"
        if not default.exists():
            default = DATA_DIR / "sample_clues.json"
        dataset = str(default)
    dataset_path = dataset

    solvers = [system_message(SYSTEM_PROMPT)]

    if cot:
        from inspect_ai.solver import chain_of_thought

        solvers.append(chain_of_thought())

    solvers.append(generate())

    return Task(
        dataset=json_dataset(dataset_path),
        solver=solvers,
        scorer=cryptic_scorer(),
    )
