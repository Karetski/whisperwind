"""The adapter conformance kit, `whisperwind adapter test`.

Offline (default), it replays recorded streams and compares the normalized
results with each fixture set's `expected.yaml`: built-in adapters parse the
streams directly; command adapters run their real process path against a stub
executable that replays the stream. ACP adapters run theirs against a stub
agent that replays a two-way transcript, checking each message the client
sends against it. Live (`--live`, opt-in, spends money), it runs a few small
prompts through a real harness with a spend cap.

Besides the expected result, a case in `expected.yaml` may set the request:
`schema` (an output schema), `permissions` (a profile) and `resume` (a session
ID to resume). `stop: cancel` or `stop: timeout` stops the attempt at its first
text, for cancellation cases.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from whisperwind.adapters import (
    AdapterEvent,
    AgentRequest,
    AgentResult,
    SessionSpec,
    Text,
    registry,
)
from whisperwind.adapters.acp import AcpAdapter, features
from whisperwind.adapters.process import ProcessAdapter, parse_lines
from whisperwind.store.events import read_log

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPLAY = Path(__file__).parent / "replay.py"
ACP_REPLAY = Path(__file__).parent / "acp_replay.py"
SESSION = "11111111-2222-4333-8444-555555555555"


@dataclass
class CaseResult:
    case: str
    passed: bool
    problems: list[str]

    def to_json(self) -> dict[str, Any]:
        return {"case": self.case, "passed": self.passed, "problems": self.problems}


def fixture_dirs(name: str, root: Path | None) -> list[Path]:
    """Fixture sets for an adapter: the project's own for command adapters,
    the packaged ones (one per tested harness version) for built-ins."""
    if root is not None:
        from whisperwind.adapters.command import find

        path = find(root, name)
        if path is not None:
            own = path.parent / name / "fixtures"
            return [own] if own.is_dir() else []
    return sorted(p for p in FIXTURES_DIR.glob(f"{name}-*") if p.is_dir())


def _request(attempt_dir: Path, case: dict[str, Any]) -> AgentRequest:
    resume = case.get("resume")
    session = SessionSpec("resume", str(resume)) if resume else SessionSpec("new", None, SESSION)
    return AgentRequest(
        run_id="conformance",
        node_id="case",
        visit=1,
        attempt=1,
        prompt="Conformance test prompt.",
        instructions=None,
        cwd=str(attempt_dir),
        add_dirs=[],
        model=None,
        effort=None,
        permissions=str(case.get("permissions", "edit")),
        allow_tools=[],
        deny_tools=[],
        output_schema=case.get("schema"),
        session=session,
        max_turns=None,
        budget_usd=None,
        budget_tokens=None,
        bare=False,
        env={"PATH": os.environ.get("PATH", "")},
        options={},
        attempt_dir=str(attempt_dir),
    )


def compare(result: AgentResult, expected: dict[str, Any]) -> list[str]:
    """Differences between a normalized result and its expectation."""
    problems = []

    def check(what: str, actual: Any, wanted: Any) -> None:
        if actual != wanted:
            problems.append(f"{what}: expected {wanted!r}, got {actual!r}")

    if "outcome" in expected:
        check("outcome", result.outcome, expected["outcome"])
    if "error_kind" in expected:
        check("error kind", result.error.kind if result.error else None, expected["error_kind"])
    for key in ("session_id", "text", "output", "num_turns", "stopped_by"):
        if key in expected:
            check(key, getattr(result, key), expected[key])
    if "cost_usd" in expected:
        actual = result.cost_usd
        if actual is None or abs(actual - float(expected["cost_usd"])) > 1e-9:
            problems.append(f"cost_usd: expected {expected['cost_usd']!r}, got {actual!r}")
    for key, wanted in (expected.get("usage") or {}).items():
        check(f"usage.{key}", getattr(result.usage, key), wanted)
    if "permission_denials" in expected:
        check(
            "permission denials",
            [d.tool for d in result.permission_denials],
            expected["permission_denials"],
        )
    return problems


def run_offline(name: str, root: Path | None) -> list[CaseResult]:
    adapter = registry.load(name, root)
    if not isinstance(adapter, ProcessAdapter) and name != "fake":
        raise ValueError(f"{name}: offline conformance needs a process-based adapter")
    results: list[CaseResult] = []
    dirs = fixture_dirs(name, root)
    if not dirs:
        return [CaseResult("fixtures", False, [f"no fixtures found for {name}"])]
    command_adapter = registry.source(name, root) not in ("built-in",)
    for directory in dirs:
        expected = YAML(typ="safe", pure=True).load((directory / "expected.yaml").read_text())
        for case, wanted in (expected.get("cases") or {}).items():
            # A built-in's sets are one per harness version, so its labels name the set.
            label = case if command_adapter else f"{directory.name}/{case}"
            stream = directory / f"{case}.jsonl"
            if not stream.exists():
                results.append(CaseResult(label, False, [f"missing {stream.name}"]))
                continue
            problems: list[str] = []
            with tempfile.TemporaryDirectory() as tmp:
                req = _request(Path(tmp), wanted)
                if command_adapter:
                    assert isinstance(adapter, ProcessAdapter)
                    result = asyncio.run(_replay(adapter, req, stream, wanted.get("stop")))
                    report = Path(tmp) / "replay-mismatch.txt"
                    if report.exists():
                        problems.append(f"transcript: {report.read_text()}")
                else:
                    assert isinstance(adapter, ProcessAdapter)
                    parser = adapter.parser(req)
                    parse_lines(parser, stream.read_text().splitlines())
                    result = parser.finish(req, 0, "")
            problems += compare(result, wanted)
            results.append(CaseResult(label, not problems, problems))
    return results


async def _replay(
    adapter: ProcessAdapter, req: AgentRequest, stream: Path, stop: str | None
) -> AgentResult:
    """Run the adapter's real process path with its program replaced by a stub
    that replays `stream`. With `stop`, the attempt is stopped at its first text."""
    original = adapter.command
    report = Path(req.attempt_dir) / "replay-mismatch.txt"

    def command(request: AgentRequest) -> list[str]:
        if isinstance(adapter, AcpAdapter):
            return [sys.executable, str(ACP_REPLAY), str(stream), str(report)]
        argv = original(request)
        return [sys.executable, str(REPLAY), str(stream), "--", *argv[1:]]

    texted = asyncio.Event()

    def emit(event: AdapterEvent) -> None:
        if isinstance(event, Text):
            texted.set()

    adapter.command = command  # type: ignore[method-assign, assignment]
    try:
        task = asyncio.ensure_future(adapter.run(req, emit))
        if stop is not None:
            waiter = asyncio.ensure_future(texted.wait())
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if not task.done():
                req.stop_reason = "timeout" if stop == "timeout" else "cancel"
                task.cancel()
        return await task
    finally:
        adapter.command = original  # type: ignore[method-assign]


LIVE_FLOW = """name: conformance-live
defaults:
  agent:
    harness: {name}
    timeout: 3m
    budget: {{usd: 0.05, tokens: 100000}}
