"""Inspect model provider backed by the Codex app server.

Lets a ChatGPT-plan Codex login stand in for an OpenAI API key:
`--model codex/<model-slug>`. One `codex app-server` process is shared
and each generate() call runs as a single-turn ephemeral thread.

Codex is an agent harness, not a bare completion endpoint, and its
built-in tools can't all be switched off. Web search is disabled and the
sandbox is read-only with no network, but the load-bearing guarantee is
enforced here: a turn that starts any tool item is interrupted and
returned as an empty answer flagged in the output metadata.

Reasoning summaries come back as bold headings only ("**Parsing the
clue**") on a ChatGPT login, whatever `summary` is requested: the server
streams nothing more, and `codex exec` gets the same. Readable summaries
need an API key and Inspect's `openai/<model>` provider with
`--reasoning-summary detailed`.
"""

import asyncio
import atexit
import json
import shutil
import sys
import tempfile
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ContentReasoning,
    ContentText,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool import ToolChoice, ToolInfo

PASSIVE_ITEMS = {"userMessage", "agentMessage", "reasoning"}
DEFAULT_EFFORT = "medium"
TURN_TIMEOUT_SECONDS = 900

# Harness features that only add tools or prompt boilerplate. Turning them
# off per thread roughly halves the injected context; it does not remove
# the core exec tool, hence the interrupt-on-tool-use guard below.
DISABLED_FEATURES = [
    "apps",
    "browser_use",
    "browser_use_external",
    "code_mode_host",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "plugins",
    "remote_plugin",
    "shell_tool",
    "skill_search",
    "sleep_tool",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
]


class CodexServerError(RuntimeError):
    pass


class CodexAppServer:
    """JSON-RPC (newline-delimited, over stdio) client for `codex app-server`."""

    def __init__(self, codex_path: str) -> None:
        self.codex_path = codex_path
        self.process: asyncio.subprocess.Process | None = None
        self.workdir = tempfile.mkdtemp(prefix="codex-eval-")
        self.rate_limits: dict[str, Any] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._threads: dict[str, asyncio.Queue] = {}
        self._reader: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._start_lock:
            if self.process is not None:
                return
            process = await asyncio.create_subprocess_exec(
                self.codex_path,
                "app-server",
                "-c",
                'web_search="disabled"',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.workdir,
                limit=16 * 1024 * 1024,
            )
            atexit.register(self._kill)
            self.process = process
            self._reader = asyncio.create_task(self._read_loop())
            await self.request(
                "initialize",
                {"clientInfo": {"name": "inspect-eval", "title": "Inspect eval", "version": "0.1"}},
            )
            await self._send({"method": "initialized"})

    async def _send(self, message: dict) -> None:
        assert self.process and self.process.stdin
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": params})
        return await future

    async def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        error: Exception = CodexServerError("codex app-server exited")
        try:
            while line := await self.process.stdout.readline():
                await self._dispatch(json.loads(line))
        except Exception as ex:  # noqa: BLE001
            error = CodexServerError(f"codex app-server connection failed: {ex}")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        for queue in self._threads.values():
            queue.put_nowait(error)

    async def _dispatch(self, message: dict) -> None:
        method = message.get("method")
        if method is None:
            future = self._pending.pop(message.get("id"), None)
            if future and not future.done():
                if "error" in message:
                    future.set_exception(CodexServerError(json.dumps(message["error"])))
                else:
                    future.set_result(message.get("result") or {})
        elif "id" in message:
            # Approval/elicitation requests: nothing may be approved during an eval.
            await self._send(
                {"id": message["id"], "error": {"code": -32601, "message": "not supported"}}
            )
        else:
            params = message.get("params") or {}
            if method == "account/rateLimits/updated":
                self.rate_limits = params.get("rateLimits")
            queue = self._threads.get(params.get("threadId"))
            if queue is not None:
                queue.put_nowait(message)

    async def run_turn(
        self, model: str, instructions: str, prompt: str, effort: str, summary: str = "auto"
    ) -> dict[str, Any]:
        await self.start()
        thread = await self.request(
            "thread/start",
            {
                "model": model,
                "cwd": self.workdir,
                "ephemeral": True,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "baseInstructions": instructions,
                "config": {
                    "web_search": "disabled",
                    "features": {feature: False for feature in DISABLED_FEATURES},
                },
            },
        )
        thread_id = thread["thread"]["id"]
        queue: asyncio.Queue = asyncio.Queue()
        self._threads[thread_id] = queue
        result: dict[str, Any] = {
            "messages": [],
            "reasoning": [],
            "tool_items": [],
            "usage": None,
            "status": None,
            "error": None,
        }
        try:
            await self.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "effort": effort,
                    "summary": summary,
                },
            )
            async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
                while True:
                    event = await queue.get()
                    if isinstance(event, Exception):
                        raise event
                    method, params = event["method"], event["params"]
                    item = params.get("item") or {}
                    if method == "item/started" and item.get("type") not in PASSIVE_ITEMS:
                        if not result["tool_items"]:
                            await self.request(
                                "turn/interrupt",
                                {"threadId": thread_id, "turnId": params.get("turnId")},
                            )
                        result["tool_items"].append(item.get("type"))
                    elif method == "item/completed" and item.get("type") == "agentMessage":
                        result["messages"].append(item)
                    elif method == "item/completed" and item.get("type") == "reasoning":
                        result["reasoning"].append(item)
                    elif method == "thread/tokenUsage/updated":
                        result["usage"] = params["tokenUsage"]["total"]
                    elif method == "error":
                        result["error"] = json.dumps(params.get("error") or params)
                    elif method == "turn/completed":
                        turn = params["turn"]
                        result["status"] = turn.get("status")
                        if turn.get("error"):
                            result["error"] = json.dumps(turn["error"])
                        return result
        finally:
            self._threads.pop(thread_id, None)

    def _kill(self) -> None:
        if self.rate_limits:
            windows = [
                f"{window['windowDurationMins'] // 60}h window {window['usedPercent']}% used"
                for key in ("primary", "secondary")
                if (window := self.rate_limits.get(key))
            ]
            print(f"Codex plan usage after run: {', '.join(windows)}", file=sys.stderr)
            self.rate_limits = None
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
        shutil.rmtree(self.workdir, ignore_errors=True)

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        self._kill()


