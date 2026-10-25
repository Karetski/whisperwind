"""Scopes on DBOS child workflows: branches start concurrently under path IDs (V1),
one branch reruns without its siblings (V5), cancelling a branch reaches its
process group (V6), and a fan-out resumes after a kill at any crash point."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from dbos import DBOSClient
from dbos_slice import CRASH_EXIT
from scopes import app_name

SCRIPT = Path(__file__).with_name("scopes.py")
RUN_ID = "run-1"
BRANCHES = [f"{RUN_ID}/parallel#0/{i}" for i in range(3)]
RESULT = (
    "one small patch; bugs: no issues (tests pass); security: no issues (tests pass);"
    " style: no issues (tests pass); verdict 0"
)


def command(
    workdir: Path, *args: str, crash_at: int | None = None, trace: bool = False
) -> tuple[list[str], dict[str, str]]:
    """The argv and environment that run scopes.py against workdir's database."""
    env = {**os.environ, "SPIKE_LEDGER": str(workdir / "ledger")}
    for name in ("SPIKE_CRASH_AT", "SPIKE_TRACE"):
        env.pop(name, None)
    if crash_at is not None:
        env["SPIKE_CRASH_AT"] = str(crash_at)
    if trace:
        env["SPIKE_TRACE"] = str(workdir / "trace")
    return [sys.executable, str(SCRIPT), args[0], str(workdir / "run.sqlite"), *args[1:]], env


def call(
    workdir: Path, *args: str, crash_at: int | None = None, trace: bool = False
) -> subprocess.CompletedProcess[str]:
    argv, env = command(workdir, *args, crash_at=crash_at, trace=trace)
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)


def ledger(workdir: Path) -> list[list[str]]:
    path = workdir / "ledger"
    return [line.split() for line in path.read_text().splitlines()] if path.exists() else []


def checkpointed(workdir: Path) -> set[tuple[str, int]]:
    db = workdir / "run.sqlite"
    if not db.exists():
        return set()
    with closing(sqlite3.connect(db)) as conn:
        try:
            rows = conn.execute(
                "SELECT workflow_uuid, function_id FROM operation_outputs"
            ).fetchall()
        except sqlite3.OperationalError:  # the schema doesn't exist yet
            return set()
    return {(str(workflow), int(step)) for workflow, step in rows}


def test_given_a_fan_out_when_it_runs_then_branches_run_at_once_as_child_workflows_named_by_path(
    tmp_path: Path,
) -> None:
    # When
    done = call(tmp_path, "run", RUN_ID, "review")

    # Then
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == RESULT
    shells = {line[2]: float(line[4]) for line in ledger(tmp_path) if line[1] == "shell"}
    assert sorted(w for w in shells if w != RUN_ID) == BRANCHES
    starts = [shells[branch] for branch in BRANCHES]
    # Each branch's shell step sleeps 0.3 s; run one after another, they would start 0.3 s apart.
    assert max(starts) - min(starts) < 0.3


def test_given_a_finished_fan_out_when_one_branch_reruns_then_its_siblings_do_not(
    tmp_path: Path,
) -> None:
    # Given
    assert call(tmp_path, "run", RUN_ID, "review").returncode == 0
    executed = len(ledger(tmp_path))

    # When: branch 1 reruns from its second step (the shell step)
    rerun = call(tmp_path, "rerun", RUN_ID, "parallel#0/1", "2")

    # Then: only that step and the parent's steps after the fan-out ran again
    assert rerun.returncode == 0, rerun.stderr
    assert json.loads(rerun.stdout) == RESULT
    again = [(line[2], line[0], line[1]) for line in ledger(tmp_path)[executed:]]
    assert again == [(f"{BRANCHES[1]}~1", "2", "shell"), (f"{RUN_ID}~1", "8", "shell")]


def test_given_a_running_branch_when_it_is_cancelled_then_its_process_group_is_killed(
    tmp_path: Path,
) -> None:
    # Given: both branches are running a 30 s command
    argv, env = command(tmp_path, "run", RUN_ID, "slow")
    process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pids: dict[str, int] = {}
    try:
        deadline = time.time() + 30
        while len(ledger(tmp_path)) < 2 and time.time() < deadline:
            time.sleep(0.05)
        pids = {line[2]: int(line[1].split(":")[1]) for line in ledger(tmp_path)}
        client = DBOSClient(
            system_database_url=f"sqlite:///{tmp_path / 'run.sqlite'}",
            application_name=app_name(RUN_ID),
        )

        # When
        client.cancel_workflow(BRANCHES[0])
        deadline = time.time() + 2
        while alive(pids[BRANCHES[0]]) and time.time() < deadline:
            time.sleep(0.05)

        # Then: the cancelled branch's command is gone, its sibling's still runs
        assert not alive(pids[BRANCHES[0]])
        assert alive(pids[BRANCHES[1]])
        client.destroy()
    finally:
        process.kill()
        process.wait()
        for pid in pids.values():
            if alive(pid):
                os.kill(pid, 9)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child stays a zombie until its parent reaps it.
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return not status.stdout.strip().startswith("Z")


def test_given_a_kill_at_any_crash_point_of_a_fan_out_when_resumed_then_no_checkpointed_step_reruns(
    tmp_path: Path,
) -> None:
    # Given: how many crash points a clean run passes
    clean = tmp_path / "clean"
    clean.mkdir()
    assert call(clean, "run", RUN_ID, "review", trace=True).returncode == 0
    points = len((clean / "trace").read_text().splitlines())

    failures = []
    for n in range(1, points + 1):
        workdir = tmp_path / f"crash-{n}"
        workdir.mkdir()

        # When: the run is killed at point n, then resumed
        crashed = call(workdir, "run", RUN_ID, "review", crash_at=n)
        saved, executed = checkpointed(workdir), len(ledger(workdir))
        resumed = call(workdir, "run", RUN_ID, "review")

        # Then
        problems = []
        if crashed.returncode != CRASH_EXIT:
            problems.append(f"crash run exited {crashed.returncode}: {crashed.stderr[-300:]}")
        if resumed.returncode != 0 or json.loads(resumed.stdout or "null") != RESULT:
            problems.append(f"resume exited {resumed.returncode}: {resumed.stderr[-300:]}")
        rerun = {(line[2], int(line[0])) for line in ledger(workdir)[executed:]} & saved
        if rerun:
            problems.append(f"checkpointed steps ran again: {sorted(rerun)}")
        if problems:
            failures.append(f"point {n}: " + "; ".join(problems))

    assert not failures, "\n".join(failures)
