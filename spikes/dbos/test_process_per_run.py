"""Several run processes share one SQLite file: each recovers and executes only its
own run when runs have their own DBOS application names, and concurrent writers
and a reader all succeed."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from dbos_slice import CRASH_EXIT

SCRIPT = Path(__file__).with_name("process_per_run.py")
RUNS = [f"run-{i}" for i in range(4)]


def start(
    workdir: Path, run_id: str, count: int, crash_at: int | None = None
) -> subprocess.Popen[str]:
    env = {**os.environ, "SPIKE_LEDGER": str(workdir / "ledger")}
    env.pop("SPIKE_CRASH_AT", None)
    if crash_at is not None:
        env["SPIKE_CRASH_AT"] = str(crash_at)
    argv = [sys.executable, str(SCRIPT), "steps", str(workdir / "run.sqlite"), run_id, str(count)]
    return subprocess.Popen(
        [*argv, "per-run"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def ledger_lines(workdir: Path) -> list[list[str]]:
    return [line.split() for line in (workdir / "ledger").read_text().splitlines()]


def test_given_crashed_runs_when_they_resume_together_then_each_runs_in_its_own_process(
    tmp_path: Path,
) -> None:
    # Given: four runs, each killed in its seventh step
    for run_id in RUNS:
        crashed = start(tmp_path, run_id, 12, crash_at=30)
        crashed.wait(timeout=60)
        assert crashed.returncode == CRASH_EXIT, crashed.stderr.read() if crashed.stderr else ""
    executed = len(ledger_lines(tmp_path))

    # When: all four resume at once
    resumed = {run_id: start(tmp_path, run_id, 12) for run_id in RUNS}
    for process in resumed.values():
        process.wait(timeout=60)

    # Then: every resumed step ran in its own run's process
    assert [p.returncode for p in resumed.values()] == [0] * len(RUNS)
    pids = {run_id: str(p.pid) for run_id, p in resumed.items()}
    foreign = [line for line in ledger_lines(tmp_path)[executed:] if line[3] != pids[line[2]]]
    assert foreign == []


def test_given_concurrent_runs_when_a_reader_polls_then_every_write_lands_and_reads_succeed(
    tmp_path: Path,
) -> None:
    # Given: the schema exists, as after a project's first run
    assert start(tmp_path, "warmup", 1).wait(timeout=60) == 0
    db = tmp_path / "run.sqlite"

    # When: six runs of 100 steps write at once while a reader polls
    processes = [start(tmp_path, f"run-{i}", 100) for i in range(6)]
    read_times = []
    while any(p.poll() is None for p in processes):
        began = time.perf_counter()
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)) as conn:
            conn.execute("SELECT status, count(*) FROM workflow_status GROUP BY status").fetchall()
            conn.execute("SELECT count(*) FROM operation_outputs").fetchone()
        read_times.append(time.perf_counter() - began)
        time.sleep(0.02)

    # Then
    assert [p.wait() for p in processes] == [0] * 6
    with closing(sqlite3.connect(db)) as conn:
        steps = conn.execute(
            "SELECT count(*) FROM operation_outputs WHERE workflow_uuid LIKE 'run-%'"
        ).fetchone()[0]
        events = conn.execute(
            "SELECT count(*) FROM whw_events WHERE run_id LIKE 'run-%'"
        ).fetchone()[0]
    assert (steps, events) == (600, 600)
    # In rollback-journal mode, writers held reads up to half a second; in WAL, a few ms.
    assert max(read_times) < 0.25
