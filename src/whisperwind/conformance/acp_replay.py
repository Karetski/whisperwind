"""Stub ACP agent for the conformance kit: replays a recorded two-way transcript.

Usage: python acp_replay.py <transcript.jsonl> <report file>

Each transcript line is `{"from": "client" | "agent", "message": ..., "match": [...]}`.
For a client line, the stub reads the client's next message and checks it: a
request or notification must have the recorded method, a response must answer
the recorded request, and each JSON pointer in `match` must resolve to the same
value in both. Agent lines are sent as recorded, with a response's ID mapped to
the ID the client actually used. On a mismatch the stub writes what differed to
the report file and exits with status 3.

`{"from": "agent", "exit": <status>}` makes the agent exit there. After the
last line the stub waits for the client to close its side.
"""

from __future__ import annotations

import json
import sys
from typing import Any

MISMATCH = 3


def resolve(document: Any, pointer: str) -> Any:
    """The value at a JSON pointer, or a marker for none."""
    value = document
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return "<absent>"
    return value


def describe(message: dict[str, Any]) -> str:
    if "method" in message:
        return f"{message['method']} {'request' if 'id' in message else 'notification'}"
    return f"response to request {message.get('id')!r}"


def difference(recorded: dict[str, Any], actual: Any, pointers: list[str]) -> str | None:
    if actual is None:
        return f"expected {describe(recorded)}, but the client closed its side"
    if not isinstance(actual, dict):
        return f"expected {describe(recorded)}, got {actual!r}"
    if "method" in recorded:
        same = actual.get("method") == recorded["method"] and ("id" in actual) == ("id" in recorded)
    else:
        same = "method" not in actual and actual.get("id") == recorded.get("id")
    if not same:
        return f"expected {describe(recorded)}, got {describe(actual)}"
    for pointer in pointers:
        want, got = resolve(recorded, pointer), resolve(actual, pointer)
        if want != got:
            return f"{describe(recorded)}: {pointer} expected {want!r}, got {got!r}"
    return None


def main() -> None:
    transcript, report = sys.argv[1], sys.argv[2]
    with open(transcript, encoding="utf-8") as file:
        entries = [json.loads(line) for line in file if line.strip()]
    ids: dict[Any, Any] = {}  # recorded client request ID -> the ID the client used
    for entry in entries:
        if "exit" in entry:
            sys.exit(int(entry["exit"]))
        recorded = entry["message"]
        if entry["from"] == "agent":
            if "method" not in recorded and recorded.get("id") in ids:
                recorded = {**recorded, "id": ids[recorded["id"]]}
            sys.stdout.write(json.dumps(recorded) + "\n")
            sys.stdout.flush()
            continue
        line = sys.stdin.readline()
        actual = json.loads(line) if line.strip() else None
        problem = difference(recorded, actual, list(entry.get("match") or []))
        if problem is not None:
            with open(report, "w", encoding="utf-8") as file:
                file.write(problem)
            sys.exit(MISMATCH)
        if "method" in recorded and "id" in recorded:
            ids[recorded["id"]] = actual["id"]  # type: ignore[index]
    sys.stdin.read()  # until the client closes its side


if __name__ == "__main__":
    main()
