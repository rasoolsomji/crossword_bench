"""Inspect extension registry (loaded via the inspect_ai entry point)."""

from inspect_ai.model import modelapi


@modelapi(name="codex")
def codex():
    from crossword_bench.codex_provider import CodexAppServerAPI

    return CodexAppServerAPI
