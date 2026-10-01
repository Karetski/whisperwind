"""ACP adapters, driven against the reference ACP agent with scripted turns."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from engine_support import Result, run_flow

from whisperwind import cli
from whisperwind.adapters import (
    AdapterEvent,
    AgentRequest,
    AgentResult,
    Log,
    PermissionDenied,
    SessionSpec,
    Text,
    ToolCall,
    ToolResult,
    UsageUpdate,
)
from whisperwind.adapters.acp import AcpAdapter
from whisperwind.adapters.command import load_spec
from whisperwind.validate import validate

AGENT = Path(__file__).parent.parent / ".whisperwind" / "harnesses" / "acp-reference" / "agent.py"


def write_harness(project: Path, script: dict[str, Any], extra: str = "") -> Path:
    """A harness file `ref` that runs the reference agent with `script`."""
    (project / "script.json").write_text(json.dumps(script))
    command = [sys.executable, str(AGENT), "--script", str(project / "script.json")]
    command += ["--state", str(project / "agent-state")]
    harnesses = project / ".whisperwind" / "harnesses"
    harnesses.mkdir(parents=True, exist_ok=True)
    path = harnesses / "ref.yaml"
    path.write_text(f"name: ref\nprotocol: acp\ncommand: {json.dumps(command)}\ngrace: 1s\n{extra}")
    return path


def request(project: Path, **changes: Any) -> AgentRequest:
    attempt_dir = project / "attempt"
    attempt_dir.mkdir(exist_ok=True)
    base = AgentRequest(
        run_id="r",
        node_id="n",
        visit=1,
        attempt=1,
        prompt="Do the task.",
        instructions=None,
        cwd=str(project),
        add_dirs=[],
        model=None,
        effort=None,
        permissions="edit",
        allow_tools=[],
        deny_tools=[],
        output_schema=None,
        session=SessionSpec(),
        max_turns=None,
        budget_usd=None,
        budget_tokens=None,
        bare=False,
        env={"PATH": os.environ["PATH"]},
        options={},
        attempt_dir=str(attempt_dir),
    )
    return dataclasses.replace(base, **changes)


def drive(
    project: Path, script: dict[str, Any], extra: str = "", **changes: Any
) -> tuple[AgentResult, list[AdapterEvent], list[dict[str, Any]]]:
    """Run one request through the adapter: its result, every event and the
    messages the client sent."""
    spec, problems = load_spec(write_harness(project, script, extra))
    assert spec is not None, problems
    events: list[AdapterEvent] = []
    req = request(project, **changes)
    result = asyncio.run(AcpAdapter(spec).run(req, events.append))
    return result, events, sent(Path(req.attempt_dir))


def sent(attempt_dir: Path) -> list[dict[str, Any]]:
    lines = (attempt_dir / "stream.jsonl").read_text().splitlines()
    return [m["message"] for m in map(json.loads, lines) if m["from"] == "client"]


def methods(messages: list[dict[str, Any]]) -> list[str]:
    return [m["method"] for m in messages if "method" in m]


def run_acp_flow(project: Path, nodes: str, script: dict[str, Any], extra: str = "") -> Result:
    write_harness(project, script, extra)
    flow = f"name: a\ndefaults:\n  agent: {{harness: ref}}\nnodes:\n{nodes}"
    environ = {"PATH": os.environ["PATH"]}
    return run_flow(project, flow, virtual=False, environ=environ, grace=1.0)


def finished(result: Result, node: str) -> dict[str, Any]:
    event = next(e for e in result.events if e["type"] == "attempt_finished" and e["node"] == node)
    data: dict[str, Any] = event["data"]
    return data


# -- a turn ---------------------------------------------------------------------------


def test_given_acp_agent_when_a_node_runs_then_text_tools_and_cost_are_mapped(
    tmp_path: Path,
) -> None:
    # Given
    script = {
        "agent_info": {"name": "ref", "version": "1.2.0"},
        "turns": [
            {
                "steps": [
                    {"text": "Hello, "},
                    {"tool": "Read README.md", "kind": "read"},
                    {"usage": {"used": 900, "size": 200000, "cost": 0.02}},
                    {"text": "world."},
                ]
            }
        ],
    }

    # When
    result = run_acp_flow(
        tmp_path,
        "  ask:\n    type: agent\n    prompt: Greet.\n",
        script,
        "capabilities: {cost_usd: true}\n",
    )

    # Then
    assert result.status == "succeeded", result.state["failure"]
    ask = result.state["nodes"]["ask"]
    assert (ask["text"], ask["cost_usd"], ask["harness_version"]) == (
        "Hello, world.",
        0.02,
        "1.2.0",
    )
    started = [e["data"]["session_id"] for e in result.events if e["type"] == "session_started"]
    assert started == [ask["session_id"]]
    messages = sent(result.run.attempt_dir("ask", 1, 1))
    assert methods(messages) == ["initialize", "session/new", "session/prompt"]
    assert messages[0]["params"]["protocolVersion"] == 1
    assert messages[1]["params"] == {"cwd": str(tmp_path), "mcpServers": []}
    assert messages[2]["params"]["prompt"] == [{"type": "text", "text": "Greet."}]


def test_given_acp_agent_when_it_streams_then_each_update_becomes_an_event(
    tmp_path: Path,
) -> None:
    # Given
    script = {
        "turns": [
            {
                "steps": [
                    {"text": "Done."},
                    {"tool": "Edit a.txt", "kind": "edit"},
                    {"usage": {"cost": 0.5}},
                ]
            }
        ]
    }

    # When
    result, events, _ = drive(tmp_path, script)

    # Then
    assert result.outcome == "succeeded"
    assert [e for e in events if not isinstance(e, Log)][1:] == [
        Text("Done."),
        ToolCall("Edit a.txt", "Edit a.txt"),
        ToolResult("Edit a.txt", True, "completed"),
        UsageUpdate(result.usage, 0.5),
    ]


def test_given_instructions_when_prompted_then_they_lead_the_prompt(tmp_path: Path) -> None:
    # When
    _, _, messages = drive(tmp_path, {}, instructions="Be brief.", prompt="Summarize.")

    # Then
    prompt = messages[-1]["params"]["prompt"][0]["text"]
    assert prompt == "# Instructions\n\nBe brief.\n\n# Task\n\nSummarize."


# -- sessions -------------------------------------------------------------------------

RESUME_FLOW = """  first:
    type: agent
    prompt: Remember the word kiwi.
    next: second
  second:
    type: agent
    session: {resume: first}
    prompt: Which word?
