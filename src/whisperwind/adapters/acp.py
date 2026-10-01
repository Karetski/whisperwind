"""ACP adapters: any Agent Client Protocol (v1) agent, declared in
`.whisperwind/harnesses/<name>.yaml` with `protocol: acp`.

The client speaks newline-delimited JSON-RPC 2.0 on the agent's stdio, with the
standard library only. Each attempt spawns one agent process in its own process
group: `initialize`, then open a session (`session/new`, or `session/resume` or
`session/load` to resume one), apply the model, effort and mode, and send one
`session/prompt`. Session updates become adapter events and the prompt's stop
reason decides the outcome. Both directions are saved to `stream.jsonl`, one
`{"from": "client" | "agent", "message": ...}` per line.

The client declares no file-system or terminal capabilities, so the agent uses
its own tools in `cwd`. Permission requests are answered from the node's
permission profile by tool kind. Tools the agent approves on its own never
reach the client, so the harness file's optional `modes` map also selects the
agent's mode for each profile.

What ACP v1 lacks of the adapter contract travels in Whisperwind's extension:
an agent that advertises `agentCapabilities._meta.whisperwind` with a known
version and its features gets the request's instructions, output schema,
limits and permissions under the prompt's `_meta.whisperwind`, and answers with
its outcome, output, usage, turns and denials under the response's
`_meta.whisperwind`. Standard ACP fields win where both carry the same
information. Without the extension, instructions lead the prompt and
structured output falls back to a JSON instruction and extraction.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, ClassVar

from whisperwind import __version__
from whisperwind.adapters import (
    AdapterEvent,
    AgentRequest,
    AgentResult,
    Capabilities,
    Denial,
    ErrorInfo,
    Log,
    PermissionDenied,
    Probe,
    SessionStarted,
    Text,
    ToolCall,
    ToolResult,
    Usage,
    UsageUpdate,
)
from whisperwind.adapters.command import HarnessSpec, substitute
from whisperwind.adapters.process import (
    TERM_WAIT_S,
    ProcessAdapter,
    _read_stderr,
    _stopped_outcome,
    version_in_range,
)
from whisperwind.engine.structured import extract_json, json_instruction
from whisperwind.flowspec import duration
from whisperwind.schema import Bool, Field, ListOf, MapOf, Str, Struct

PROTOCOL_VERSION = 1
AUTH_REQUIRED = -32000
METHOD_NOT_FOUND = -32601
MAX_MESSAGE = 16 * 1024 * 1024  # bytes in one JSON-RPC line
PROBE_TIMEOUT_S = 20.0
# Tool kinds each profile approves when the agent asks; `full` approves every kind.
APPROVED_KINDS = {
    "read-only": frozenset({"read", "search", "think", "fetch"}),
    "edit": frozenset({"read", "search", "think", "fetch", "edit", "delete", "move"}),
}
EXTENSION = "whisperwind"  # the `_meta` key of Whisperwind's ACP extension
EXTENSION_VERSIONS = (1,)
# Extension features that back a capability the harness file may declare.
FEATURE_CAPABILITIES = {
    "output_schema": "structured_output",
    "max_turns": "turn_cap",
    "budget": "budget_cap",
    "usage": "tokens",
    "tool_rules": "tool_rules",
}
# Outcomes an agent can know about; the engine decides `cancelled` and `timed_out`.
AGENT_OUTCOMES = ("succeeded", "failed", "budget_exceeded", "schema_invalid")

ACP_HARNESS_FILE = Struct(
    {
        "name": Field(Str(pattern=r"^[a-z][a-z0-9_-]*$"), required=True),
        "protocol": Field(Str(enum=("acp",)), required=True),
        "command": Field(ListOf(Str(), min_items=1), required=True),
        "interactive_command": Field(ListOf(Str(), min_items=1)),
        "capabilities": Field(
            Struct(
                {
                    key: Field(Bool())
                    for key in ("resume", "cost_usd", "effort", *FEATURE_CAPABILITIES.values())
                }
            )
        ),
        "modes": Field(MapOf(Str())),
        "env": Field(ListOf(Str())),
        "tested_versions": Field(Str()),
        "grace": Field(duration()),
    },
    doc="A Whisperwind ACP adapter (.whisperwind/harnesses/<name>.yaml with protocol: acp).",
)


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class ConnectionLost(Exception):
    """The agent closed its stdout before answering."""


class Connection:
    """One JSON-RPC 2.0 peer on a process's stdio. Every message in either
    direction is also written to the transcript."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        transcript: IO[str],
        answer: Callable[[str, dict[str, Any]], Any],
        notice: Callable[[str, dict[str, Any]], None],
        emit: Callable[[AdapterEvent], None],
    ) -> None:
        self.process = process
        self.transcript = transcript
        self.answer = answer  # agent requests; raises RpcError to refuse
        self.notice = notice  # agent notifications
        self.emit = emit
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.next_id = 0
        self.closed = False

    def _record(self, side: str, message: Any) -> None:
        self.transcript.write(json.dumps({"from": side, "message": message}) + "\n")
        self.transcript.flush()

    def _send(self, message: dict[str, Any]) -> None:
        message = {"jsonrpc": "2.0", **message}
        self._record("client", message)
        stdin = self.process.stdin
        if self.closed or stdin is None or stdin.is_closing():
            return
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            stdin.write(json.dumps(message).encode("utf-8") + b"\n")

    def request(self, method: str, params: dict[str, Any]) -> asyncio.Future[Any]:
        """Send a request; the future resolves to its result, or fails with
        RpcError or ConnectionLost."""
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        if self.closed:
            future.set_exception(ConnectionLost())
            return future
        self.next_id += 1
        self.pending[self.next_id] = future
        self._send({"id": self.next_id, "method": method, "params": params})
        return future

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        return await self.request(method, params)

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def close(self) -> None:
        stdin = self.process.stdin
        if stdin is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                stdin.close()

    async def serve(self) -> None:
        """Read the agent's messages until it closes stdout."""
        stream = self.process.stdout
        assert stream is not None
        try:
            while True:
                try:
                    line = await stream.readline()
                except ValueError:  # a line longer than MAX_MESSAGE
                    self.emit(Log("warning", "the agent sent an over-long message; skipped"))
                    continue
                if not line:
                    break
                if line.strip():
                    self._dispatch(line)
        finally:
            self.closed = True
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionLost())
            self.pending.clear()

    def _dispatch(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            self._record("agent", {"unparsed": line.decode("utf-8", "replace")})
            self.emit(Log("warning", f"non-JSON output: {line[:200].decode('utf-8', 'replace')}"))
            return
        self._record("agent", message)
        if not isinstance(message, dict):
            return
        method = message.get("method")
        if isinstance(method, str) and "id" in message:
            try:
                result = self.answer(method, message.get("params") or {})
            except RpcError as exc:
                error = {"code": exc.code, "message": exc.message}
                self._send({"id": message["id"], "error": error})
            else:
                self._send({"id": message["id"], "result": result})
        elif isinstance(method, str):
            self.notice(method, message.get("params") or {})
        else:
            future = self.pending.pop(message.get("id"), None)  # type: ignore[arg-type]
            if future is None or future.done():
                return
            if isinstance(message.get("error"), dict):
                error = message["error"]
                future.set_exception(
                    RpcError(
                        int(error.get("code", 0)), str(error.get("message")), error.get("data")
                    )
                )
            else:
                future.set_result(message.get("result"))


def _options(option: dict[str, Any]) -> list[str]:
    """The values of a select config option, flat or grouped."""
    values = []
    for entry in option.get("options") or []:
        if isinstance(entry, dict) and "group" in entry:
            values += [o.get("value") for o in entry.get("options") or [] if isinstance(o, dict)]
        elif isinstance(entry, dict):
            values.append(entry.get("value"))
    return [str(v) for v in values if v is not None]


class Turn:
    """One attempt's conversation with the agent: its session, the events it
    streams once the prompt is sent, and the permission answers."""

    def __init__(
        self, adapter: AcpAdapter, req: AgentRequest, emit: Callable[[AdapterEvent], None]
    ) -> None:
        self.adapter = adapter
        self.req = req
        self.emit = emit
        self.init: dict[str, Any] = {}  # the agent's `initialize` response
        self.features: frozenset[str] | None = None  # None: no usable extension
        self.version: str | None = None
        self.session_id: str | None = None
        self.prompt: asyncio.Future[Any] | None = None
        self.texts: list[str] = []
        self.tools: dict[str, str] = {}  # tool call ID -> name
        self.denials: list[Denial] = []
        self.total_usd: float | None = None

    # -- driving the session ---------------------------------------------------------

    async def drive(self, conn: Connection) -> AgentResult:
        """Run the session up to the prompt's response. Raises ConnectionLost when
        the agent exits first."""
        try:
            init = await conn.call(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "whisperwind", "version": __version__},
                },
            )
            self.init = init = init if isinstance(init, dict) else {}
            self.version = (init.get("agentInfo") or {}).get("version")
            if init.get("protocolVersion") != PROTOCOL_VERSION:
                return self._failed(
                    f"the agent speaks ACP version {init.get('protocolVersion')!r}; "
                    f"Whisperwind speaks {PROTOCOL_VERSION}"
                )
            caps = init.get("agentCapabilities") or {}
            self.features = self._extension(caps)
            opened = await self._open(conn, caps)
            await self._configure(conn, opened)
            params: dict[str, Any] = {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": self._text()}],
            }
            if self.features is not None:
                params["_meta"] = {EXTENSION: self._extension_request()}
            self.prompt = conn.request("session/prompt", params)
            response = await asyncio.shield(self.prompt)
        except RpcError as exc:
            return self.rpc_failure(exc)
        return self.result(response)

    async def _open(self, conn: Connection, caps: dict[str, Any]) -> dict[str, Any]:
        req = self.req
        params: dict[str, Any] = {"cwd": req.cwd, "mcpServers": []}
        session_caps = caps.get("sessionCapabilities") or {}
        if req.add_dirs:
            if session_caps.get("additionalDirectories") is not None:
                params["additionalDirectories"] = list(req.add_dirs)
            else:
                self.emit(Log("warning", "the agent does not accept add_dirs; they are ignored"))
        resume_id = req.session.resume_id if req.session.mode != "new" else None
        method = "session/new"
        if resume_id and session_caps.get("resume") is not None:
            method = "session/resume"
        elif resume_id and caps.get("loadSession"):
            method = "session/load"
        elif resume_id:
            self.emit(Log("warning", "the agent cannot resume sessions; starting a new one"))
        if method != "session/new":
            params["sessionId"] = resume_id
            self.session_id = resume_id
            self.emit(SessionStarted(str(resume_id)))
        opened = await conn.call(method, params)
        opened = opened if isinstance(opened, dict) else {}
        if method == "session/new":
            self.session_id = str(opened.get("sessionId"))
            self.emit(SessionStarted(self.session_id))
        return opened

    async def _configure(self, conn: Connection, opened: dict[str, Any]) -> None:
        """Set the model, effort and mode the request asks for, where the agent
        exposes a matching option."""
        req = self.req
        options = [o for o in opened.get("configOptions") or [] if isinstance(o, dict)]
        wanted = [("model", req.model, "model"), ("thought_level", req.effort, "effort")]
        mode = (self.adapter.spec.data.get("modes") or {}).get(req.permissions)
        for category, value, what in wanted:
            if value is None:
                continue
            option = next(
                (o for o in options if o.get("category") == category and value in _options(o)),
                None,
            )
            if option is None:
                self.emit(Log("warning", f"the agent has no {what} option {value!r}; ignored"))
                continue
            changed = await conn.call(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": option["id"], "value": value},
            )
            if isinstance(changed, dict) and isinstance(changed.get("configOptions"), list):
                options = [o for o in changed["configOptions"] if isinstance(o, dict)]
        if mode is None:
            return
        option = next(
            (o for o in options if o.get("category") == "mode" and mode in _options(o)), None
        )
        available = [m.get("id") for m in (opened.get("modes") or {}).get("availableModes") or []]
        if option is not None:
            await conn.call(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": option["id"], "value": mode},
            )
        elif mode in available:
            await conn.call("session/set_mode", {"sessionId": self.session_id, "modeId": mode})
        else:
            self.emit(Log("warning", f"the agent has no mode {mode!r}; permission answers only"))

    def _extension(self, caps: dict[str, Any]) -> frozenset[str] | None:
        """The extension features the agent advertises, warning about declared
        capabilities it does not back."""
        meta = caps.get("_meta") or {}
        advert = meta.get(EXTENSION) if isinstance(meta, dict) else None
        features: frozenset[str] | None = None
        if isinstance(advert, dict) and advert.get("version") in EXTENSION_VERSIONS:
            features = frozenset(str(f) for f in advert.get("features") or [])
        elif isinstance(advert, dict):
            self.emit(
                Log(
                    "warning",
                    f"the agent's {EXTENSION} extension version {advert.get('version')!r} "
                    f"is not one Whisperwind knows ({', '.join(map(str, EXTENSION_VERSIONS))}); "
                    "using plain ACP",
                )
            )
        declared = self.adapter.spec.data.get("capabilities") or {}
        for feature, capability in FEATURE_CAPABILITIES.items():
            if declared.get(capability) and feature not in (features or ()):
                self.emit(
                    Log(
                        "warning",
                        f"the harness file declares {capability}, but the agent does not "
                        f"advertise the {EXTENSION} extension's {feature} feature",
                    )
                )
        return features

    def _extension_request(self) -> dict[str, Any]:
        req = self.req
        values = {
            "instructions": req.instructions,
            "output_schema": req.output_schema,
            "max_turns": req.max_turns,
            "budget_usd": req.budget_usd,
            "budget_tokens": req.budget_tokens,
            "effort": req.effort,
            "permissions": req.permissions,
            "allow_tools": req.allow_tools or None,
            "deny_tools": req.deny_tools or None,
        }
        return {key: value for key, value in values.items() if value is not None}

    def _has(self, feature: str) -> bool:
        return self.features is not None and feature in self.features

    def _text(self) -> str:
        req = self.req
        text = req.prompt
        if req.instructions and not self._has("instructions"):
            text = f"# Instructions\n\n{req.instructions}\n\n# Task\n\n{text}"
        if req.output_schema is not None and not self._has("output_schema"):
            text += json_instruction(req.output_schema)
        return text

    # -- what the agent sends -----------------------------------------------------------

    def notice(self, method: str, params: dict[str, Any]) -> None:
        """Session updates count once the prompt is out; `session/load` replays
        the history before that."""
        if method != "session/update" or self.prompt is None:
            return
        update = params.get("update")
        if isinstance(update, dict):
            for event in self._events(update):
                self.emit(event)

    def _events(self, update: dict[str, Any]) -> list[AdapterEvent]:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            if content.get("type") == "text" and content.get("text"):
                self.texts.append(str(content["text"]))
                return [Text(str(content["text"]))]
        elif kind == "tool_call":
            name = str(update.get("name") or update.get("title") or update.get("kind") or "tool")
            self.tools[str(update.get("toolCallId"))] = name
            return [ToolCall(name, str(update.get("title") or ""))]
        elif kind == "tool_call_update" and update.get("status") in ("completed", "failed"):
            name = self.tools.get(str(update.get("toolCallId")), "tool")
            ok = update["status"] == "completed"
            return [ToolResult(name, ok, str(update.get("title") or update["status"]))]
        elif kind == "usage_update":
            cost = update.get("cost")
            if not isinstance(cost, dict) or cost.get("amount") is None:
                return []
            if cost.get("currency", "USD") != "USD":
                return [Log("warning", f"cost reported in {cost.get('currency')}; ignored")]
            self.total_usd = float(cost["amount"])
            return [UsageUpdate(Usage(), self._delta())]
        return []

    def answer(self, method: str, params: dict[str, Any]) -> Any:
        if method != "session/request_permission":
            raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
        call = params.get("toolCall") or {}
        options = [o for o in params.get("options") or [] if isinstance(o, dict)]
        kind = str(call.get("kind") or "other")
        approved = APPROVED_KINDS.get(self.req.permissions)
        tool = str(call.get("name") or call.get("title") or kind)
        if approved is None or kind in approved:
            choice = _option(options, ("allow_once",))
            if choice is not None:
                return {"outcome": {"outcome": "selected", "optionId": choice}}
        reason = f"the {self.req.permissions} profile does not allow {kind} tools"
        self.denials.append(Denial(tool, reason))
        self.emit(PermissionDenied(tool, reason))
        choice = _option(options, ("reject_once", "reject_always"))
        if choice is None:
            return {"outcome": {"outcome": "cancelled"}}
        return {"outcome": {"outcome": "selected", "optionId": choice}}

    # -- the result ------------------------------------------------------------------------

    def _delta(self) -> float | None:
        if self.total_usd is None:
            return None
        session = self.req.session
        previous = session.previous_cost_usd if session.mode != "new" else None
        return max(self.total_usd - float(previous or 0.0), 0.0)

    def result(self, response: Any) -> AgentResult:
        """The result for a prompt response: its stop reason decides, unless the
        extension's result reports a more detailed outcome."""
        response = response if isinstance(response, dict) else {}
        stop = response.get("stopReason")
        result = self._base("succeeded")
        if self.req.output_schema is not None and not self._has("output_schema"):
            result.output = extract_json(result.text)
        stopped = stop == "cancelled" and self.req.stop_reason is not None
        if stopped:
            result.outcome = "cancelled"
        elif stop != "end_turn":
            result.outcome = "failed"
            result.error = ErrorInfo(
                "harness_error", f"the agent stopped: {stop}", {"stop_reason": stop}
            )
        meta = response.get("_meta")
        extension = meta.get(EXTENSION) if isinstance(meta, dict) else None
        if self.features is not None and isinstance(extension, dict):
            self._refine(result, extension, outcome=not stopped)
        return result

    def _refine(self, result: AgentResult, extension: dict[str, Any], outcome: bool) -> None:
        """Fill the result from the extension's result payload."""
        usage = extension.get("usage")
        if isinstance(usage, dict):
            keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")
            result.usage = Usage(**{key: int(usage.get(key) or 0) for key in keys})
        cost = extension.get("cost_usd")
        if result.cost_usd is None and isinstance(cost, (int, float)):
            result.cost_usd = float(cost)  # a usage_update's cost wins
        if isinstance(extension.get("num_turns"), int):
            result.num_turns = extension["num_turns"]
        if extension.get("model"):
            result.model = str(extension["model"])
        if "output" in extension:
            result.output = extension["output"]
        for denial in extension.get("permission_denials") or []:
            if isinstance(denial, dict) and denial.get("tool"):
                reason = str(denial.get("reason") or "")
                result.permission_denials.append(Denial(str(denial["tool"]), reason))
        reported = extension.get("outcome")
        if not outcome or reported not in AGENT_OUTCOMES:
            return
        result.outcome = reported
        error = extension.get("error")
        if reported == "succeeded":
            result.error = None
        elif isinstance(error, dict):
            detail = error.get("detail")
            result.error = ErrorInfo(
                str(error.get("kind") or "harness_error"),
                str(error.get("message") or reported),
                detail if isinstance(detail, dict) else {},
            )
        elif result.error is None:
            result.error = ErrorInfo("harness_error", f"the agent reported {reported}")

    def _base(self, outcome: Any) -> AgentResult:
        return AgentResult(
            outcome,
            text="".join(self.texts),
            session_id=self.session_id,
            cost_usd=self._delta(),
            session_total_usd=self.total_usd,
            harness_version=self.version,
            model=self.req.model,
            permission_denials=list(self.denials),
        )

    def _failed(self, message: str, detail: dict[str, Any] | None = None) -> AgentResult:
        result = self._base("failed")
        result.error = ErrorInfo("harness_error", message, detail or {})
        return result

    def rpc_failure(self, exc: RpcError) -> AgentResult:
        detail: dict[str, Any] = {"code": exc.code}
        if exc.data is not None:
            detail["data"] = exc.data
        message = exc.message
        if exc.code == AUTH_REQUIRED:
            methods = _auth_methods(self.init)
            message = "the agent needs authentication" + (
                f" ({', '.join(methods)})" if methods else ""
            )
        return self._failed(message, detail)

    def no_result(self, exit_code: int | None, stderr_tail: str) -> AgentResult:
        result = self._base("failed")
        message = "the agent exited without answering the prompt"
        if stderr_tail.strip():
            message += f": {stderr_tail.strip()[-300:]}"
        result.error = ErrorInfo("no_result", message, {"exit_code": exit_code})
        return result


