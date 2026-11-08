"""Tests for the shared report view."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from beanschedule.report import (
    STATUS_MOVED,
    STATUS_OVERDUE,
    STATUS_POSTED,
    STATUS_SKIPPED,
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
    assert statuses[date(2026, 1, 15)] == STATUS_POSTED
    assert statuses[date(2026, 2, 15)] == STATUS_UPCOMING
    assert schedule.rule_hash


def test_view_stale_outcomes(load_view) -> None:
    view = load_view("stale.bean", today=date(2026, 6, 15))
    schedule = view.schedule("rent")
    assert schedule is not None
    statuses = {line.nominal: line.status for line in schedule.lines}
    assert statuses[date(2026, 2, 1)] == STATUS_SKIPPED
    assert statuses[date(2026, 3, 1)] == STATUS_MOVED
    assert statuses[date(2026, 1, 1)] == STATUS_OVERDUE
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