nodes:
  first:
    type: agent
    permissions: read-only
    prompt: Reply with the word ready.
    output_schema:
      type: object
      additionalProperties: false
      required: [word]
      properties: {{word: {{type: string}}}}
    next: second
  second:
    type: agent
    permissions: read-only
    session: {{resume: first}}
    prompt: Which word did you reply with? Answer in one word.
    next: slow
  slow:
    type: agent
    timeout: 5s
    on_error: continue
    prompt: Count slowly from 1 to 500, one number per line.
"""


def run_live(name: str, root: Path | None, environ: dict[str, str]) -> list[CaseResult]:
    """A few real calls with a spend cap: session IDs, resume, schema output and
    stopping within the grace period."""
    from whisperwind.clock import Clock
    from whisperwind.config import load_config
    from whisperwind.engine.runner import Runner, create_run

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / ".whisperwind").mkdir()
        if root is not None and (root / ".whisperwind" / "harnesses").is_dir():
            import shutil

            shutil.copytree(
                root / ".whisperwind" / "harnesses", project / ".whisperwind" / "harnesses"
            )
        flow = project / "flow.yaml"
        flow.write_text(LIVE_FLOW.format(name=name))
        config, _ = load_config(project)
        run = create_run(flow, {}, config=config, clock=Clock(), workdir=project)
        outcome = asyncio.run(Runner(run, config, Clock(), environ=environ, heartbeat=False).run())
        nodes = outcome.state["nodes"]
        stopped_by = {
            e["node"]: e["data"].get("stopped_by")
            for e in read_log(run.events).events
            if e["type"] == "attempt_finished"
        }
    first, second, slow = (
        nodes.get("first") or {},
        nodes.get("second") or {},
        nodes.get("slow") or {},
    )
    acp = [
        _live_case(
            "cancel answered within grace",
            slow.get("outcome") == "timed_out" and stopped_by.get("slow") is None,
            f"the process was stopped with {stopped_by.get('slow')}",
        )
    ]
    return [
        _live_case("session id", bool(first.get("session_id")), f"got {first.get('session_id')!r}"),
        _live_case(
            "schema output",
            isinstance(first.get("output"), dict) and "word" in first["output"],
            f"got {first.get('output')!r}",
        ),
        _live_case(
            "resume",
            second.get("session_id") == first.get("session_id")
            and second.get("outcome") == "succeeded",
            f"first {first.get('session_id')!r}, second {second.get('session_id')!r}",
        ),
        _live_case(
            "stop within grace", slow.get("outcome") == "timed_out", f"got {slow.get('outcome')!r}"
        ),
        *(acp if isinstance(registry.load(name, root), AcpAdapter) else []),
    ]


def live_features(name: str, root: Path | None, environ: dict[str, str]) -> dict[str, Any] | None:
    """For an ACP adapter, what the agent supports, from a handshake that opens
    a session without prompting it; None for other adapters. The agent gets the
    environment a run would give it."""
    from whisperwind.config import load_config
    from whisperwind.engine.environment import process_environment

    adapter = registry.load(name, root)
    if not isinstance(adapter, AcpAdapter):
        return None
    project = (root or Path.cwd()).resolve()
    config, _ = load_config(project)
    env = process_environment(
        environ, passthrough=config["env_passthrough"], adapter_vars=adapter.auth_env
    )
    shaken = asyncio.run(adapter.handshake(str(project), env))
    return features(*shaken) if shaken is not None else None


def _live_case(case: str, ok: bool, detail: str) -> CaseResult:
    return CaseResult(f"live/{case}", ok, [] if ok else [detail])
