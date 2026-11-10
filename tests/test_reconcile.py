"""Tests for post-import reconciliation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from beancount import loader

from beanschedule import actions, core, reconcile
from beanschedule.pending import PendingPosting, PendingTransaction

SCHEDULE = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:Tax

2026-02-15 * "Acme" "Paycheck"
  id: "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  Assets:Bank     -3000.00 USD
  Expenses:Tax     3000.00 USD
"""

REAL = """2026-02-16 * "Acme" "February"
  Assets:Bank     -3000.00 USD
  Expenses:Tax     3000.00 USD
"""


def _load(text: str):
    entries, _errors, options = loader.load_string(text)
    return list(entries), options


def _schedules(entries):
    return [entry for entry in entries if core.is_schedule(entry)]


def test_plan_matches_and_advances() -> None:
    entries, options = _load(SCHEDULE + REAL)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 20))
    assert len(plan.matches) == 1
    match = plan.matches[0]
    assert match.nominal == date(2026, 2, 15)
    assert match.transaction.date == date(2026, 2, 16)
    assert len(plan.advances) == 1
    assert plan.advances[0].new_date == date(2026, 3, 15)


def test_plan_empty_when_nothing_matches() -> None:
    entries, options = _load(SCHEDULE)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 20))
    assert plan.matches == ()
    assert plan.advances == ()
    assert plan.empty


def test_already_tagged_transactions_are_not_candidates() -> None:
    tagged = REAL.replace(
        '2026-02-16 * "Acme" "February"',
        '2026-02-16 * "Acme" "February"\n  schedule: "paycheck"',
    )
    entries, options = _load(SCHEDULE + tagged)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 20))
    assert plan.matches == ()


def test_plan_enriches_the_transaction() -> None:
    entries, options = _load(SCHEDULE + REAL)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 20))
    enriched = reconcile.enrich(plan.matches[0])
    assert enriched.meta["schedule"] == "paycheck"
    assert enriched.payee == "Acme"
    accounts = {posting.account for posting in enriched.postings}
    assert accounts == {"Assets:Bank", "Expenses:Tax"}


def test_pending_is_consumed_first() -> None:
    pending = PendingTransaction(
        date=date(2026, 2, 16),
        account="Assets:Bank",
        amount=Decimal("-3000.00"),
        payee="Amazon",
        narration="Headphones",
        postings=(
            PendingPosting("Assets:Bank", Decimal("-3000.00")),
            PendingPosting("Expenses:Tax", Decimal("3000.00")),
        ),
        source=Path("pending.bean"),
    )
    entries, options = _load(SCHEDULE + REAL)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, [pending], options)
    assert len(plan.pending) == 1
    assert plan.pending[0].transaction.date == date(2026, 2, 16)
    assert plan.matches == ()


def test_enrich_pending_renames_the_transaction() -> None:
    pending = PendingTransaction(
        date=date(2026, 2, 16),
        account="Assets:Bank",
        amount=Decimal("-3000.00"),
        payee="Amazon",
        narration="Headphones",
        postings=(
            PendingPosting("Assets:Bank", Decimal("-3000.00")),
            PendingPosting("Expenses:Tax", Decimal("3000.00")),
        ),
        source=Path("pending.bean"),
    )
    entries, options = _load(SCHEDULE + REAL)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, [pending], options)
    enriched = reconcile.enrich_pending(plan.pending[0])
    assert enriched.narration == "Headphones"
    assert enriched.payee == "Amazon"


TAGGED_SCHEDULE = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:Tax

2026-02-15 * "Acme" "Paycheck" #salary ^payroll-2026
  id: "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  category: "income"
  Assets:Bank     -3000.00 USD
  Expenses:Tax     3000.00 USD
    narration: "withholding"
