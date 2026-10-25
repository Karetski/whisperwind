"""The first DBOS slice: one sequential flow with `agent` and `shell` steps in a
loop, on the fake harness, on DBOS with SQLite.

Spike code, not the kernel: phase P1 ports what survives into `src/whisperwind/`.
One process runs one run:

    python spikes/dbos/dbos_slice.py DB RUN_ID

It starts the run, or recovers it when the database already holds it, and prints
the flow's result as JSON. Three environment variables drive the crash tests:
SPIKE_CRASH_AT=N kills the process at the Nth crash point, SPIKE_TRACE names a
file that lists every crash point passed, and SPIKE_LEDGER names a file that
records every step execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import threading
from collections.abc import Awaitable, Callable
from contextlib import closing
from dataclasses import dataclass
from typing import Any, TypeVar

from dbos import DBOS, SetWorkflowID
from dbos._error import DBOSNonExistentWorkflowError

# Private: the crash points wrap the system database's writes, because DBOS's own
# debug triggers fire only after a step commit and after a workflow starts.
from dbos._sys_db import SystemDatabase

from whisperwind.adapters import AdapterEvent, AgentRequest, SessionSpec, SessionStarted
from whisperwind.adapters.fake import FakeAdapter

CRASH_EXIT = 77
DB_WRITES = ("init_workflow", "record_operation_result", "update_workflow_outcome")

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

_db = ""
_passed = 0
_lock = threading.Lock()


def crash_point(label: str) -> None:
    """Count a crash point, and kill the process if SPIKE_CRASH_AT names it."""
    global _passed
    with _lock:
        _passed += 1
        if trace := os.environ.get("SPIKE_TRACE"):
            with open(trace, "a") as f:
                f.write(f"{_passed} {label}\n")
        if os.environ.get("SPIKE_CRASH_AT") == str(_passed):
            os._exit(CRASH_EXIT)


def _with_crash_points(name: str) -> None:
    write = getattr(SystemDatabase, name)

    def wrapped(self: SystemDatabase, *args: Any, **kwargs: Any) -> Any:
        crash_point(f"before {name}")
        result = write(self, *args, **kwargs)
        crash_point(f"after {name}")
        return result

    setattr(SystemDatabase, name, wrapped)


for _name in DB_WRITES:
    _with_crash_points(_name)


def _ledger(step: int, kind: str) -> None:
    if ledger := os.environ.get("SPIKE_LEDGER"):
        with open(ledger, "a") as f:
            f.write(f"{step} {kind}\n")


def write_event(run_id: str, step: int, kind: str, data: dict[str, Any]) -> None:
    """Append a fact DBOS doesn't record to the event table in DBOS's database."""
    crash_point(f"before event {kind}")
    with closing(sqlite3.connect(_db, timeout=30)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS whw_events"
            " (id INTEGER PRIMARY KEY, run_id TEXT, step INTEGER, kind TEXT, data TEXT)"
        )
        conn.execute(
            "INSERT INTO whw_events (run_id, step, kind, data) VALUES (?, ?, ?, ?)",
            (run_id, step, kind, json.dumps(data)),
        )
    crash_point(f"after event {kind}")


# -- primitives ---------------------------------------------------------------------


def flow(fn: F) -> F:
    return DBOS.workflow(name=fn.__name__)(fn)


@DBOS.step()
async def _agent_step(prompt: str, reply: str) -> dict[str, Any]:
    run_id, step = DBOS.workflow_id or "", DBOS.step_id or 0
    _ledger(step, "agent")

    def emit(event: AdapterEvent) -> None:
        if isinstance(event, SessionStarted):
            write_event(run_id, step, "session_started", {"session_id": event.session_id})

    request = AgentRequest(
        run_id=run_id,
        node_id=f"step-{step}",
        visit=1,
        attempt=1,
        prompt=prompt,
        instructions=None,
        cwd=".",
        add_dirs=[],
        model=None,
        effort=None,
        permissions="read-only",
        allow_tools=[],
        deny_tools=[],
        output_schema=None,
        # A session ID derived from the run and step survives a rerun of the step.
        session=SessionSpec(new_id=f"{run_id}-{step}"),
        max_turns=None,
        budget_usd=None,
        budget_tokens=None,
        bare=True,
        env={},
        options={"responses": [{"text": reply}]},
        attempt_dir=".",
    )
    result = await FakeAdapter().run(request, emit)
    return {"text": result.text, "session_id": result.session_id}


async def agent(prompt: str, *, reply: str) -> str:
    """Run an agent step on the fake harness, which answers with `reply`."""
    return str((await _agent_step(prompt, reply))["text"])


@dataclass(frozen=True)
class ShellResult:
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@DBOS.step()
async def _shell_step(argv: list[str]) -> dict[str, Any]:
    _ledger(DBOS.step_id or 0, "shell")
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    output, _ = await process.communicate()
    return {"exit_code": process.returncode, "output": output.decode()}


async def shell(argv: list[str]) -> ShellResult:
    return ShellResult(**await _shell_step(argv))


# -- the flow -----------------------------------------------------------------------


@flow
async def fix_until_green(goal: str, max_rounds: int = 3) -> str:
    plan = await agent(f"Plan this change: {goal}", reply="add a failing test, then fix it")
    for attempt in range(max_rounds):
        await agent(f"Implement: {plan} (attempt {attempt + 1})", reply="done")
        # The tests fail on the first attempt and pass on the second.
        tests = await shell(["sh", "-c", f"exit $(( {attempt} < 1 ))"])
        if tests.ok:
            return f"green after {attempt + 1} attempts: {plan}"
    return f"still failing after {max_rounds} attempts"


async def main(db: str, run_id: str) -> None:
    global _db
    _db = db
    # The run ID doubles as the executor ID, so launching recovers only this run.
    DBOS(
        config={
            "name": "whisperwind-spike",
            "system_database_url": f"sqlite:///{db}",
            "executor_id": run_id,
            "log_level": "WARNING",
            # Shutdown waits out one poll of the notification listener (1 s by default).
            "notification_listener_polling_interval_sec": 0.1,
        }
    )
    DBOS.launch()
    try:
        try:
            handle = await DBOS.retrieve_workflow_async(run_id)
        except DBOSNonExistentWorkflowError:
            with SetWorkflowID(run_id):
                handle = await DBOS.start_workflow_async(fix_until_green, "add rate limiting")
        print(json.dumps(await handle.get_result()))
    finally:
        DBOS.destroy()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
