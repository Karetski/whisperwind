"""The step-path grammar proposed in ADR 0014, as a reference implementation.

A path is a sequence of segments separated by `/`:

    name        a phase or a label           plan, security-review
    kind#n      the nth call of a kind       agent#0, parallel#1, stage#2, summarize#0
    n           the nth branch               0, 1, 2
    item[key]   a pipeline item, by key      item[src/a.ts]

An address is a run reference, optionally followed by `/` and a path:
`20260930T121500-review-abcd/review/parallel#0/1`, `@last/plan`, `@last:review/plan`.
Inside `item[...]`, `\\` escapes `]` and `\\`; everything else, `/` included, is
literal. Spike code: phase P1 ports it into `src/whisperwind/`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NAME = re.compile(r"[a-z][a-z0-9._-]*\Z")
KIND = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
RUN_REF = re.compile(r"(@last(:[A-Za-z0-9._-]+)?|[A-Za-z0-9][A-Za-z0-9._-]*)\Z")


@dataclass(frozen=True)
class Name:
    """A phase or a label: its identity doesn't depend on position."""

    text: str


@dataclass(frozen=True)
class Call:
    """The nth call of one kind in its scope, counted from 0."""

    kind: str
    ordinal: int


@dataclass(frozen=True)
class Branch:
    """The nth branch of a parallel, race or map call, by argument position."""

    index: int


@dataclass(frozen=True)
class Item:
    """A pipeline item, identified by its key rather than its position."""

    key: str


Segment = Name | Call | Branch | Item
Path = tuple[Segment, ...]


def slug(phase: str) -> str:
    """The path segment of a phase name: lower case, other runs of characters as `-`."""
    text = re.sub(r"[^a-z0-9._]+", "-", phase.lower()).strip("-")
    if not NAME.match(text):
        raise ValueError(f"phase {phase!r} has no valid path segment")
    return text


def format_segment(segment: Segment) -> str:
    match segment:
        case Name(text):
            if not NAME.match(text):
                raise ValueError(f"not a valid name: {text!r}")
            return text
        case Call(kind, ordinal):
            if not KIND.match(kind) or ordinal < 0:
                raise ValueError(f"not a valid call: {kind!r}#{ordinal}")
            return f"{kind}#{ordinal}"
        case Branch(index):
            if index < 0:
                raise ValueError(f"not a valid branch: {index}")
            return str(index)
        case Item(key):
            return "item[" + key.replace("\\", "\\\\").replace("]", "\\]") + "]"
    raise TypeError(segment)


def format_path(path: Path) -> str:
    return "/".join(format_segment(segment) for segment in path)


def _split(text: str) -> list[str]:
    """Split on `/` outside `item[...]`, keeping escapes for the segment parser."""
    parts, current, in_item, i = [], [], False, 0
    while i < len(text):
        char = text[i]
        if in_item and char == "\\" and i + 1 < len(text):
            current += [char, text[i + 1]]
            i += 2
            continue
        if not in_item and char == "/":
            parts.append("".join(current))
            current = []
        else:
            if not in_item and "".join(current) == "item" and char == "[":
                in_item = True
            elif in_item and char == "]":
                in_item = False
            current.append(char)
        i += 1
    if in_item:
        raise ValueError(f"unclosed item key in {text!r}")
    parts.append("".join(current))
    return parts


def parse_segment(text: str) -> Segment:
    if text.startswith("item[") and text.endswith("]"):
        return Item(re.sub(r"\\(.)", r"\1", text[5:-1]))
    if text.isdigit() and (text == "0" or not text.startswith("0")):
        return Branch(int(text))
    kind, hash_, ordinal = text.partition("#")
    if hash_:
        if (
            KIND.match(kind)
            and ordinal.isdigit()
            and (ordinal == "0" or not ordinal.startswith("0"))
        ):
            return Call(kind, int(ordinal))
        raise ValueError(f"not a valid call: {text!r}")
    if NAME.match(text):
        return Name(text)
    raise ValueError(f"not a valid path segment: {text!r}")


def parse_path(text: str) -> Path:
    if not text:
        return ()
    return tuple(parse_segment(part) for part in _split(text))


def parse_address(text: str) -> tuple[str, Path]:
    """Split `<run>/<path>` into the run reference and the path."""
    run, _, rest = text.partition("/")
    if not RUN_REF.match(run):
        raise ValueError(f"not a valid run reference: {run!r}")
    return run, parse_path(rest)


def is_prefix(prefix: Path, path: Path) -> bool:
    """Whether `prefix` names `path` or a scope it was called in, by whole segments."""
    return path[: len(prefix)] == prefix


def workflow_id(run_id: str, scope: Path) -> str:
    """The DBOS workflow ID of a concurrent scope in a run's first attempt."""
    return run_id if not scope else f"{run_id}/{format_path(scope)}"
