"""Behavior of the ledger check: python3 -m unittest discover -s tools"""

import tempfile
import textwrap
import unittest
from pathlib import Path

import ledger

ACCEPTED_ADR = """\
---
id: ADR-0001
title: Use a ledger
status: accepted
---
## Context
"""


class LedgerCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write("docs/adr/0001-ledger.md", ACCEPTED_ADR)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")

    def problems(self) -> list[str]:
        (self.root / ledger.INDEX).write_text(ledger.render_index(ledger.load(self.root)[0]), encoding="utf-8")
        return ledger.check(self.root)

    def test_given_a_consistent_ledger_when_checked_then_it_passes(self) -> None:
        self.write("docs/questions/Q-001-shape.md", "---\nid: Q-001\ntitle: Shape\nstatus: answered\nanswered-by: ADR-0001\n---\nSee ADR-0001.\n")
        self.write("docs/spec/cli.md", "# CLI\n\n### CLI-001 Exit codes\nstatus: specified  decided-by: ADR-0001\n")
        self.assertEqual(self.problems(), [])

    def test_given_a_reference_to_an_undefined_id_when_checked_then_it_is_reported(self) -> None:
        self.write("docs/product.md", "Depends on Q-042.\n")
        self.assertIn("docs/product.md refers to Q-042, which is not defined", self.problems())

    def test_given_an_id_inside_code_when_checked_then_it_is_not_a_reference(self) -> None:
        self.write("docs/product.md", "Write `Q-042` like this:\n\n```\nid: H-999\n```\n")
        self.assertEqual(self.problems(), [])

    def test_given_an_answered_question_without_a_decision_when_checked_then_it_is_reported(self) -> None:
        self.write("docs/questions/Q-001-shape.md", "---\nid: Q-001\ntitle: Shape\nstatus: answered\n---\n")
        self.assertIn("docs/questions/Q-001-shape.md: Q-001 is answered but has no answered-by ADR", self.problems())

    def test_given_a_specified_requirement_citing_a_proposed_adr_when_checked_then_it_is_reported(self) -> None:
        self.write("docs/adr/0002-maybe.md", ACCEPTED_ADR.replace("0001", "0002").replace("accepted", "proposed"))
        self.write("docs/spec/cli.md", "### CLI-001 Exit codes\nstatus: specified  decided-by: ADR-0002\n")
        self.assertIn("docs/spec/cli.md: CLI-001 is specified but cites ADR-0002, which is not accepted", self.problems())

    def test_given_a_finished_hypothesis_without_a_result_when_checked_then_it_is_reported(self) -> None:
        self.write("experiments/H-001-server/README.md", "---\nid: H-001\ntitle: Server\nstatus: refuted\n---\n## Result\n\n## Evidence\n")
        self.assertIn("experiments/H-001-server/README.md: H-001 is refuted but its Result section is empty", self.problems())

    def test_given_an_unknown_status_when_checked_then_the_allowed_ones_are_listed(self) -> None:
        self.write("docs/principles.md", "### P-01 Attention first\nstatus: maybe\n")
        self.assertIn("docs/principles.md: P-01 has status 'maybe'; expected one of accepted, candidate, retired", self.problems())

    def test_given_a_duplicate_id_when_checked_then_it_is_reported(self) -> None:
        self.write("docs/adr/0001-copy.md", ACCEPTED_ADR)
        self.assertTrue(any("ADR-0001 is also defined" in p for p in self.problems()))

    def test_given_an_edit_after_indexing_when_checked_then_the_index_is_stale(self) -> None:
        self.problems()
        self.write("docs/adr/0001-ledger.md", ACCEPTED_ADR.replace("Use a ledger", "Use a register"))
        self.assertEqual(ledger.check(self.root), ["docs/INDEX.md is stale; run: python3 tools/ledger.py index"])

    def test_given_an_oversized_file_when_checked_then_it_is_reported(self) -> None:
        self.write("docs/product.md", "line\n" * (ledger.MAX_LINES + 1))
        self.assertIn(f"docs/product.md is over {ledger.MAX_LINES} lines; split it", self.problems())


if __name__ == "__main__":
    unittest.main()
