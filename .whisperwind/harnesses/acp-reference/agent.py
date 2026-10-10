#!/usr/bin/env python3
"""A reference Agent Client Protocol (v1) agent around a scripted model.

Whisperwind's tests drive their ACP adapter against it, and it is a starting
point for a harness of your own: it answers every message Whisperwind sends,
with the shapes Whisperwind expects back. It uses only the standard library.

    python3 agent.py [--script SCRIPT.json] [--state DIR]

The script (JSON) says what the agent advertises and what its "model" does for
each prompt. Every key is optional:

    {
      "agent_info": {"name": "acp-reference", "version": "1.0.0"},
      "load_session": true,            # advertise session/load
      "resume": true,                  # advertise session/resume
      "additional_directories": true,  # accept additionalDirectories
      "auth_methods": [{"id": "api-key", "name": "API key"}],
      "auth_required": false,          # refuse new sessions with -32000
      "modes": ["ask", "auto"],        # session modes, the first is current
      "modes_as_config": false,        # expose the modes as a `mode` config option
      "config_options": [{"id": "model", "category": "model", "values": ["small", "large"]}],
      "extension": {"version": 1, "features": ["output_schema", "usage", "outcome"]},
      "turns": [{"when": "text in the prompt", "steps": [...], "stop": "end_turn",
                 "result": {"outcome": "succeeded", "output": {...}}}]
    }

`extension` advertises Whisperwind's ACP extension, under the `_meta` key
`whisperwind.karetski.com`: Whisperwind then sends the node's settings in the
prompt's `_meta` (instructions, output_schema, max_turns, budget_usd,
budget_tokens, effort, permissions, allow_tools, deny_tools), and reads a
turn's `result` back from the response's `_meta` (outcome, output, num_turns,
model, usage, cost_usd, permission_denials, error). Each key travels only
when the agent advertises the feature that carries it (see the README). A
real agent fills the result from its run; this one returns what the script
says.

The first turn whose `when` occurs in the prompt (or that has no `when`)
answers it. Its steps run in order:

    {"text": "..."}                          an agent_message_chunk
    {"tool": "Edit a.txt", "kind": "edit"}   a tool call, asking permission first
                                             unless "ask": false; "options" lists
                                             the option kinds offered (default:
                                             allow_once, allow_always, reject_once)
    {"usage": {"used": 10, "size": 100, "cost": 0.01}}   a usage_update
    {"wait_for_cancel": true}                stop with `cancelled` at session/cancel
    {"ignore_cancel": true}                  hang until the process is stopped
    {"stderr": "..."}                        a line on stderr
    {"exit": 3}                              exit mid-turn, without a response
    {"error": {"code": -32603, "message": "..."}}   answer the prompt with an error

Session histories are kept under --state, so a later process can load (with
history replay) or resume a session.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from typing import Any

PROTOCOL_VERSION = 1
EXTENSION = "whisperwind.karetski.com"
AUTH_REQUIRED = -32000
RESOURCE_NOT_FOUND = -32002
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
# Without --script: answers the prompts of the conformance kit's live suite
# (`whw adapter test acp-reference --live`), which then passes at no cost.
DEFAULT_SCRIPT: dict[str, Any] = {
    "load_session": True,
    "resume": True,
    "extension": {"version": 1, "features": ["outcome"]},
    "turns": [
        {"when": "Count slowly", "steps": [{"text": "1\n"}, {"wait_for_cancel": True}]},
        {
            "steps": [{"text": '{"word": "ready"}'}],
            "result": {"outcome": "succeeded", "num_turns": 1},
        },
    ],
}


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Agent:
    def __init__(self, script: dict[str, Any], state: str) -> None:
        self.script = script
        self.state = state
        self.next_id = 0
        self.cancelled = False
        self.sessions: dict[str, dict[str, Any]] = {}  # live settings per session

    # -- the wire: one JSON-RPC message per line on stdio --------------------------

    def send(self, message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        sys.stdout.flush()

    def receive(self) -> dict[str, Any]:
        line = sys.stdin.readline()
        if not line:
            sys.exit(0)  # the client closed stdin: shut down
        message: dict[str, Any] = json.loads(line)
        return message

    def update(self, session_id: str, update: dict[str, Any]) -> None:
        self.send(
            {"method": "session/update", "params": {"sessionId": session_id, "update": update}}
        )

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a request to the client and wait for its response, noting a
        session/cancel that arrives meanwhile."""
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("id") == request_id and "method" not in message:
                return message
            self.handle(message)

    def serve(self) -> None:
        while True:
            self.handle(self.receive())

    def handle(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method is None:
            return  # a response nobody waits for
        if "id" not in message:
            if method == "session/cancel":
                self.cancelled = True
            return  # unknown notifications are ignored
        handler = getattr(self, "on_" + method.replace("/", "_"), None)
        try:
            if handler is None:
                raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
            self.send({"id": message["id"], "result": handler(message.get("params") or {})})
        except RpcError as exc:
            self.send({"id": message["id"], "error": {"code": exc.code, "message": exc.message}})

    # -- lifecycle -----------------------------------------------------------------------

    def on_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        script = self.script
        session: dict[str, Any] = {}
        if script.get("resume"):
            session["resume"] = {}
        if script.get("additional_directories"):
            session["additionalDirectories"] = {}
        capabilities: dict[str, Any] = {
            "loadSession": bool(script.get("load_session")),
            "promptCapabilities": {},
            "sessionCapabilities": session,
        }
        if "extension" in script:
            capabilities["_meta"] = {EXTENSION: script["extension"]}
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentCapabilities": capabilities,
            "authMethods": script.get("auth_methods", []),
            "agentInfo": script.get("agent_info", {"name": "acp-reference", "version": "1.0.0"}),
        }

    def on_session_new(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.script.get("auth_required"):
            raise RpcError(AUTH_REQUIRED, "Authentication required")
        session_id = str(uuid.uuid4())
        self._save(session_id, [])
        return {"sessionId": session_id, **self._open(session_id)}

    def on_session_load(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params["sessionId"]
        for entry in self._history(session_id):
            kind = "user_message_chunk" if entry["role"] == "user" else "agent_message_chunk"
            content = {"type": "text", "text": entry["text"]}
            self.update(session_id, {"sessionUpdate": kind, "content": content})
        return self._open(session_id)

    def on_session_resume(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params["sessionId"]
        self._history(session_id)  # must exist
        return self._open(session_id)

    def _open(self, session_id: str) -> dict[str, Any]:
        """Settings start at their defaults in every process."""
        modes = list(self.script.get("modes") or [])
        options = [dict(o) for o in self.script.get("config_options") or []]
        if modes and self.script.get("modes_as_config"):
            options.append({"id": "mode", "category": "mode", "values": modes})
        self.sessions[session_id] = {
            "mode": modes[0] if modes else None,
            "config": {o["id"]: o["values"][0] for o in options},
            "options": options,
        }
        result: dict[str, Any] = {"configOptions": self._config_options(session_id)}
        if modes and not self.script.get("modes_as_config"):
            result["modes"] = {
                "currentModeId": modes[0],
                "availableModes": [{"id": m, "name": m.title()} for m in modes],
            }
        return result

    def _config_options(self, session_id: str) -> list[dict[str, Any]]:
        live = self.sessions[session_id]
        return [
            {
                "id": option["id"],
                "name": option["id"].title(),
                "category": option.get("category"),
                "type": "select",
                "currentValue": live["config"][option["id"]],
                "options": [{"value": v, "name": v} for v in option["values"]],
            }
            for option in live["options"]
        ]

    def on_session_set_config_option(self, params: dict[str, Any]) -> dict[str, Any]:
        live = self._live(params["sessionId"])
        option = next((o for o in live["options"] if o["id"] == params.get("configId")), None)
        if option is None or params.get("value") not in option["values"]:
            raise RpcError(INVALID_PARAMS, f"no such option value: {params.get('value')!r}")
        live["config"][option["id"]] = params["value"]
        return {"configOptions": self._config_options(params["sessionId"])}

    def on_session_set_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        live = self._live(params["sessionId"])
        if params.get("modeId") not in (self.script.get("modes") or []):
            raise RpcError(INVALID_PARAMS, f"no such mode: {params.get('modeId')!r}")
        live["mode"] = params["modeId"]
        return {}

    # -- the scripted model --------------------------------------------------------------

    def on_session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params["sessionId"]
        self._live(session_id)
        prompt = "".join(b.get("text", "") for b in params.get("prompt") or [])
        turn = next(
            (t for t in self.script.get("turns") or [] if t.get("when", "") in prompt), None
        ) or {"steps": []}
        self.cancelled = False
        said: list[str] = []
        for step in turn.get("steps") or []:
            if self.cancelled:
                break
            self._step(session_id, step, said)
        history = self._history(session_id)
        history += [{"role": "user", "text": prompt}, {"role": "agent", "text": "".join(said)}]
        self._save(session_id, history)
        response: dict[str, Any] = {
            "stopReason": "cancelled" if self.cancelled else turn.get("stop", "end_turn")
        }
        if "extension" in self.script and "result" in turn:
            response["_meta"] = {EXTENSION: turn["result"]}
        return response

    def _step(self, session_id: str, step: dict[str, Any], said: list[str]) -> None:
        if "text" in step:
            said.append(step["text"])
            content = {"type": "text", "text": step["text"]}
            self.update(session_id, {"sessionUpdate": "agent_message_chunk", "content": content})
        elif "tool" in step:
            self._tool(session_id, step)
        elif "usage" in step:
            usage = step["usage"]
            update = {"sessionUpdate": "usage_update", "used": usage.get("used", 0)}
            update["size"] = usage.get("size", 0)
            if "cost" in usage:
                update["cost"] = {"amount": usage["cost"], "currency": "USD"}
            self.update(session_id, update)
        elif step.get("wait_for_cancel"):
            while not self.cancelled:
                self.handle(self.receive())
        elif step.get("ignore_cancel"):
            while True:
                time.sleep(3600)
        elif "stderr" in step:
            print(step["stderr"], file=sys.stderr, flush=True)
        elif "exit" in step:
            sys.exit(int(step["exit"]))
        elif "error" in step:
            raise RpcError(int(step["error"]["code"]), str(step["error"]["message"]))

    def _tool(self, session_id: str, step: dict[str, Any]) -> None:
        self.next_id += 1
        call = {"toolCallId": f"call-{self.next_id}", "title": step["tool"], "kind": step["kind"]}
        self.update(session_id, {"sessionUpdate": "tool_call", "status": "pending", **call})
        allowed = True
        if step.get("ask", True):
            options = [
                {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                {"optionId": "always", "name": "Always allow", "kind": "allow_always"},
                {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
            ]
            if "options" in step:
                options = [o for o in options if o["kind"] in step["options"]]
            answer = self.call(
                "session/request_permission",
                {"sessionId": session_id, "toolCall": call, "options": options},
            )
            outcome = (answer.get("result") or {}).get("outcome") or {}
            allowed = outcome.get("outcome") == "selected" and outcome.get("optionId") in (
                "allow",
                "always",
            )
        status = "completed" if allowed else "failed"
        update = {"sessionUpdate": "tool_call_update", "toolCallId": call["toolCallId"]}
        self.update(session_id, {**update, "status": status})

    # -- sessions ------------------------------------------------------------------------

    def _live(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise RpcError(RESOURCE_NOT_FOUND, f"no open session {session_id}")
        return self.sessions[session_id]

    def _path(self, session_id: str) -> str:
        return os.path.join(self.state, f"{session_id}.json")

    def _history(self, session_id: str) -> list[dict[str, str]]:
        try:
            with open(self._path(session_id), encoding="utf-8") as file:
                history: list[dict[str, str]] = json.load(file)
                return history
        except (OSError, ValueError):
            raise RpcError(RESOURCE_NOT_FOUND, f"no session {session_id}") from None

    def _save(self, session_id: str, history: list[dict[str, str]]) -> None:
        os.makedirs(self.state, exist_ok=True)
        with open(self._path(session_id), "w", encoding="utf-8") as file:
            json.dump(history, file)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--script", help="what to advertise and answer (JSON)")
    parser.add_argument(
        "--state",
        default=os.path.join(tempfile.gettempdir(), "acp-reference"),
        help="where session histories are kept",
    )
    args = parser.parse_args()
    script = DEFAULT_SCRIPT
    if args.script:
        with open(args.script, encoding="utf-8") as file:
            script = json.load(file)
    Agent(script, args.state).serve()


if __name__ == "__main__":
    main()
