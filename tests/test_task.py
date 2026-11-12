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
    from crossword_bench.task import cryptic_crossword

    data = write(tmp_path / "clues.json", [{"input": "x (1)", "target": "X"}])
    before = cryptic_crossword(dataset=str(data))
    write(data, [{"input": "x (1)", "target": "Y"}])
    after = cryptic_crossword(dataset=str(data))
    assert before.dataset.name.startswith("clues-")
    assert before.dataset.name != after.dataset.name
    assert cryptic_crossword(dataset=str(data), label="fixed").dataset.name == "fixed"
