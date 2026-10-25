"""The crash-injection suite (V8): a sequential flow and a fan-out each resume
after a kill at any crash point, with the uninterrupted run's result, no
checkpointed step run twice, and harness sessions resumed rather than restarted."""

from __future__ import annotations

import sys
from pathlib import Path

import crash_suite
from crash_suite import Flow, check_every_crash_point

HERE = Path(__file__).parent

SEQUENTIAL = Flow(
    argv=lambda workdir: [
        sys.executable,
        str(HERE / "dbos_slice.py"),
        str(workdir / "run.sqlite"),
        "run-1",
    ],
    result="green after 2 attempts: add a failing test, then fix it",
)

FAN_OUT = Flow(
    argv=lambda workdir: [
        sys.executable,
        str(HERE / "scopes.py"),
        "run",
        str(workdir / "run.sqlite"),
        "run-1",
        "review",
    ],
    result=(
        "one small patch; bugs: no issues (tests pass); security: no issues (tests pass);"
        " style: no issues (tests pass); verdict 0"
    ),
)


def test_given_a_sequential_flow_when_killed_at_any_crash_point_then_it_resumes_correctly(
    tmp_path: Path,
) -> None:
    failures = check_every_crash_point(SEQUENTIAL, tmp_path)
    assert not failures, "\n".join(failures)


def test_given_a_fan_out_when_killed_at_any_crash_point_then_it_resumes_correctly(
    tmp_path: Path,
) -> None:
    failures = check_every_crash_point(FAN_OUT, tmp_path)
    assert not failures, "\n".join(failures)


def test_given_a_kill_after_a_session_started_when_resumed_then_the_step_resumes_that_session(
    tmp_path: Path,
) -> None:
    # Given: the first crash point after the plan step's session started, before its checkpoint
    (tmp_path / "clean").mkdir()
    points = crash_suite.crash_points(SEQUENTIAL, tmp_path / "clean")
    point = points.index("4 after event session_started") + 1

    # When
    assert crash_suite.kill_and_resume(SEQUENTIAL, tmp_path, point) == []

    # Then: step 1 ran twice, the second time resuming its session
    kinds = [line[1] for line in crash_suite.ledger(tmp_path) if line[0] == "1"]
    assert kinds == ["agent", "agent:resume"]
