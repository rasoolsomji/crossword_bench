import json

import pytest

from crossword_bench.task import load_samples, resolve_dataset_files


def write(path, samples):
    path.write_text(json.dumps(samples))
    return path


def test_resolves_directories_globs_and_lists(tmp_path):
    a = write(tmp_path / "a.json", [{"id": "a1", "input": "x (1)", "target": "X"}])
    b = write(tmp_path / "b.json", [{"id": "b1", "input": "y (1)", "target": "Y"}])
    assert resolve_dataset_files(str(tmp_path)) == [a, b]
    assert resolve_dataset_files(str(tmp_path / "*.json")) == [a, b]
    assert resolve_dataset_files(f"{b}, {a}") == [b, a]
    with pytest.raises(FileNotFoundError):
        resolve_dataset_files(str(tmp_path / "missing.json"))


def test_ids_assigned_when_missing_and_duplicates_rejected(tmp_path):
    a = write(tmp_path / "a.json", [{"input": "x (1)", "target": "X"}, {"input": "y (1)", "target": "Y"}])
    b = write(tmp_path / "b.json", [{"input": "y (1)", "target": "Y"}])
    c = write(tmp_path / "c.json", [{"id": "kept", "input": "z (1)", "target": "Z"}])
    ids = [s.id for s in load_samples([a, c])]
    assert ids[2] == "kept"
    assert [s.id for s in load_samples([b])] == ids[1:2]
    c = write(tmp_path / "c.json", [{"id": "dup", "input": "x (1)", "target": "X"}])
    with pytest.raises(ValueError):
        load_samples([c, c])


def test_task_always_sets_an_effort(tmp_path):
    from crossword_bench.task import DEFAULT_EFFORT, cryptic_crossword

    data = write(tmp_path / "a.json", [{"id": "a1", "input": "x (1)", "target": "X"}])
    assert cryptic_crossword(dataset=str(data)).config.reasoning_effort == DEFAULT_EFFORT


def test_default_label_changes_with_the_clues(tmp_path):
    from crossword_bench.task import DEFAULT_MAX_TOKENS, cryptic_crossword

    data = write(tmp_path / "clues.json", [{"input": "x (1)", "target": "X"}])
    before = cryptic_crossword(dataset=str(data))
    assert before.config.max_tokens == DEFAULT_MAX_TOKENS
    write(data, [{"input": "x (1)", "target": "Y"}])
    after = cryptic_crossword(dataset=str(data))
    assert before.dataset.name.startswith("clues-")
    assert before.dataset.name != after.dataset.name
    assert cryptic_crossword(dataset=str(data), label="fixed").dataset.name == "fixed"


KIMI_EFFORTS = ("max", "high", "low", "none")


def test_unsupported_openrouter_effort_is_refused():
    from crossword_bench.task import require_supported_effort

    lookup = {"moonshotai/kimi-k3.1-pro": KIMI_EFFORTS}.get
    with pytest.raises(ValueError, match="no 'medium' reasoning effort"):
        require_supported_effort("openrouter/moonshotai/kimi-k3.1-pro", "medium", lookup)
    require_supported_effort("openrouter/moonshotai/kimi-k3.1-pro", "low", lookup)
    # Models that list no efforts, and providers other than OpenRouter, are left alone.
    require_supported_effort("openrouter/deepseek/deepseek-v4.1-flash-1017", "medium", lookup)
    require_supported_effort("anthropic/claude-haiku-5-5", "medium", lambda slug: pytest.fail(slug))


def test_task_checks_the_effort_the_run_will_use(tmp_path, monkeypatch):
    from inspect_ai.model import GenerateConfig

    from crossword_bench import task as task_module

    class FakeModel:
        def __init__(self, effort):
            self.config = GenerateConfig(reasoning_effort=effort)

        def __str__(self):
            return "openrouter/moonshotai/kimi-k3.1-pro"

    monkeypatch.setattr(task_module, "openrouter_efforts", lambda slug: KIMI_EFFORTS)
    data = write(tmp_path / "a.json", [{"id": "a1", "input": "x (1)", "target": "X"}])

    monkeypatch.setattr(task_module, "get_model", lambda: FakeModel(None))
    with pytest.raises(ValueError, match="'medium'"):
        task_module.cryptic_crossword(dataset=str(data))

    monkeypatch.setattr(task_module, "get_model", lambda: FakeModel("high"))
    assert task_module.cryptic_crossword(dataset=str(data)).dataset[0].id == "a1"