"""


def test_enrich_carries_tags_links_and_metadata() -> None:
    entries, options = _load(TAGGED_SCHEDULE + REAL)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 20))
    enriched = reconcile.enrich(plan.matches[0])
    assert "salary" in enriched.tags
    assert "payroll-2026" in enriched.links
    assert enriched.meta["category"] == "income"
    assert enriched.meta["schedule"] == "paycheck"
    taxes = next(p for p in enriched.postings if p.account == "Expenses:Tax")
    assert taxes.meta == {"narration": "withholding"}


AMORTIZED = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Liabilities:Loan
2020-01-01 open Expenses:Interest

2026-01-01 * "Chase" "Mortgage"
  id: "loan"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"
  method: "static"
  rate: 0.06
  term: 360
  Assets:Bank              -1000.00 USD
  Liabilities:Loan           900.00 USD
    schedule-leg: "principal"
    narration: "principal leg"
  Expenses:Interest          100.00 USD
    schedule-leg: "interest"
    narration: "interest leg"

2026-01-02 * "Chase" "payment"
  Assets:Bank              -1000.00 USD
  Liabilities:Loan           900.00 USD
  Expenses:Interest          100.00 USD
"""


def test_enrich_carries_amortized_leg_metadata() -> None:
    entries, options = _load(AMORTIZED)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 1, 5))
    assert plan.matches, plan
    enriched = reconcile.enrich(plan.matches[0])
    leg_meta = {
        posting.account: posting.meta
        for posting in enriched.postings
        if posting.meta is not None
    }
    assert leg_meta["Liabilities:Loan"] == {"narration": "principal leg"}
    assert leg_meta["Expenses:Interest"] == {"narration": "interest leg"}


WEEKLY = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:Sub

2026-01-01 * "Weekly" "Subscription"
  id: "weekly"
  rrule: "FREQ=WEEKLY;BYDAY=TH"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD

2026-01-02 * "Weekly" "wk1"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD
2026-01-09 * "Weekly" "wk2"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD
2026-01-16 * "Weekly" "wk3"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD
2026-01-23 * "Weekly" "wk4"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD
2026-01-30 * "Weekly" "wk5"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD
"""


def _apply_plan(entries, plan):
    """Apply a plan in memory, as the CLI does: enrich, then advance.

    Args:
        entries: The ledger entries.
        plan: The plan.

    Returns:
        The ``(entries, schedules)`` after application.
    """
    enriched: dict[int, object] = {}
    for match in plan.matches:
        enriched[id(match.transaction)] = reconcile.enrich(match)
    for match in plan.pending:
        enriched[id(match.transaction)] = reconcile.enrich_pending(match)
    advanced = {
        id(advance.rule.entry): actions.advance(advance.rule, advance.new_date)
        for advance in plan.advances
        if advance.new_date is not None and advance.rule.entry is not None
    }
    removed = {
        id(advance.rule.entry)
        for advance in plan.advances
        if advance.new_date is None and advance.rule.entry is not None
    }
    updated = [
        advanced.get(id(entry), enriched.get(id(entry), entry))
        for entry in entries
        if id(entry) not in removed
    ]
    schedules = [entry for entry in updated if core.is_schedule(entry)]
    return updated, schedules


def test_plan_matches_multiple_occurrences_in_one_pass() -> None:
    entries, options = _load(WEEKLY)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 6))
    assert len(plan.matches) == 5
    assert [(m.nominal, m.transaction.date) for m in plan.matches] == [
        (date(2026, 1, 1), date(2026, 1, 2)),
        (date(2026, 1, 8), date(2026, 1, 9)),
        (date(2026, 1, 15), date(2026, 1, 16)),
        (date(2026, 1, 22), date(2026, 1, 23)),
        (date(2026, 1, 29), date(2026, 1, 30)),
    ]
    assert [(advance.rule.id, advance.new_date) for advance in plan.advances] == [
        ("weekly", date(2026, 2, 5))
    ]


def test_multi_occurrence_plan_is_idempotent() -> None:
    entries, options = _load(WEEKLY)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 2, 6))
    applied, advanced = _apply_plan(entries, plan)
    again = reconcile.plan(applied, advanced, (), options, today=date(2026, 2, 6))
    assert again.empty


def test_half_gap_stops_an_adjacent_occurrence_stealing_a_match() -> None:
    ledger = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:Sub

2026-01-08 * "Weekly" "Subscription"
  id: "weekly"
  rrule: "FREQ=WEEKLY;BYDAY=TH"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD

2026-01-11 * "Weekly" "midweek"
  Assets:Bank  -25.00 USD
  Expenses:Sub  25.00 USD
"""
    entries, options = _load(ledger)
    schedules = _schedules(entries)
    plan = reconcile.plan(entries, schedules, (), options, today=date(2026, 1, 20))
    assert [match.nominal for match in plan.matches] == [date(2026, 1, 8)]
