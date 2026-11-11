"""Check the spec ledger and generate its index.

    python3 tools/ledger.py check   # fail on any rule violation or a stale docs/INDEX.md
    python3 tools/ledger.py index   # rewrite docs/INDEX.md

The ledger's rules are described in docs/adr/0001-spec-ledger.md. Standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_LINES = 300
INDEX = Path("docs/INDEX.md")

STATUSES = {
    "ADR": {"proposed", "accepted", "rejected", "deprecated", "superseded"},
    "Q": {"open", "answered", "dropped"},
    "H": {"planned", "running", "confirmed", "refuted", "inconclusive"},
    "P": {"candidate", "accepted", "retired"},
    "REQ": {"draft", "specified", "implemented", "verified", "dropped"},
}
SECTIONS = [
    ("ADR", "Decisions"),
    ("Q", "Questions"),
    ("H", "Hypotheses"),
    ("P", "Principles"),
    ("REQ", "Requirements"),
]
REQ_PREFIXES = "ARCH|SDK|CLI|TUI|DM"
ID_RE = re.compile(rf"\b(ADR-\d{{4}}|Q-\d{{3}}|H-\d{{3}}|P-\d{{2}}|(?:{REQ_PREFIXES})-\d{{3}})\b")
HEADING_ITEM_RE = re.compile(rf"^#{{2,4}} (P-\d{{2}}|(?:{REQ_PREFIXES})-\d{{3}}) (.+)$")
FIELD_RE = re.compile(r"([a-z][a-z-]*): (\S+)")
TERMINAL_HYPOTHESIS = {"confirmed", "refuted", "inconclusive"}
NORMATIVE_REQ = {"specified", "implemented", "verified"}


@dataclass
class Item:
    id: str
    title: str
    path: str
    fields: dict[str, object] = field(default_factory=dict)
    body: str = ""

    @property
    def kind(self) -> str:
        prefix = self.id.split("-")[0]
        return prefix if prefix in STATUSES else "REQ"

    @property
    def status(self) -> str:
        return str(self.fields.get("status", ""))


def ledger_files(root: Path) -> list[Path]:
    docs = [p for p in (root / "docs").rglob("*.md") if "templates" not in p.relative_to(root).parts]
    docs = [p for p in docs if p.relative_to(root) != INDEX]
    return sorted(docs + list((root / "experiments").glob("*/README.md")))


def split_front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        return {}, text
    fields: dict[str, object] = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            fields[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            fields[key.strip()] = value
    return fields, body


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def parse_file(path: Path, rel: str) -> tuple[list[Item], str]:
    text = path.read_text(encoding="utf-8")
    fields, body = split_front_matter(text)
    items = []
    if "id" in fields:
        items.append(Item(str(fields["id"]), str(fields.get("title", "")), rel, fields, body))
    lines = body.splitlines()
    for n, line in enumerate(lines):
        match = HEADING_ITEM_RE.match(line)
        if match:
            meta = next((l for l in lines[n + 1 :] if l.strip()), "")
            item_fields = dict(FIELD_RE.findall(meta.replace("`", "")))
            items.append(Item(match.group(1), match.group(2).strip(), rel, item_fields))
    return items, text


def section(body: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", body, flags=re.M | re.S)
    return match.group(1).strip() if match else ""


def item_problems(item: Item, items: dict[str, Item]) -> list[str]:
    where = f"{item.path}: {item.id}"
    problems = []
    if not item.title:
        problems.append(f"{where} has no title")
    if item.status not in STATUSES[item.kind]:
        allowed = ", ".join(sorted(STATUSES[item.kind]))
        problems.append(f"{where} has status '{item.status}'; expected one of {allowed}")
    name = Path(item.path).name
    if item.kind == "ADR" and not name.startswith(item.id.removeprefix("ADR-") + "-"):
        problems.append(f"{where} must live in a file named {item.id.removeprefix('ADR-')}-*.md")
    if item.kind in ("Q", "H") and not (name.startswith(item.id + "-") or Path(item.path).parent.name.startswith(item.id + "-")):
        problems.append(f"{where} must live in a file or directory named {item.id}-*")
    if item.kind == "Q" and item.status == "answered" and not str(item.fields.get("answered-by", "")).startswith("ADR-"):
        problems.append(f"{where} is answered but has no answered-by ADR")
    if item.kind == "ADR" and item.status == "superseded" and "superseded-by" not in item.fields:
        problems.append(f"{where} is superseded but has no superseded-by")
    if item.kind == "H" and item.status in TERMINAL_HYPOTHESIS and not section(item.body, "Result"):
        problems.append(f"{where} is {item.status} but its Result section is empty")
    if item.kind == "REQ" and item.status in NORMATIVE_REQ:
        decided_by = item.fields.get("decided-by")
        if decided_by and items.get(str(decided_by), Item("", "", "")).status != "accepted":
            problems.append(f"{where} is {item.status} but cites {decided_by}, which is not accepted")
        if item.status == "verified" and "verify" not in item.fields:
            problems.append(f"{where} is verified but names no verify target")
    return problems


def load(root: Path) -> tuple[dict[str, Item], dict[str, str], list[str]]:
    items: dict[str, Item] = {}
    texts: dict[str, str] = {}
    problems: list[str] = []
    for path in ledger_files(root):
        rel = path.relative_to(root).as_posix()
        found, texts[rel] = parse_file(path, rel)
        for item in found:
            if item.id in items:
                problems.append(f"{rel}: {item.id} is also defined in {items[item.id].path}")
            items[item.id] = item
    return items, texts, problems


def check(root: Path) -> list[str]:
    items, texts, problems = load(root)
    for rel, text in texts.items():
        if text.count("\n") > MAX_LINES:
            problems.append(f"{rel} is over {MAX_LINES} lines; split it")
        for ref in sorted(set(ID_RE.findall(strip_code(text))) - items.keys()):
            problems.append(f"{rel} refers to {ref}, which is not defined")
    for item in items.values():
        problems += item_problems(item, items)
    index = root / INDEX
    if not index.exists() or index.read_text(encoding="utf-8") != render_index(items):
        problems.append(f"{INDEX} is stale; run: python3 tools/ledger.py index")
    return problems


def render_index(items: dict[str, Item]) -> str:
    out = [
        "# Index",
        "",
        "Every ID in the ledger, generated by `python3 tools/ledger.py index`. Don't edit by hand.",
    ]
    for kind, heading in SECTIONS:
        rows = sorted((i for i in items.values() if i.kind == kind), key=lambda i: i.id)
        if not rows:
            continue
        out += ["", f"## {heading}", "", "| ID | Title | Status | File |", "|---|---|---|---|"]
        out += [f"| {i.id} | {i.title} | {i.status} | [{i.path}]({os.path.relpath(i.path, INDEX.parent)}) |" for i in rows]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    command = argv[1] if len(argv) > 1 else "check"
    if command == "index":
        (root / INDEX).write_text(render_index(load(root)[0]), encoding="utf-8")
        return 0
    if command == "check":
        problems = check(root)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
