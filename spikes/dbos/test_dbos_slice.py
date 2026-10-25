"""The first DBOS slice resumes after a kill at any crash point, with the same
result and without rerunning a step whose result was checkpointed."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from dbos_slice import CRASH_EXIT

SLICE = Path(__file__).with_name("dbos_slice.py")
RUN_ID = "run-1"
RESULT = "green after 2 attempts: add a failing test, then fix it"
STEPS = [1, 2, 3, 4, 5]  # agent, agent, shell, agent, shell


def run_slice(
    workdir: Path, crash_at: int | None = None, trace: bool = False
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SPIKE_LEDGER": str(workdir / "ledger")}
    env.pop("SPIKE_CRASH_AT", None)
    env.pop("SPIKE_TRACE", None)
    if crash_at is not None:
        env["SPIKE_CRASH_AT"] = str(crash_at)
    if trace:
        env["SPIKE_TRACE"] = str(workdir / "trace")
    return subprocess.run(
        [sys.executable, str(SLICE), str(workdir / "run.sqlite"), RUN_ID],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def ledger(workdir: Path) -> list[int]:
    path = workdir / "ledger"
    return [int(line.split()[0]) for line in path.read_text().splitlines()] if path.exists() else []


def query(workdir: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    db = workdir / "run.sqlite"
    if not db.exists():
        return []
    with closing(sqlite3.connect(db)) as conn:
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:  # the table doesn't exist yet
            return []


def checkpointed_steps(workdir: Path) -> set[int]:
    sql = "SELECT function_id FROM operation_outputs WHERE workflow_uuid = ?"
    rows = query(workdir, sql, RUN_ID)
    return {int(str(row[0])) for row in rows}


def session_events(workdir: Path) -> list[int]:
    rows = query(workdir, "SELECT step FROM whw_events WHERE kind = 'session_started'")
    return [int(str(row[0])) for row in rows]


def test_given_a_clean_run_when_it_finishes_then_every_step_ran_once(tmp_path: Path) -> None:
    # When
    done = run_slice(tmp_path)

    # Then
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == RESULT
    assert ledger(tmp_path) == STEPS
    assert session_events(tmp_path) == [1, 2, 4]
    status = query(tmp_path, "SELECT status FROM workflow_status WHERE workflow_uuid = ?", RUN_ID)
    assert status == [("SUCCESS",)]


def test_given_a_kill_at_any_crash_point_when_resumed_then_no_checkpointed_step_reruns(
    tmp_path: Path,
) -> None:
    # Given: the crash points a clean run passes
    clean = tmp_path / "clean"
    clean.mkdir()
    assert run_slice(clean, trace=True).returncode == 0
    points = (clean / "trace").read_text().splitlines()

    failures = []
    for n, point in enumerate(points, start=1):
        workdir = tmp_path / f"crash-{n}"
        workdir.mkdir()

        # When: the run is killed at point n, then resumed
        crashed = run_slice(workdir, crash_at=n)
        checkpointed = checkpointed_steps(workdir)
        executed = len(ledger(workdir))
        resumed = run_slice(workdir)

        # Then
        problems = []
        if crashed.returncode != CRASH_EXIT:
            problems.append(f"crash run exited {crashed.returncode}: {crashed.stderr[-500:]}")
        if resumed.returncode != 0 or json.loads(resumed.stdout or "null") != RESULT:
            problems.append(f"resume exited {resumed.returncode}: {resumed.stderr[-500:]}")
        rerun = set(ledger(workdir)[executed:]) & checkpointed
        if rerun:
            problems.append(f"checkpointed steps ran again: {sorted(rerun)}")
        if set(ledger(workdir)) != set(STEPS):
            problems.append(f"steps executed: {ledger(workdir)}")
        duplicated = {s for s in session_events(workdir) if session_events(workdir).count(s) > 1}
        if duplicated & checkpointed:
            problems.append(f"checkpointed steps wrote events twice: {sorted(duplicated)}")
        if problems:
            failures.append(f"point {point}: " + "; ".join(problems))

    assert not failures, "\n".join(failures)
