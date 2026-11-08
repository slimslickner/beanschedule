"""Tests for the beangulp hook and its pending support."""

from __future__ import annotations

from decimal import Decimal

from beancount.core import data
from beancount.parser import parser

from beanschedule.hook import schedule_hook

SCHEDULES = """2026-01-01 custom "schedule" "new" "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  start: 2026-01-15
  match-account: "Assets:Bank"
  match-payee: "Acme"
  amount-mode: "any"
  payee: "Acme Payroll"
"""


def _txn(text: str):
    entries, _errors, _options = parser.parse_string(text)
    return entries[0]


def test_hook_tags_matched_transaction(tmp_path, monkeypatch) -> None:
    schedules = tmp_path / "Schedules.bean"
    schedules.write_text(SCHEDULES, encoding="utf-8")
    monkeypatch.setenv("BEANSCHEDULE_SCHEDULES", str(schedules))
    txn = _txn(
        '2026-01-16 * "Acme" "January"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n"
    )
    items: list = [("bank.bean", [txn], None, None)]
    out = schedule_hook(items, [])
    enriched = out[0][1][0]
    assert isinstance(enriched, data.Transaction)
    assert enriched.meta["schedule"] == "paycheck"
    assert enriched.payee == "Acme Payroll"


def test_hook_leaves_unmatched(tmp_path, monkeypatch) -> None:
    schedules = tmp_path / "Schedules.bean"
    schedules.write_text(SCHEDULES, encoding="utf-8")
    monkeypatch.setenv("BEANSCHEDULE_SCHEDULES", str(schedules))
    txn = _txn(
        '2026-01-16 * "Someone else"\n'
        "  Assets:Other  -10.00 USD\n"
        "  Expenses:Tax   10.00 USD\n"
    )
    items: list = [("bank.bean", [txn], None, None)]
    out = schedule_hook(items, [])
    assert "schedule" not in out[0][1][0].meta


def test_hook_applies_declared_split(tmp_path, monkeypatch) -> None:
    schedules = tmp_path / "Schedules.bean"
    schedules.write_text(
        '2026-01-01 custom "schedule" "new" "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  start: 2026-01-15\n"
        '  match-account: "Assets:Bank"\n'
        "  match-amount: -1000.00\n"
        '  amount-mode: "exact"\n'
        '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Taxes"\n'
        "  amount: 600.00\n"
        '  narration: "withholding"\n'
        '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Savings"\n'
        "  amount: 400.00\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BEANSCHEDULE_SCHEDULES", str(schedules))
    txn = _txn(
        '2026-01-16 * "Acme" "January"\n'
        "  Assets:Bank      -1000.00 USD\n"
        "  Expenses:Unknown  1000.00 USD\n"
    )
    out = schedule_hook([("bank.bean", [txn], None, None)], [])
    enriched = out[0][1][0]
    assert isinstance(enriched, data.Transaction)
    accounts = {posting.account for posting in enriched.postings}
    assert accounts == {"Assets:Bank", "Expenses:Taxes", "Expenses:Savings"}
    numbers = {
        posting.account: posting.units.number
        for posting in enriched.postings
        if posting.units is not None
    }
    assert numbers["Expenses:Taxes"] == Decimal("600.00")
    assert enriched.postings[1].meta == {"narration": "withholding"}


def test_hook_without_schedules_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BEANSCHEDULE_SCHEDULES", raising=False)
    monkeypatch.delenv("BEANSCHEDULE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    txn = _txn(
        '2026-01-16 * "Acme"\n  Assets:Bank  -1.00 USD\n  Expenses:Tax  1.00 USD\n'
    )
    items: list = [("bank.bean", [txn], None, None)]
    assert schedule_hook(items, []) == items


def test_hook_matches_pending(tmp_path, monkeypatch) -> None:
    schedules = tmp_path / "Schedules.bean"
    schedules.write_text(SCHEDULES, encoding="utf-8")
    monkeypatch.setenv("BEANSCHEDULE_SCHEDULES", str(schedules))
    pending = tmp_path / "pending.beancount"
    pending.write_text(
        '2026-01-16 ! "Amazon" "Headphones"\n'
        "  Assets:Bank    -89.99 USD\n"
        "  Expenses:Electronics  89.99 USD\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BEANSCHEDULE_PENDING", str(pending))
    txn = _txn(
        '2026-01-16 * "AMAZON" "order"\n'
        "  Assets:Bank  -89.99 USD\n"
        "  Expenses:Uncategorised  89.99 USD\n"
    )
    items: list = [("bank.bean", [txn], None, None)]
    out = schedule_hook(items, [])
    enriched = out[0][1][0]
    assert isinstance(enriched, data.Transaction)
    assert enriched.narration == "Headphones"
    assert enriched.payee == "Amazon"
    assert "Amazon" not in pending.read_text(encoding="utf-8")


def test_hook_fills_balancer_posting(tmp_path, monkeypatch) -> None:
    schedules = tmp_path / "Schedules.bean"
    schedules.write_text(
        '2026-01-01 custom "schedule" "new" "p"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  start: 2026-01-15\n"
        '  match-account: "Assets:Bank"\n'
        "  match-amount: -1000.00\n"
        '  amount-mode: "exact"\n'
        '2026-01-01 custom "schedule" "posting" "p" "Expenses:A"\n'
        "  amount: 600.00\n"
        '2026-01-01 custom "schedule" "posting" "p" "Expenses:B"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BEANSCHEDULE_SCHEDULES", str(schedules))
    txn = _txn(
        '2026-01-16 * "Acme" "January"\n'
        "  Assets:Bank      -1000.00 USD\n"
        "  Expenses:Unknown  1000.00 USD\n"
    )
    out = schedule_hook([("bank.bean", [txn], None, None)], [])
    enriched = out[0][1][0]
    assert isinstance(enriched, data.Transaction)
    numbers = {
        posting.account: posting.units.number
        for posting in enriched.postings
        if posting.units is not None
    }
    assert numbers == {
        "Assets:Bank": Decimal("-1000.00"),
        "Expenses:A": Decimal("600.00"),
        "Expenses:B": Decimal("400.00"),
    }
