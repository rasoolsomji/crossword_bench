import asyncio
import shutil
from types import SimpleNamespace

import pytest

from crossword_bench import codex_provider
from crossword_bench.codex_provider import CodexAppServer, CodexServerError


def test_requests_fail_once_the_reader_has_stopped():
    async def scenario():
        server = CodexAppServer("codex")
        shutil.rmtree(server.workdir)
        stdout = asyncio.StreamReader()
        stdout.feed_data(b"not json\n")
        stdout.feed_eof()
        server.process = SimpleNamespace(stdout=stdout)
        await server._read_loop()
        with pytest.raises(CodexServerError):
            await server.request("thread/start", {})

    asyncio.run(scenario())


def test_timed_out_turn_is_interrupted(monkeypatch):
    monkeypatch.setattr(codex_provider, "TURN_TIMEOUT_SECONDS", 0.01)
    calls = []

    async def scenario():
        server = CodexAppServer("codex")
        shutil.rmtree(server.workdir)

        async def start():
            pass

        async def request(method, params):
            calls.append((method, params))
            return {"thread/start": {"thread": {"id": "t"}}, "turn/start": {"turn": {"id": "u"}}}.get(method, {})

        server.start, server.request = start, request
        with pytest.raises(TimeoutError):
            await server.run_turn("m", "", "clue", "medium")

    asyncio.run(scenario())
    assert calls[-1] == ("turn/interrupt", {"threadId": "t", "turnId": "u"})