def _option(options: list[dict[str, Any]], kinds: tuple[str, ...]) -> str | None:
    for kind in kinds:
        for option in options:
            if option.get("kind") == kind and option.get("optionId") is not None:
                return str(option["optionId"])
    return None


def _auth_methods(init: dict[str, Any]) -> list[str]:
    methods = [m for m in init.get("authMethods") or [] if isinstance(m, dict)]
    return [str(m.get("name") or m.get("id")) for m in methods]


class AcpAdapter(ProcessAdapter):
    name: ClassVar[str] = "acp"

    def __init__(self, spec: HarnessSpec) -> None:
        super().__init__()
        self.spec = spec
        self.name = spec.name  # type: ignore[misc]
        self.binary = spec.data["command"][0]  # type: ignore[misc]
        self.auth_env = tuple(spec.data.get("env") or ())  # type: ignore[misc]
        self.configure({})

    def configure(self, settings: dict[str, Any]) -> None:
        merged = {k: v for k, v in self.spec.data.items() if k in ("tested_versions", "grace")}
        merged.update(settings)
        super().configure(merged)

    def capabilities(self) -> Capabilities:
        declared = self.spec.data.get("capabilities") or {}
        return Capabilities(
            structured_output=bool(declared.get("structured_output", False)),
            session_id="harness",
            resume=bool(declared.get("resume", False)),
            interactive="interactive_command" in self.spec.data,
            cost_usd=bool(declared.get("cost_usd", False)),
            tokens=bool(declared.get("tokens", False)),
            budget_cap=bool(declared.get("budget_cap", False)),
            turn_cap=bool(declared.get("turn_cap", False)),
            tool_rules=bool(declared.get("tool_rules", False)),
            permission_hook=True,
            streaming=True,
            effort=bool(declared.get("effort", False)),
        )

    def command(self, req: AgentRequest) -> list[str]:
        return self._argv()

    def _argv(self) -> list[str]:
        return [self.command_path, *self.spec.data["command"][1:]]

    def interactive_command(self, session_id: str, cwd: str) -> list[str] | None:
        template = self.spec.data.get("interactive_command")
        if not template:
            return None
        return substitute(list(template), {"session_id": session_id, "cwd": cwd})

    async def _spawn(self, argv: list[str], **kwargs: Any) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=MAX_MESSAGE,
            **kwargs,
        )

    async def probe(self) -> Probe:
        """Start the agent, `initialize` it and stop it."""
        try:
            process = await self._spawn(self._argv())
        except OSError:
            return Probe(found=False)
        with open(os.devnull, "w") as sink:
            conn = Connection(process, sink, _refuse, lambda method, params: None, lambda e: None)
            serving = asyncio.ensure_future(conn.serve())
            init: Any = None
            with contextlib.suppress(RpcError, ConnectionLost, asyncio.TimeoutError):
                init = await asyncio.wait_for(
                    conn.call(
                        "initialize",
                        {"protocolVersion": PROTOCOL_VERSION, "clientCapabilities": {}},
                    ),
                    PROBE_TIMEOUT_S,
                )
            await self._end(process, conn)
            await asyncio.gather(serving, return_exceptions=True)
        if not isinstance(init, dict):
            return Probe(found=True, source=str(self.spec.path))
        version = (init.get("agentInfo") or {}).get("version")
        tested = self.settings.get("tested_versions")
        methods = _auth_methods(init)
        return Probe(
            found=True,
            version=version,
            in_tested_range=version_in_range(version, tested) if version and tested else None,
            auth_hint=f"auth: {', '.join(methods)}" if methods else None,
            source=str(self.spec.path),
        )

    async def run(self, req: AgentRequest, emit: Callable[[AdapterEvent], None]) -> AgentResult:
        attempt_dir = Path(req.attempt_dir)
        argv = self.command(req) + [str(a) for a in req.options.get("extra_args", [])]
        try:
            process = await self._spawn(argv, cwd=req.cwd, env=req.env)
        except OSError as exc:
            return AgentResult("failed", error=ErrorInfo("spawn_failed", f"{argv[0]}: {exc}"))
        tail: list[bytes] = []
        errors = asyncio.ensure_future(
            _read_stderr(process.stderr, attempt_dir / "stderr.log", tail)
        )
        turn = Turn(self, req, emit)
        result: AgentResult | None = None
        stopped_by: str | None = None
        with open(attempt_dir / "stream.jsonl", "w", encoding="utf-8") as transcript:
            conn = Connection(process, transcript, turn.answer, turn.notice, emit)
            serving = asyncio.ensure_future(conn.serve())
            try:
                result = await turn.drive(conn)
            except ConnectionLost:
                result = None
            except asyncio.CancelledError:
                result, stopped_by = await asyncio.shield(self._cancel(turn, conn, process))
            if stopped_by is None:
                await self._end(process, conn)
            await asyncio.gather(serving, errors, return_exceptions=True)
        if result is None:
            text = b"".join(tail).decode("utf-8", errors="replace")
            result = turn.no_result(process.returncode, text)
        if stopped_by is not None or req.stop_reason is not None:
            result.stopped_by = stopped_by  # type: ignore[assignment]
            result = _stopped_outcome(req, result)
        version = turn.version
        tested = self.settings.get("tested_versions")
        if version and tested and not version_in_range(version, tested):
            emit(Log("warning", f"{self.name} {version} is outside tested_versions {tested}"))
        return result

    async def _cancel(
        self, turn: Turn, conn: Connection, process: asyncio.subprocess.Process
    ) -> tuple[AgentResult | None, str | None]:
        """Ask the agent to cancel the prompt and wait a grace period for its
        response; then stop the process group."""
        prompt = turn.prompt
        if prompt is not None and not prompt.done():
            conn.notify("session/cancel", {"sessionId": turn.session_id})
            with contextlib.suppress(asyncio.TimeoutError, RpcError, ConnectionLost):
                await asyncio.wait_for(asyncio.shield(prompt), self.grace)
        if prompt is not None and prompt.done():
            failure = prompt.exception()
            if failure is None:
                return turn.result(prompt.result()), None
            if isinstance(failure, RpcError):
                return turn.rpc_failure(failure), None
        return None, await self._stop(process, interrupt_wait=TERM_WAIT_S)

    async def _end(self, process: asyncio.subprocess.Process, conn: Connection) -> None:
        """Close stdin, which ends an ACP agent, and stop it if it lingers."""
        conn.close()
        try:
            await asyncio.wait_for(process.wait(), TERM_WAIT_S)
        except asyncio.TimeoutError:
            await self._stop(process, interrupt_wait=TERM_WAIT_S)


def _refuse(method: str, params: dict[str, Any]) -> Any:
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