"""

TWO_TURNS = [
    {"when": "Remember", "steps": [{"text": "Noted."}]},
    {"when": "Which", "steps": [{"text": "kiwi"}]},
]


@pytest.mark.parametrize(
    ("advertised", "method"),
    [({"resume": True}, "session/resume"), ({"load_session": True}, "session/load")],
)
def test_given_resumable_agent_when_a_session_is_resumed_then_the_agent_continues_it(
    tmp_path: Path, advertised: dict[str, bool], method: str
) -> None:
    # Given
    script = {**advertised, "turns": TWO_TURNS}

    # When
    result = run_acp_flow(tmp_path, RESUME_FLOW, script, "capabilities: {resume: true}\n")

    # Then
    assert result.status == "succeeded", result.state["failure"]
    first, second = result.state["nodes"]["first"], result.state["nodes"]["second"]
    assert second["session_id"] == first["session_id"]
    assert second["text"] == "kiwi"  # a loaded session's replayed history is not this turn's
    messages = sent(result.run.attempt_dir("second", 1, 1))
    assert methods(messages)[1] == method
    assert messages[1]["params"]["sessionId"] == first["session_id"]


def test_given_agent_that_cannot_resume_when_resumed_then_a_new_session_starts(
    tmp_path: Path,
) -> None:
    # When
    result, events, messages = drive(tmp_path, {}, session=SessionSpec("resume", "old-session"))

    # Then
    assert result.outcome == "succeeded"
    assert methods(messages)[1] == "session/new"
    assert Log("warning", "the agent cannot resume sessions; starting a new one") in events


def test_given_add_dirs_when_the_agent_accepts_them_then_they_are_sent(tmp_path: Path) -> None:
    # When
    _, _, messages = drive(tmp_path, {"additional_directories": True}, add_dirs=["/data"])

    # Then
    assert messages[1]["params"]["additionalDirectories"] == ["/data"]


# -- settings -------------------------------------------------------------------------

OPTIONS = [
    {"id": "model", "category": "model", "values": ["small", "large"]},
    {"id": "reasoning", "category": "thought_level", "values": ["low", "high"]},
]


def test_given_model_and_effort_options_when_requested_then_they_are_set(tmp_path: Path) -> None:
    # When
    result, _, messages = drive(tmp_path, {"config_options": OPTIONS}, model="large", effort="high")

    # Then
    assert result.outcome == "succeeded"
    settings = [m["params"] for m in messages if m.get("method") == "session/set_config_option"]
    assert [(s["configId"], s["value"]) for s in settings] == [
        ("model", "large"),
        ("reasoning", "high"),
    ]


def test_given_option_the_agent_lacks_when_requested_then_a_warning_is_logged(
    tmp_path: Path,
) -> None:
    # When
    result, events, messages = drive(
        tmp_path, {"config_options": OPTIONS[:1]}, model="huge", effort="high"
    )

    # Then
    assert result.outcome == "succeeded"
    assert "session/set_config_option" not in methods(messages)
    assert Log("warning", "the agent has no model option 'huge'; ignored") in events
    assert Log("warning", "the agent has no effort option 'high'; ignored") in events


@pytest.mark.parametrize(
    ("as_config", "method", "key"),
    [(False, "session/set_mode", "modeId"), (True, "session/set_config_option", "value")],
)
def test_given_modes_map_when_a_profile_runs_then_its_mode_is_selected(
    tmp_path: Path, as_config: bool, method: str, key: str
) -> None:
    # Given
    script = {"modes": ["ask", "plan", "auto"], "modes_as_config": as_config}
    modes = "modes: {read-only: plan, edit: auto}\n"

    # When
    _, _, messages = drive(tmp_path, script, modes, permissions="read-only")

    # Then
    chosen = [m["params"] for m in messages if m.get("method") == method]
    assert [c[key] for c in chosen] == ["plan"]


# -- permissions ----------------------------------------------------------------------

TOOLS = {
    "turns": [
        {
            "steps": [
                {"tool": "Read a.txt", "kind": "read"},
                {"tool": "Edit a.txt", "kind": "edit"},
                {"tool": "Run tests", "kind": "execute"},
            ]
        }
    ]
}


@pytest.mark.parametrize(
    ("profile", "denied"),
    [
        ("read-only", ["Edit a.txt", "Run tests"]),
        ("edit", ["Run tests"]),
        ("full", []),
    ],
)
def test_given_permission_request_when_answered_then_the_profile_decides(
    tmp_path: Path, profile: str, denied: list[str]
) -> None:
    # When
    result, events, messages = drive(tmp_path, TOOLS, permissions=profile)

    # Then
    assert result.outcome == "succeeded"
    assert [d.tool for d in result.permission_denials] == denied
    assert [e.tool for e in events if isinstance(e, PermissionDenied)] == denied
    answers = [m["result"]["outcome"]["optionId"] for m in messages if "result" in m]
    assert answers == [
        "reject" if t in denied else "allow" for t in ("Read a.txt", "Edit a.txt", "Run tests")
    ]
    failed = [e.name for e in events if isinstance(e, ToolResult) and not e.ok]
    assert failed == denied


# -- failures -------------------------------------------------------------------------


def test_given_agent_needing_login_when_run_then_the_failure_names_its_auth_methods(
    tmp_path: Path,
) -> None:
    # Given
    script = {"auth_required": True, "auth_methods": [{"id": "api-key", "name": "API key"}]}

    # When
    result, _, _ = drive(tmp_path, script)

    # Then
    assert result.outcome == "failed"
    assert result.error is not None
    assert (result.error.kind, result.error.detail["code"]) == ("harness_error", -32000)
    assert result.error.message == "the agent needs authentication (API key)"


def test_given_json_rpc_error_when_prompted_then_the_attempt_fails_with_it(
    tmp_path: Path,
) -> None:
    # Given
    script = {"turns": [{"steps": [{"error": {"code": -32603, "message": "model overloaded"}}]}]}

    # When
    result, _, _ = drive(tmp_path, script)

    # Then
    assert result.outcome == "failed"
    assert result.error is not None
    assert (result.error.kind, result.error.message) == ("harness_error", "model overloaded")
    assert result.error.detail == {"code": -32603}


def test_given_agent_crashing_mid_turn_when_run_then_no_result_keeps_what_it_said(
    tmp_path: Path,
) -> None:
    # Given
    script = {"turns": [{"steps": [{"text": "Starting"}, {"exit": 3}]}]}

    # When
    result, _, _ = drive(tmp_path, script)

    # Then
    assert (result.outcome, result.text) == ("failed", "Starting")
    assert result.error is not None
    assert (result.error.kind, result.error.detail) == ("no_result", {"exit_code": 3})


@pytest.mark.parametrize("stop", ["refusal", "max_tokens", "max_turn_requests"])
def test_given_coarse_stop_reason_when_the_turn_ends_then_it_fails_with_the_reason(
    tmp_path: Path, stop: str
) -> None:
    # When
    result, _, _ = drive(tmp_path, {"turns": [{"steps": [], "stop": stop}]})

    # Then
    assert result.outcome == "failed"
    assert result.error is not None
    assert result.error.detail == {"stop_reason": stop}


# -- stopping -------------------------------------------------------------------------


def test_given_agent_answering_cancel_when_timed_out_then_it_stops_within_grace(
    tmp_path: Path,
) -> None:
    # Given
    script = {"turns": [{"steps": [{"text": "Working"}, {"wait_for_cancel": True}]}]}

    # When
    result = run_acp_flow(
        tmp_path, "  slow:\n    type: agent\n    prompt: Go.\n    timeout: 1s\n", script
    )

    # Then
    slow = result.state["nodes"]["slow"]
    assert (slow["outcome"], slow["text"]) == ("timed_out", "Working")
    assert finished(result, "slow")["stopped_by"] is None
    assert "session/cancel" in methods(sent(result.run.attempt_dir("slow", 1, 1)))


def test_given_agent_ignoring_cancel_when_timed_out_then_the_process_is_stopped(
    tmp_path: Path,
) -> None:
    # Given
    script = {"turns": [{"steps": [{"text": "Working"}, {"ignore_cancel": True}]}]}

    # When
    result = run_acp_flow(
        tmp_path, "  slow:\n    type: agent\n    prompt: Go.\n    timeout: 1s\n", script
    )

    # Then
    slow = result.state["nodes"]["slow"]
    assert (slow["outcome"], slow["error"]["kind"]) == ("timed_out", "no_result")
    assert finished(result, "slow")["stopped_by"] == "sigint"


# -- harness files, validation and probing ----------------------------------------------


def test_given_acp_harness_when_probed_then_its_version_and_auth_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given
    script = {
        "agent_info": {"name": "ref", "version": "0.31.0"},
        "auth_methods": [{"id": "login", "name": "Log in"}],
    }
    write_harness(tmp_path, script, "tested_versions: '>=0.30'\n")
    monkeypatch.chdir(tmp_path)

    # When
    code = cli.main(["adapters", "--probe", "--json"])

    # Then
    assert code == 0
    found = json.loads(capsys.readouterr().out)["data"]["adapters"]
    ref = next(a for a in found if a["name"] == "ref")
    assert ref["probe"] == {
        "found": True,
        "version": "0.31.0",
        "in_tested_range": True,
        "auth": "auth: Log in",
    }
    assert ref["capabilities"]["permission_hook"] is True


@pytest.mark.parametrize(
    ("harness", "code"),
    [
        ("name: ext\nprotocol: acp\ncommand: [ext]\nstream: {}\n", "E-UNKNOWN-KEY"),
        ("name: ext\nprotocol: acp\ncommand: [ext]\nmodes: {admin: x}\n", "E-SCHEMA"),
    ],
    ids=["acp has no stream", "modes name profiles"],
)
def test_given_malformed_acp_harness_when_validated_then_it_is_reported(
    tmp_path: Path, harness: str, code: str
) -> None:
    # Given
    harnesses = tmp_path / ".whisperwind" / "harnesses"
    harnesses.mkdir(parents=True)
    (harnesses / "ext.yaml").write_text(harness)
    (tmp_path / "flow.yaml").write_text(
        "name: f\nnodes:\n  a: {type: agent, harness: ext, prompt: Hi.}\n"
    )

    # When
    report = validate(tmp_path / "flow.yaml")

    # Then
    assert [p.code for p in report.errors] == [code]


def test_given_valid_acp_harness_when_a_flow_is_validated_then_it_passes(tmp_path: Path) -> None:
    # Given
    write_harness(tmp_path, {}, "modes: {read-only: plan}\ncapabilities: {resume: true}\n")
    (tmp_path / "flow.yaml").write_text(
        "name: f\nnodes:\n  a: {type: agent, harness: ref, permissions: read-only, prompt: Hi.}\n"
    )

    # When
    report = validate(tmp_path / "flow.yaml")

    # Then
    assert report.errors == []
