"""The first DBOS slice runs a sequential flow with each step once, records a
session event per agent step, and ends its workflow in SUCCESS. Its behavior
under a kill is in test_crash_suite.py."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

SLICE = Path(__file__).with_name("dbos_slice.py")
RUN_ID = "run-1"
RESULT = "green after 2 attempts: add a failing test, then fix it"
STEPS = [1, 2, 3, 4, 5]  # agent, agent, shell, agent, shell


def run_slice(workdir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SPIKE_LEDGER": str(workdir / "ledger")}
    env.pop("SPIKE_CRASH_AT", None)
    return subprocess.run(
        [sys.executable, str(SLICE), str(workdir / "run.sqlite"), RUN_ID],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def query(workdir: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(workdir / "run.sqlite")) as conn:
        return conn.execute(sql, params).fetchall()


def test_given_a_clean_run_when_it_finishes_then_every_step_ran_once(tmp_path: Path) -> None:
    # When
    done = run_slice(tmp_path)

    # Then
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == RESULT
    steps = [int(line.split()[0]) for line in (tmp_path / "ledger").read_text().splitlines()]
    assert steps == STEPS
    events = query(tmp_path, "SELECT step FROM whw_events WHERE kind = 'session_started'")
    assert events == [(1,), (2,), (4,)]
    status = query(tmp_path, "SELECT status FROM workflow_status WHERE workflow_uuid = ?", RUN_ID)
    assert status == [("SUCCESS",)]
