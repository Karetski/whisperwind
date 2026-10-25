"""The crash-injection harness (V8): kill a run at every crash point a clean run
passes, resume it in a new process, and compare with the uninterrupted run.

A flow is described by the argv that runs it against a working directory and the
result it returns. The run's database is `run.sqlite` and its ledger `ledger` in
that directory. Each kill is checked for:

- the resumed run returning the uninterrupted run's result;
- no step whose checkpoint was committed before the kill running again;
- every rerun agent step that had started a harness session resuming it;
- no checkpointed step's event being written twice.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dbos_slice import CRASH_EXIT

Step = tuple[str, int]  # (workflow ID, DBOS step number)


@dataclass(frozen=True)
class Flow:
    argv: Callable[[Path], list[str]]
    result: Any


def run(
    flow: Flow, workdir: Path, crash_at: int | None = None, trace: bool = False
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SPIKE_LEDGER": str(workdir / "ledger")}
    for name in ("SPIKE_CRASH_AT", "SPIKE_TRACE"):
        env.pop(name, None)
    if crash_at is not None:
        env["SPIKE_CRASH_AT"] = str(crash_at)
    if trace:
        env["SPIKE_TRACE"] = str(workdir / "trace")
    return subprocess.run(flow.argv(workdir), env=env, capture_output=True, text=True, timeout=120)


def ledger(workdir: Path) -> list[list[str]]:
    """Step executions: step number, kind, workflow ID, process ID, start time."""
    path = workdir / "ledger"
    return [line.split() for line in path.read_text().splitlines()] if path.exists() else []


def _rows(workdir: Path, sql: str) -> list[tuple[Any, ...]]:
    db = workdir / "run.sqlite"
    if not db.exists():
        return []
    with closing(sqlite3.connect(db)) as conn:
        try:
            return conn.execute(sql).fetchall()
        except sqlite3.OperationalError:  # the table doesn't exist yet
            return []


def checkpointed(workdir: Path) -> set[Step]:
    return {
        (str(w), int(s))
        for w, s in _rows(workdir, "SELECT workflow_uuid, function_id FROM operation_outputs")
    }


def sessions(workdir: Path) -> list[Step]:
    rows = _rows(workdir, "SELECT run_id, step FROM whw_events WHERE kind = 'session_started'")
    return [(str(w), int(s)) for w, s in rows]


def crash_points(flow: Flow, workdir: Path) -> list[str]:
    """The crash points an uninterrupted run passes, in order."""
    clean = run(flow, workdir, trace=True)
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout) == flow.result
    return (workdir / "trace").read_text().splitlines()


def kill_and_resume(flow: Flow, workdir: Path, point: int) -> list[str]:
    """Kill a fresh run at one crash point, resume it, and return what went wrong."""
    crashed = run(flow, workdir, crash_at=point)
    saved, started = checkpointed(workdir), set(sessions(workdir))
    executed = len(ledger(workdir))
    resumed = run(flow, workdir)

    problems = []
    if crashed.returncode != CRASH_EXIT:
        problems.append(f"the crash run exited {crashed.returncode}: {crashed.stderr[-300:]}")
    if resumed.returncode != 0 or json.loads(resumed.stdout or "null") != flow.result:
        problems.append(f"the resume exited {resumed.returncode}: {resumed.stderr[-300:]}")
    reruns = [(line[2], int(line[0]), line[1]) for line in ledger(workdir)[executed:]]
    if again := sorted({(w, s) for w, s, _ in reruns} & saved):
        problems.append(f"checkpointed steps ran again: {again}")
    if restarted := sorted(
        (w, s) for w, s, kind in reruns if (w, s) in started and kind == "agent"
    ):
        problems.append(f"steps started a new session instead of resuming theirs: {restarted}")
    counts = Counter(sessions(workdir))
    if doubled := sorted(step for step, n in counts.items() if n > 1 and step in saved):
        problems.append(f"checkpointed steps wrote their session event twice: {doubled}")
    return problems


def check_every_crash_point(flow: Flow, tmp_path: Path) -> list[str]:
    """Kill and resume at every crash point; return one line per failing point."""
    (tmp_path / "clean").mkdir()
    points = crash_points(flow, tmp_path / "clean")
    failures = []
    for n, point in enumerate(points, start=1):
        workdir = tmp_path / f"crash-{n}"
        workdir.mkdir()
        if problems := kill_and_resume(flow, workdir, n):
            failures.append(f"point {n} ({point}): " + "; ".join(problems))
    return failures
