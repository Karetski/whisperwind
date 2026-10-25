"""Reproduce the measurements behind the process-per-run findings in README.md.

    uv run --group spike python spikes/dbos/measure_process_per_run.py WORKDIR

1. Recovery: four crashed runs resume at once, with a shared and with a per-run
   application name. Lists the runs whose steps execute in another run's process.
2. Contention: six runs of 100 steps write one SQLite file while a reader polls it.
3. Queue: three runs share a queue with global_concurrency=2. Reports the peak
   concurrency, children executed by another run's process, and hung runs.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).with_name("process_per_run.py")


def start(
    command: str, db: Path, run_id: str, count: int, mode: str, **extra: str
) -> subprocess.Popen[str]:
    env = {**os.environ, **extra}
    if "SPIKE_CRASH_AT" not in extra:
        env.pop("SPIKE_CRASH_AT", None)
    return subprocess.Popen(
        [sys.executable, str(SCRIPT), command, str(db), run_id, str(count), mode],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish(processes: dict[str, subprocess.Popen[str]], timeout: float) -> list[str]:
    """Wait for every process; kill and return the ones still running at the deadline."""
    deadline, hung = time.time() + timeout, []
    for run_id, process in processes.items():
        try:
            process.communicate(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            hung.append(run_id)
    return hung


def ledger(path: Path) -> list[list[str]]:
    return [line.split() for line in path.read_text().splitlines()] if path.exists() else []


def recovery(workdir: Path, mode: str) -> None:
    db, log = workdir / "run.sqlite", str(workdir / "ledger")
    runs = [f"run-{i}" for i in range(4)]
    for run_id in runs:
        start("steps", db, run_id, 12, mode, SPIKE_LEDGER=log, SPIKE_CRASH_AT="30").wait()
    executed = len(ledger(Path(log)))
    processes = {r: start("steps", db, r, 12, mode, SPIKE_LEDGER=log) for r in runs}
    hung = finish(processes, 60)
    pids = {run_id: str(p.pid) for run_id, p in processes.items()}
    by_pid = {pid: run_id for run_id, pid in pids.items()}
    resumed = ledger(Path(log))[executed:]
    taken = sorted(
        {(line[2], by_pid.get(line[3], "?")) for line in resumed if line[3] != pids[line[2]]}
    )
    print(f"recovery {mode:7}: runs executed elsewhere (run, by): {taken}; hung: {hung}")


def contention(workdir: Path) -> None:
    db = workdir / "run.sqlite"
    start("steps", db, "warmup", 1, "per-run").wait()
    processes = {f"run-{i}": start("steps", db, f"run-{i}", 100, "per-run") for i in range(6)}
    began, latencies = time.time(), []
    while any(p.poll() is None for p in processes.values()):
        t = time.perf_counter()
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)) as conn:
            conn.execute("SELECT status, count(*) FROM workflow_status GROUP BY status").fetchall()
            conn.execute("SELECT count(*) FROM operation_outputs").fetchone()
        latencies.append(time.perf_counter() - t)
        time.sleep(0.02)
    elapsed, hung = time.time() - began, finish(processes, 60)
    latencies.sort()
    p50, p99 = latencies[len(latencies) // 2], latencies[int(len(latencies) * 0.99)]
    print(
        f"contention: 600 steps in {elapsed:.1f}s; reader p50 {1000 * p50:.1f} ms,"
        f" p99 {1000 * p99:.1f} ms; hung: {hung}"
    )


def queue(workdir: Path) -> None:
    db, log = workdir / "run.sqlite", workdir / "ledger"
    processes = {}
    for i in range(3):
        processes[f"run-{i}"] = start("fanout", db, f"run-{i}", 4, "shared", SPIKE_LEDGER=str(log))
        if i == 0:
            time.sleep(1.5)  # the first run creates the schema and registers the queue
    hung = finish(processes, 40)
    by_pid = {str(p.pid): run_id for run_id, p in processes.items()}
    holds = [line for line in ledger(log) if line[0] == "hold"]
    with closing(sqlite3.connect(db)) as conn:
        children = conn.execute(
            "SELECT workflow_uuid, parent_workflow_id, status, executor_id FROM workflow_status"
            " WHERE parent_workflow_id IS NOT NULL"
        ).fetchall()
    parent = {child: run_id for child, run_id, _, _ in children}
    stranded = [(child, executor) for child, _, status, executor in children if status == "PENDING"]
    edges = sorted([(float(h[3]), 1) for h in holds] + [(float(h[4]), -1) for h in holds])
    running = peak = 0
    for _, delta in edges:
        running += delta
        peak = max(peak, running)
    elsewhere = sum(parent.get(h[1]) != by_pid.get(h[2]) for h in holds)
    print(
        f"queue: peak {peak} (limit 2); children executed elsewhere {elsewhere}/{len(holds)};"
        f" hung: {hung}; stranded children (id, executor): {stranded}"
    )


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for trial in range(3):
        for mode in ("shared", "per-run"):
            (root / f"recovery-{mode}-{trial}").mkdir(parents=True)
            recovery(root / f"recovery-{mode}-{trial}", mode)
    (root / "contention").mkdir()
    contention(root / "contention")
    for trial in range(3):
        (root / f"queue-{trial}").mkdir()
        queue(root / f"queue-{trial}")
