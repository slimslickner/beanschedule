"""Tests for the directive builders and the opt-in writer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from beancount.parser import parser

from beanschedule import actions, writer
from beanschedule.core import compute


def test_new_renders_registry_order() -> None:
    entry = actions.new(
        "paycheck",
        date(2026, 1, 1),
        rrule="FREQ=MONTHLY;BYMONTHDAY=15",
        start=date(2026, 1, 15),
        match_account="Assets:Bank",
        match_payee="Acme",
        match_amount=Decimal(-3000),
        amount_mode="approx",
        amount_tolerance=Decimal("7.5"),
        payee="Acme",
        narration="Paycheck",
    )
    text = actions.render(entry)
    assert '"new" "paycheck"' in text
    assert 'rrule: "FREQ=MONTHLY;BYMONTHDAY=15"' in text
    assert "match-amount: -3000.00" in text
    assert text.index("rrule:") < text.index("start:") < text.index("match-account:")


def test_posting_renders_amount_and_metadata() -> None:
    entry = actions.posting(
        "paycheck",
        "Expenses:Taxes:Federal",
        date(2026, 1, 1),
        amount=Decimal(600),
        metadata={"contribution-year": 2026},
    )
    text = actions.render(entry)
    assert '"posting" "paycheck" "Expenses:Taxes:Federal"' in text
    assert "amount: 600.00" in text
    assert "contribution-year: 2026" in text


def test_skip_and_move_render() -> None:
    assert actions.render(actions.skip("p", date(2026, 12, 15))) == (
        '2026-12-15 custom "schedule" "skip" "p"'
    )
    assert actions.render(
        actions.move("p", date(2026, 12, 15), date(2026, 12, 20))
    ) == ('2026-12-15 custom "schedule" "move" "p" 2026-12-20')


def test_from_rule_round_trips() -> None:
    text = """option "operating_currency" "USD"
2026-01-01 custom "schedule" "new" "p"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  start: 2026-01-15
  match-account: "Assets:Bank"
  match-amount: -100.00
  amount-mode: "exact"
2026-01-01 custom "schedule" "posting" "p" "Expenses:Tax"
  amount: 100.00
  narration: "Tax"
"""
    entries, _errors, options = parser.parse_string(text)
    result = compute(entries, options)
    rule = result.rule("p")
    assert rule is not None
    rendered = [actions.render(entry) for entry in actions.from_rule(rule)]
    assert 'rrule: "FREQ=MONTHLY;BYMONTHDAY=15"' in rendered[0]
    assert "match-amount: -100.00" in rendered[0]
    assert '"posting" "p" "Expenses:Tax"' in rendered[1]
    assert "amount: 100.00" in rendered[1]
    assert 'narration: "Tax"' in rendered[1]


def test_from_rule_omits_defaults() -> None:
    text = """option "operating_currency" "USD"
2026-01-01 custom "schedule" "new" "p"
  rrule: "FREQ=MONTHLY"
  start: 2026-01-01
  match-account: "Assets:Bank"
"""
    entries, _errors, options = parser.parse_string(text)
    rule = compute(entries, options).rule("p")
    assert rule is not None
    rendered = actions.render(actions.from_rule(rule)[0])
    assert "window-before" not in rendered
    assert "window-after" not in rendered
    assert "amount-mode" not in rendered


def test_resolve_target_refuses_escape(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    ledger.touch()
    with pytest.raises(ValueError, match="outside the ledger directory"):
        writer.resolve_target(Path("../escape.bean"), tmp_path)
    with pytest.raises(ValueError, match="not a Beancount source file"):
        writer.resolve_target(Path("notes.txt"), tmp_path)


def test_apply_edits_deletes_and_replaces() -> None:
    lines = [
        '2026-01-01 custom "schedule" "new" "a"\n',
        '  rrule: "FREQ=MONTHLY"\n',
        "\n",
        '2026-02-01 custom "schedule" "skip" "a"\n',
    ]
    replaced = writer.apply_edits(lines, [(1, actions.skip("a", date(2026, 1, 1)))])
    assert replaced[0].startswith("2026-01-01")
    assert replaced[1].startswith("  ") is False
    deleted = writer.apply_edits(lines, [(1, None)])
    assert deleted[0] == "\n"


def test_append_and_replace_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "Schedules.bean"
    path.write_text("", encoding="utf-8")
    writer.append(path, actions.skip("a", date(2026, 1, 1)))
    assert path.read_text(encoding="utf-8").startswith("2026-01-01")
    writer.replace(path, 1, actions.move("a", date(2026, 1, 1), date(2026, 1, 5)))
    assert "move" in path.read_text(encoding="utf-8")
    writer.delete(path, 1)
    assert "move" not in path.read_text(encoding="utf-8")
