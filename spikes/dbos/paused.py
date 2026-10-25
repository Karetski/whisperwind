"""Editing a flow while its run is paused (V3), and human waits that outlive the
run's process (V4).

    python spikes/dbos/paused.py run DB RUN_ID FLOW_FILE [VERSION]
    python spikes/dbos/paused.py respond DB RUN_ID ANSWER

`run` starts or resumes the run of the flow `main` in FLOW_FILE, with DBOS's
application version pinned to VERSION if given. A run still waiting after
SPIKE_WAIT seconds (2 by default) exits with WAITING_EXIT, and no process stays
behind. A replay that diverges from the record exits with DIVERGED_EXIT without
recording an outcome, so the run stays resumable once the edit is reverted.
`respond` answers a waiting `human` step from another process. Paths are
provisional.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from typing import Any, NoReturn

from dbos import DBOS, DBOSClient
from dbos._error import DBOSUnexpectedStepError
from dbos_slice import ShellResult, flow, ledger, run
from dbos_slice import shell as _shell

WAITING_EXIT = 4
DIVERGED_EXIT = 5
HUMAN_TOPIC = "human"
HUMAN_TIMEOUT = 3 * 86400

__all__ = ["agent", "flow", "human", "shell"]

_ordinals: Counter[tuple[str, str]] = Counter()


def diverge(message: str) -> NoReturn:
    """Stop the run process without an outcome: DBOS can't resume a workflow that ERRORed."""
    print(f"divergence at {message}", file=sys.stderr, flush=True)
    os._exit(DIVERGED_EXIT)


def _path(kind: str) -> str:
    workflow = DBOS.workflow_id or ""
    ordinal = _ordinals[(workflow, kind)]
    _ordinals[(workflow, kind)] += 1
    return f"{kind}#{ordinal}"


def fingerprint(kind: str, **options: Any) -> str:
    """A hash of what a step was asked to do, so a replay can tell it was edited."""
    text = json.dumps({"kind": kind, **options}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@DBOS.step()
async def _fingerprinted_agent_step(prompt: str, reply: str, fingerprint: str) -> dict[str, str]:
    ledger(DBOS.step_id or 0, "agent")
    return {"text": reply, "fingerprint": fingerprint}


async def agent(prompt: str, *, reply: str) -> str:
    """An agent step that reports by path when a replay's prompt differs from the record."""
    path = _path("agent")
    expected = fingerprint("agent", prompt=prompt)
    try:
        result = await _fingerprinted_agent_step(prompt, reply, expected)
    except DBOSUnexpectedStepError as error:
        diverge(f"{path}: a different step was recorded here ({error})")
    if result["fingerprint"] != expected:
        diverge(f"{path}: prompt changed since the run paused")
    return result["text"]


async def shell(argv: list[str]) -> ShellResult:
    path = _path("shell")
    try:
        return await _shell(argv)
    except DBOSUnexpectedStepError as error:
        diverge(f"{path}: a different step was recorded here ({error})")


async def human(question: str) -> str:
    """Wait for an answer sent by `respond`, for up to HUMAN_TIMEOUT seconds."""
    path = _path("human")
    try:
        answer = await DBOS.recv_async(HUMAN_TOPIC, timeout_seconds=HUMAN_TIMEOUT)
    except DBOSUnexpectedStepError as error:
        diverge(f"{path}: a different step was recorded here ({error})")
    if answer is None:
        raise TimeoutError(f"{path}: no answer to {question!r}")
    return str(answer)


def load_flow(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("flow_file", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


async def main(argv: list[str]) -> int:
    command, db, run_id = argv[:3]
    if command == "respond":
        client = DBOSClient(system_database_url=f"sqlite:///{db}")
        await client.send_async(run_id, argv[3], HUMAN_TOPIC)
        client.destroy()
        return 0
    workflow = load_flow(argv[3])
    version = argv[4] if len(argv) > 4 else None
    wait = float(os.environ.get("SPIKE_WAIT", "2"))
    try:
        result = await run(
            db, run_id, lambda: DBOS.start_workflow_async(workflow), version=version, wait=wait
        )
    except TimeoutError:
        return WAITING_EXIT
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    # Flow files import this module by name; let them find the running copy.
    sys.modules["paused"] = sys.modules["__main__"]
    sys.exit(asyncio.run(main(sys.argv[1:])))
