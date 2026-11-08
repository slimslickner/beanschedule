"""Tests for the Beancount plugin and forecast injection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from beancount import loader
from beancount.core import data

from beanschedule import plugin
from beanschedule.core import compute

LEDGER = """option "operating_currency" "USD"
2026-01-01 custom "schedule" "new" "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  start: 2026-01-15
  match-account: "Assets:Bank"
  match-amount: -1000.00
  amount-mode: "exact"
  payee: "Acme"
2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Tax"
  amount: 1000.00
"""


def _entries_options(text: str):
    entries, _errors, options = loader.load_string(text)
    return entries, options


def test_plugin_reports_diagnostics() -> None:
    entries, options = _entries_options(
        'option "operating_currency" "USD"\n2026-01-01 custom "schedule" "new" "bad"\n'
    )
    _out, errors = plugin.plugin(entries, options)
    assert any("missing required metadata" in error.message for error in errors)


def test_forecast_entries_built_when_asked() -> None:
    entries, options = _entries_options(LEDGER)
    result = compute(entries, options, today=date(2026, 1, 1))
    forecast = plugin.forecast_entries(
        result, entries, options, months=2, today=date(2026, 1, 1)
    )
    assert forecast
    assert all(
        isinstance(entry, data.Transaction) and entry.flag == "#" for entry in forecast
    )
    assert all(entry.meta[plugin.SCHEDULE_KEY] == "paycheck" for entry in forecast)
    assert all(entry.meta[plugin.FORECAST_KEY] for entry in forecast)
    assert forecast[0].date == date(2026, 1, 15)
    first = forecast[0]
    assert isinstance(first, data.Transaction)
    accounts = {posting.account for posting in first.postings}
    assert accounts == {"Assets:Bank", "Expenses:Tax"}


def test_plugin_config_forecast_appends() -> None:
    entries, options = _entries_options(LEDGER)
    out, _errors = plugin.plugin(entries, options, "forecast")
    assert len(out) > len(entries)


def test_plugin_config_mapping() -> None:
    entries, options = _entries_options(LEDGER)
    out, _errors = plugin.plugin(entries, options, {"forecast": True, "months": 1})
    assert len(out) > len(entries)


def test_plugin_config_string_mapping() -> None:
    entries, options = _entries_options(LEDGER)
    out, _errors = plugin.plugin(entries, options, "{'forecast': True, 'months': 1}")
    assert len(out) > len(entries)


def test_plugin_config_bare_forecast() -> None:
    entries, options = _entries_options(LEDGER)
    out, _errors = plugin.plugin(entries, options, "forecast")
    assert len(out) > len(entries)


def test_forecast_skips_amountless_rules() -> None:
    entries, options = _entries_options(
        'option "operating_currency" "USD"\n'
        '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"\n'
        "  start: 2026-01-01\n"
        '  match-account: "Assets:Bank"\n'
        '  amount-mode: "any"\n'
    )
    result = compute(entries, options, today=date(2026, 1, 1))
    assert (
        plugin.forecast_entries(result, entries, options, today=date(2026, 1, 1)) == []
    )


BALANCER = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:A
2020-01-01 open Expenses:B
2026-01-01 custom "schedule" "new" "p"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  start: 2026-01-15
  match-account: "Assets:Bank"
  match-amount: -100.00
  amount-mode: "exact"
2026-01-01 custom "schedule" "posting" "p" "Expenses:A"
  amount: 60.00
2026-01-01 custom "schedule" "posting" "p" "Expenses:B"
"""


def test_forecast_fills_balancer_posting() -> None:
    entries, options = _entries_options(BALANCER)
    result = compute(entries, options, today=date(2026, 1, 1))
    forecast = plugin.forecast_entries(
        result, entries, options, months=1, today=date(2026, 1, 1)
    )
    assert forecast
    first = forecast[0]
    assert isinstance(first, data.Transaction)
    units = {posting.account: posting.units for posting in first.postings}
    balancer = units["Expenses:B"]
    assert balancer is not None
    assert balancer.number == Decimal("40.00")


def test_forecast_balancer_loads_without_crashing() -> None:
    text = (
        BALANCER
        + "plugin \"beanschedule.plugin\" \"{'forecast': True, 'months': 1}\"\n"
    )
    _entries, errors, _options = loader.load_string(text)
    assert not errors, errors
