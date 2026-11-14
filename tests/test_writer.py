"""Tests for the transaction builders and the opt-in writer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from beancount.parser import parser

from beanschedule import actions, writer
from beanschedule.core import compute


def test_schedule_transaction_renders() -> None:
    txn = actions.schedule_transaction(
        "paycheck",
        date(2026, 1, 15),
        rrule="FREQ=MONTHLY;BYMONTHDAY=15",
        match_account="Assets:Bank",
        payee="Acme",
        match_amount=Decimal(-3000),
        amount_tolerance=Decimal("7.5"),
        postings=[
            ("Expenses:Taxes", Decimal(600), None),
            ("Expenses:Savings", Decimal(2400), None),
        ],
    )
    text = actions.render(txn)
    assert 'id: "paycheck"' in text
    assert 'rrule: "FREQ=MONTHLY;BYMONTHDAY=15"' in text
    assert "amount-tolerance: 7.50" in text
    assert text.index("id:") < text.index("rrule:") < text.index("match-account:")
    assert "Expenses:Taxes" in text


def test_from_rule_round_trips() -> None:
    text = """option "operating_currency" "USD"
2026-01-15 * "Acme" "Paycheck" #salary ^payroll
  id: "p"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  match-account: "Assets:Bank"
  amount-tolerance: 2.00
  category: "income"
  Assets:Bank     -100.00 USD
  Expenses:Tax     100.00 USD
    narration: "Tax"
"""
    entries, _errors, options = parser.parse_string(text)
    rule = compute(entries, options).rule("p")
    assert rule is not None
    rendered = actions.render(actions.from_rule(rule))
    assert 'rrule: "FREQ=MONTHLY;BYMONTHDAY=15"' in rendered
    assert "amount-tolerance: 2.00" in rendered
    assert "Expenses:Tax" in rendered
    assert 'narration: "Tax"' in rendered
    assert "#salary" in rendered
    assert "^payroll" in rendered
    assert 'category: "income"' in rendered


def test_from_rule_omits_defaults() -> None:
    text = """option "operating_currency" "USD"
2026-01-01 * "Acme" "Paycheck"
  id: "p"
  rrule: "FREQ=MONTHLY"
  Assets:Bank     -100.00 USD
  Expenses:Tax     100.00 USD
"""
    entries, _errors, options = parser.parse_string(text)
    rule = compute(entries, options).rule("p")
    assert rule is not None
    rendered = actions.render(actions.from_rule(rule))
    assert "window-before" not in rendered
    assert "window-after" not in rendered
    assert "amount-tolerance" not in rendered


def test_advance_changes_only_the_date() -> None:
    text = """option "operating_currency" "USD"
2026-01-01 * "Acme" "Paycheck"
  id: "p"
  rrule: "FREQ=MONTHLY"
  Assets:Bank     -100.00 USD
  Expenses:Tax     100.00 USD
"""
    entries, _errors, options = parser.parse_string(text)
    rule = compute(entries, options).rule("p")
    assert rule is not None
    advanced = actions.advance(rule, date(2026, 2, 1))
    assert advanced.date == date(2026, 2, 1)
    assert advanced.meta["id"] == "p"


def test_resolve_target_refuses_escape(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    ledger.touch()
    with pytest.raises(ValueError, match="outside the ledger directory"):
        writer.resolve_target(Path("../escape.bean"), tmp_path)
    with pytest.raises(ValueError, match="not a Beancount source file"):
        writer.resolve_target(Path("notes.txt"), tmp_path)


def test_apply_edits_deletes_and_replaces() -> None:
    lines = [
        '2026-01-01 * "Rent"\n',
        '  id: "rent"\n',
        "\n",
        '2026-02-01 * "Other"\n',
    ]
    replacement = '2026-03-01 * "Rent"\n  id: "rent"\n'
    line = parser.parse_string(replacement)[0][0]
    replaced = writer.apply_edits(lines, [(1, line)])
    assert replaced[0].startswith("2026-03-01")
    deleted = writer.apply_edits(lines, [(1, None)])
    assert deleted[0] == "\n"


def test_append_and_replace_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "schedules.bean"
    path.write_text("", encoding="utf-8")
    txn = actions.schedule_transaction(
        "a", date(2026, 1, 1), rrule="FREQ=MONTHLY", match_account="Assets:Bank"
    )
    writer.append(path, txn)
    assert path.read_text(encoding="utf-8").startswith("2026-01-01")
    moved = txn._replace(date=date(2026, 2, 1))
    writer.replace(path, 1, moved)
    assert "2026-02-01" in path.read_text(encoding="utf-8")
    writer.delete(path, 1)
    assert "2026-02-01" not in path.read_text(encoding="utf-8")
