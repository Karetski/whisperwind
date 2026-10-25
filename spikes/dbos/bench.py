"""Baseline performance of the DBOS kernel on the fake harness (V7).

    uv run --group spike python spikes/dbos/bench.py WORKDIR [JSON_OUT]

Prints a Markdown table of each metric next to the target VISION.md §7.4
proposes, and writes the numbers as JSON when JSON_OUT is given. The numbers are
a baseline, not a gate: whether a target is met is reported, never enforced.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

import dbos_slice
from dbos import DBOS
from dbos_slice import agent, write_event
from scopes import parallel

HERE = Path(__file__).parent


@dataclass
class Result:
    metric: str
    target: str
    measured: str
    met: bool | None  # None: no pass/fail target


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == "darwin" else peak / 2**10  # bytes vs KiB


# -- workflows ----------------------------------------------------------------------

_step_times: list[float] = []


@DBOS.step()
async def progress(i: int) -> int:
    write_event(DBOS.workflow_id or "", DBOS.step_id or 0, "progress", {"i": i})
    return i


@DBOS.workflow()
async def many_steps(count: int) -> int:
    for i in range(count):
        began = time.perf_counter()
        await progress(i)
        _step_times.append(time.perf_counter() - began)
    return count


@DBOS.workflow()
async def stamp(enqueued: float) -> float:
    return time.time() - enqueued


@DBOS.workflow()
async def enqueue_all(queue_name: str, count: int) -> list[float]:
    queue = await DBOS.retrieve_queue_async(queue_name)
    assert queue is not None
    handles = []
    for _ in range(count):
        handles.append(await queue.enqueue_async(stamp, time.time()))
        await asyncio.sleep(0.02)
    return [await handle.get_result() for handle in handles]


@DBOS.workflow()
async def one_agent(i: int) -> str:
    return await agent(f"task {i}", reply="ok", delay=1)


@DBOS.workflow()
async def fan_out(width: int) -> int:
    return len(await parallel(*[(one_agent, i) for i in range(width)]))


# -- in-process measurements -----------------------------------------------------------


async def step_overhead(count: int) -> Result:
    _step_times.clear()
    await (await DBOS.start_workflow_async(many_steps, count)).get_result()
    p95 = percentile(_step_times, 0.95) * 1000
    return Result(
        "Overhead per step (checkpoint + event append)", "≤ 10 ms p95",
        f"{p95:.2f} ms p95, {statistics.mean(_step_times) * 1000:.2f} ms mean ({count} steps)",
        p95 <= 10,
    )  # fmt: skip


async def long_run(count: int, db: Path) -> Result:
    _step_times.clear()
    began = time.perf_counter()
    await (await DBOS.start_workflow_async(many_steps, count)).get_result()
    elapsed = time.perf_counter() - began
    size = sum(f.stat().st_size for f in db.parent.glob(db.name + "*")) / 2**20
    late = statistics.mean(_step_times[-1000:]) * 1000
    measured = f"{count} steps in {elapsed:.1f} s; the last 1,000 at {late:.2f} ms mean"
    return Result("Steps per run", "10,000", f"{measured}; database {size:.1f} MiB", True)


async def dispatch_latency(poll: float, count: int) -> Result:
    name = f"bench-{int(poll * 1000)}ms"
    await DBOS.register_queue_async(name, polling_interval_sec=poll)
    latencies = await (await DBOS.start_workflow_async(enqueue_all, name, count)).get_result()
    p95 = percentile(latencies, 0.95)
    return Result(
        f"Queue dispatch latency on SQLite (queue polling every {poll:g} s)", "≤ 1 s p95",
        f"{p95:.2f} s p95, {statistics.median(latencies):.2f} s median ({count} enqueues)",
        p95 <= 1,
    )  # fmt: skip


async def concurrency(width: int) -> tuple[Result, float]:
    lags: list[float] = []
    stop = asyncio.Event()

    async def watch() -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            began = loop.time()
            await asyncio.sleep(0.01)
            lags.append(loop.time() - began - 0.01)

    watcher = asyncio.create_task(watch())
    began = time.perf_counter()
    await (await DBOS.start_workflow_async(fan_out, width)).get_result()
    elapsed = time.perf_counter() - began
    stop.set()
    await watcher
    p99 = percentile(lags, 0.99) * 1000
    metric = f"Concurrent agent steps in one run ({width}, each waiting 1 s)"
    lag = f"loop lag {p99:.0f} ms p99, {max(lags) * 1000:.0f} ms max"
    result = Result(
        metric,
        "≥ 200, loop lag ≤ 50 ms p99",
        f"{width} branches in {elapsed:.2f} s; {lag}",
        p99 <= 50 if width >= 200 else None,
    )
    return result, peak_rss_mb()


async def in_process(workdir: Path) -> list[Result]:
    db = workdir / "bench.sqlite"
    dbos_slice._db = str(db)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    DBOS(
        config={
            "name": "whisperwind-bench",
            "system_database_url": f"sqlite:///{db}",
            "log_level": "WARNING",
            "notification_listener_polling_interval_sec": 0.1,
        }
    )
    DBOS.launch()
    try:
        results = [await step_overhead(1000)]
        idle = peak_rss_mb()
        wide50, rss50 = await concurrency(50)
        rss = Result(
            "RSS with 50 agents in flight (harnesses excluded)", "≤ 150 MB",
            f"{rss50:.0f} MiB peak ({idle:.0f} MiB before the fan-out)",
            rss50 <= 150,
        )  # fmt: skip
        wide200, _ = await concurrency(200)
        results += [wide50, wide200, rss]
        for poll in (1.0, 0.1):
            results.append(await dispatch_latency(poll, 50))
        results.append(await long_run(10_000, db))
        return results
    finally:
        DBOS.destroy()


# -- measurements across processes ------------------------------------------------------


def recovery(workdir: Path, completed: int) -> Result:
    """Kill a run as its step completed+1 starts, then time the resume reaching that step again."""
    db, log = workdir / "recovery.sqlite", workdir / "recovery-ledger"
    argv = [
        sys.executable,
        str(HERE / "process_per_run.py"),
        "steps",
        str(db),
        "run-r",
        str(completed + 1),
        "per-run",
    ]
    env = {**os.environ, "SPIKE_LEDGER": str(log)}
    # Two points for the workflow start, then four per agent step; the next is step completed+1's.
    crash = subprocess.run(
        argv, env={**env, "SPIKE_CRASH_AT": str(2 + 4 * completed + 1)}, capture_output=True
    )
    assert crash.returncode == dbos_slice.CRASH_EXIT, crash.stderr
    spawned = time.time()
    resumed = subprocess.run(argv, env=env, capture_output=True, text=True)
    assert resumed.returncode == 0, resumed.stderr
    reached = max(
        float(line.split()[4])
        for line in log.read_text().splitlines()
        if line.startswith(f"{completed + 1} ")
    )
    total = reached - spawned
    startup = cold_start(["import dbos"])
    return Result(
        f"Recovery of a run with {completed:,} completed steps", "≤ 1 s",
        f"{total:.2f} s from spawn to the next step, of which ~{startup:.2f} s is importing DBOS",
        total - startup <= 1,
    )  # fmt: skip


def cold_start(lines: list[str], runs: int = 5) -> float:
    """Median wall time of a fresh interpreter running `lines`."""
    times = []
    for _ in range(runs):
        began = time.perf_counter()
        subprocess.run([sys.executable, "-c", "\n".join(lines)], check=True, capture_output=True)
        times.append(time.perf_counter() - began)
    return statistics.median(times)


def status_cold_start(db: Path) -> list[Result]:
    direct = cold_start([
        "import sqlite3",
        f"conn = sqlite3.connect('file:{db}?mode=ro', uri=True)",
        "conn.execute('SELECT status, count(*) FROM workflow_status GROUP BY status').fetchall()",
    ])  # fmt: skip
    through_dbos = cold_start([
        "from dbos import DBOSClient",
        f"client = DBOSClient(system_database_url='sqlite:///{db}')",
        "client.list_workflows(limit=20)",
        "client.destroy()",
    ])  # fmt: skip
    bare = cold_start(["pass"])
    return [
        Result(
            "`whw status` cold start, reading SQLite directly", "≤ 100 ms",
            f"{direct * 1000:.0f} ms (a bare interpreter: {bare * 1000:.0f} ms)", direct <= 0.1,
        ),
        Result(
            "`whw status` cold start, through DBOSClient", "≤ 100 ms",
            f"{through_dbos * 1000:.0f} ms", through_dbos <= 0.1,
        ),
    ]  # fmt: skip


def markdown(results: list[Result]) -> str:
    marks = {True: "yes", False: "**no**", None: "–"}
    rows = [f"| {r.metric} | {r.target} | {r.measured} | {marks[r.met]} |" for r in results]
    return "\n".join(["| Metric | Target | Measured | Met |", "|---|---|---|---|", *rows])


def main(workdir: Path, json_out: Path | None) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    results = asyncio.run(in_process(workdir))
    results.append(recovery(workdir, 1000))
    results += status_cold_start(workdir / "bench.sqlite")
    print(f"Python {sys.version.split()[0]} on {sys.platform}\n")
    print(markdown(results))
    if json_out:
        json_out.write_text(json.dumps([asdict(r) for r in results], indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
