"""Tests for the shared report view."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from beanschedule.report import (
    STATUS_OVERDUE,
    STATUS_POSTED,
    STATUS_UPCOMING,
    format_money,
    operating_currency,
)


def test_view_statuses(load_view) -> None:
    view = load_view("basic.bean", today=date(2026, 2, 1))
    schedule = view.schedule("paycheck")
    assert schedule is not None
    assert view.currency == "USD"
    assert schedule.next == date(2026, 2, 15)
    statuses = {line.nominal: line.status for line in schedule.lines}
    assert statuses[date(2026, 1, 16)] == STATUS_POSTED
    assert statuses[date(2026, 2, 15)] == STATUS_UPCOMING
    assert schedule.rule_hash


def test_view_overdue(load_view) -> None:
    view = load_view("stale.bean", today=date(2026, 6, 15))
    schedule = view.schedule("rent")
    assert schedule is not None
    statuses = {line.nominal: line.status for line in schedule.lines}
    assert statuses[date(2026, 1, 1)] == STATUS_OVERDUE
    assert statuses[date(2026, 2, 1)] == STATUS_OVERDUE
    assert schedule.overdue


def test_errors_and_warnings_split(load_view) -> None:
    view = load_view("stale.bean", today=date(2026, 6, 15))
    assert not view.errors
    assert [warning.code for warning in view.warnings] == ["W001"]


def test_format_and_currency() -> None:
    assert format_money(None) == "-"
    assert format_money(Decimal("12.5"), "USD") == "12.50 USD"
    assert operating_currency({"operating_currency": "USD"}) == "USD"
    assert operating_currency({}) == ""
    assert operating_currency({"operating_currency": ["EUR"]}) == "EUR"


def test_due_classification(load_view) -> None:
    view = load_view("basic.bean", today=date(2026, 2, 13))
    schedule = view.schedule("paycheck")
    assert schedule is not None
    due = {line.nominal for line in schedule.lines if line.due}
    assert date(2026, 2, 15) in due
    # A far reference date leaves the occurrence merely upcoming.
    early = load_view("basic.bean", today=date(2026, 2, 1)).schedule("paycheck")
    assert early is not None
    assert not any(line.due for line in early.lines)


def test_ledger_flattens_and_orders(load_view) -> None:
    view = load_view("basic.bean", today=date(2026, 2, 13))
    rows = view.ledger(pending_only=True)
    assert [row.line.nominal for row in rows] == [
        date(2026, 2, 15),
        date(2026, 3, 15),
        date(2026, 4, 15),
    ]
    assert rows[0].schedule_id == "paycheck"
    assert rows[0].line.due
    assert not rows[1].line.due


def test_static_amortization_projection(load_view) -> None:
    view = load_view("amortized.bean", today=date(2026, 1, 1))
    schedule = view.schedule("loan")
    assert schedule is not None
    amortization = schedule.amortization
    assert amortization is not None
    assert amortization.method == "static"
    assert amortization.remaining_payments == 360
    assert amortization.payoff_date == date(2055, 12, 1)
    assert amortization.remaining_total == (
        amortization.remaining_principal
        + amortization.remaining_interest
        + amortization.remaining_escrow
    )