def _reasoning_text(item: dict) -> str:
    parts = [*(item.get("summary") or []), *(item.get("content") or [])]
    return "\n\n".join(p if isinstance(p, str) else p.get("text", "") for p in parts).strip()


class CodexAppServerAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        codex_path: str = "codex",
        **_model_args: Any,
    ) -> None:
        super().__init__(model_name=model_name, base_url=base_url, api_key=api_key, config=config)
        self.server = CodexAppServer(codex_path)

    def max_connections(self) -> int:
        return 4

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        if tools:
            raise ValueError("The codex provider does not support tool calling.")
        instructions = "\n\n".join(m.text for m in input if isinstance(m, ChatMessageSystem))
        turns = [m for m in input if not isinstance(m, ChatMessageSystem)]
        if len(turns) == 1:
            prompt = turns[0].text
        else:
            prompt = "\n\n".join(f"[{m.role}]\n{m.text}" for m in turns)

        result = await self.server.run_turn(
            model=self.model_name,
            instructions=instructions,
            prompt=prompt,
            effort=config.reasoning_effort or DEFAULT_EFFORT,
            summary=config.reasoning_summary or "auto",
        )

        if result["tool_items"]:
            output = ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error=f"Turn interrupted: model started tool items {result['tool_items']}",
            )
            output.metadata = {"codex_tool_items": result["tool_items"]}
            return output
        if result["status"] != "completed":
            raise CodexServerError(
                f"Codex turn ended with status {result['status']}: {result['error']}"
            )

        finals = [m for m in result["messages"] if m.get("phase") in (None, "final_answer")]
        text = "\n\n".join(m.get("text", "") for m in (finals or result["messages"]))
        content: list = [
            ContentReasoning(reasoning=reasoning)
            for item in result["reasoning"]
            if (reasoning := _reasoning_text(item))
        ]
        content.append(ContentText(text=text))
        output = ModelOutput.from_content(model=self.model_name, content=content)
        if usage := result["usage"]:
            cached = usage.get("cachedInputTokens") or 0
            output.usage = ModelUsage(
                input_tokens=usage["inputTokens"] - cached,
                output_tokens=usage["outputTokens"],
                total_tokens=usage["totalTokens"],
                input_tokens_cache_read=cached,
                reasoning_tokens=usage.get("reasoningOutputTokens"),
            )
        return output

    def should_retry(self, ex: BaseException) -> bool:
        return False

    async def aclose(self) -> None:
        await self.server.close()
