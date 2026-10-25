"""A paused run survives its process exiting and an edit to its flow: a human
wait outlives the process and is answered from another one (V4), and with the
application version pinned, an edited flow resumes or reports where it diverged
(V3)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from paused import DIVERGED_EXIT, HUMAN_TIMEOUT, WAITING_EXIT

SCRIPT = Path(__file__).with_name("paused.py")
RUN_ID = "run-1"
PINNED = "project-1"

FLOW = """\
from paused import agent, flow, human, shell


@flow
async def main() -> str:
{before}    plan = await agent("{plan}", reply="plan A")
    answer = await human(f"Proceed with {{plan}}?")
    done = await agent(f"Implement {{plan}}", reply="{done}")
    return f"{{plan}}; {{answer}}; {{done}}"
"""


def write_flow(
    workdir: Path, plan: str = "Plan the change", done: str = "implemented", before: str = ""
) -> Path:
    path = workdir / "flow.py"
    path.write_text(FLOW.format(plan=plan, done=done, before=before))
    return path


def paused(workdir: Path, *args: str, wait: float = 30) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SPIKE_WAIT": str(wait), "SPIKE_LEDGER": str(workdir / "ledger")}
    argv = [sys.executable, str(SCRIPT), args[0], str(workdir / "run.sqlite"), RUN_ID, *args[1:]]
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)


def pause(workdir: Path, flow: Path, version: str | None = PINNED) -> None:
    """Run the flow until it waits on its human step, and let the process exit."""
    waiting = paused(workdir, "run", str(flow), *([version] if version else []), wait=2)
    assert waiting.returncode == WAITING_EXIT, waiting.stderr


def wake_time(workdir: Path) -> float:
    with closing(sqlite3.connect(workdir / "run.sqlite")) as conn:
        row = conn.execute(
            "SELECT output FROM operation_outputs"
            " WHERE workflow_uuid = ? AND function_name = 'DBOS.sleep'",
            (RUN_ID,),
        ).fetchone()
    return float(row[0])


def status(workdir: Path) -> str:
    with closing(sqlite3.connect(workdir / "run.sqlite")) as conn:
        row = conn.execute(
            "SELECT status FROM workflow_status WHERE workflow_uuid = ?", (RUN_ID,)
        ).fetchone()
    return str(row[0])


def test_given_a_run_waiting_on_a_person_when_its_process_exits_then_the_wait_stays_days_long(
    tmp_path: Path,
) -> None:
    # When
    pause(tmp_path, write_flow(tmp_path))

    # Then: the run is pending with no process, and its deadline is three days out
    assert status(tmp_path) == "PENDING"
    assert abs(wake_time(tmp_path) - (time.time() + HUMAN_TIMEOUT)) < 60


def test_given_a_waiting_run_with_no_process_when_answered_from_another_then_resuming_finishes_it(
    tmp_path: Path,
) -> None:
    # Given
    flow = write_flow(tmp_path)
    pause(tmp_path, flow)
    deadline = wake_time(tmp_path)

    # When
    assert paused(tmp_path, "respond", "yes").returncode == 0
    resumed = paused(tmp_path, "run", str(flow), PINNED)

    # Then: the answer arrived, and resuming didn't restart the wait's clock
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == "plan A; yes; implemented"
    assert wake_time(tmp_path) == deadline


def test_given_a_live_waiting_run_when_answered_then_it_finishes_promptly(tmp_path: Path) -> None:
    # Given: a run process waiting on its human step
    flow = write_flow(tmp_path)
    env = {**os.environ, "SPIKE_WAIT": "60"}
    argv = [sys.executable, str(SCRIPT), "run", str(tmp_path / "run.sqlite"), RUN_ID, str(flow)]
    live = subprocess.Popen([*argv, PINNED], env=env, stdout=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                wake_time(tmp_path)
                break
            except (sqlite3.OperationalError, TypeError):  # not waiting yet
                time.sleep(0.05)

        # When
        answered = time.time()
        assert paused(tmp_path, "respond", "yes").returncode == 0
        out, _ = live.communicate(timeout=30)

        # Then
        assert json.loads(out) == "plan A; yes; implemented"
        assert time.time() - answered < 5
    finally:
        live.kill()


def test_given_a_paused_run_when_a_step_after_the_pause_is_edited_then_it_resumes_with_the_edit(
    tmp_path: Path,
) -> None:
    # Given
    pause(tmp_path, write_flow(tmp_path))
    assert paused(tmp_path, "respond", "yes").returncode == 0

    # When
    resumed = paused(tmp_path, "run", str(write_flow(tmp_path, done="implemented, v2")), PINNED)

    # Then
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == "plan A; yes; implemented, v2"


def test_given_a_paused_run_when_an_executed_prompt_is_edited_then_resume_names_the_path(
    tmp_path: Path,
) -> None:
    # Given
    pause(tmp_path, write_flow(tmp_path))
    assert paused(tmp_path, "respond", "yes").returncode == 0

    # When
    edited = paused(tmp_path, "run", str(write_flow(tmp_path, plan="Plan it again")), PINNED)

    # Then: the run reports the divergence and stays resumable
    assert edited.returncode == DIVERGED_EXIT
    assert "agent#0: prompt changed since the run paused" in edited.stderr
    assert status(tmp_path) == "PENDING"

    # And: reverting the edit resumes it
    reverted = paused(tmp_path, "run", str(write_flow(tmp_path)), PINNED)
    assert reverted.returncode == 0, reverted.stderr
    assert json.loads(reverted.stdout) == "plan A; yes; implemented"


def test_given_a_paused_run_when_a_step_is_inserted_before_it_then_resume_names_the_path(
    tmp_path: Path,
) -> None:
    # Given
    pause(tmp_path, write_flow(tmp_path))

    # When: a shell step now comes first, where the run recorded an agent step
    inserted = write_flow(tmp_path, before='    await shell(["true"])\n')
    edited = paused(tmp_path, "run", str(inserted), PINNED)

    # Then
    assert edited.returncode == DIVERGED_EXIT
    assert "shell#0: a different step was recorded here" in edited.stderr
    assert status(tmp_path) == "PENDING"


def test_given_an_unpinned_version_when_the_flow_is_edited_then_the_paused_run_is_not_recovered(
    tmp_path: Path,
) -> None:
    # Given: a run paused without a pinned version, then answered
    pause(tmp_path, write_flow(tmp_path), version=None)
    assert paused(tmp_path, "respond", "yes").returncode == 0

    # When: the flow is edited after the pause and the run resumed
    resumed = paused(tmp_path, "run", str(write_flow(tmp_path, done="v2")), wait=5)

    # Then: DBOS's source-hash version changed, so recovery skips the run
    assert resumed.returncode == WAITING_EXIT
    assert status(tmp_path) == "PENDING"
