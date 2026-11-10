"""Tests for the Beancount plugin: pending relabelling and schedule validation."""

from __future__ import annotations

from pathlib import Path

from beancount import loader
from beancount.core import data

from beanschedule import plugin

SCHEDULES = """2026-01-15 * "Acme" "Paycheck"
  id: "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  Assets:Bank     -1000.00 USD
  Expenses:Tax     1000.00 USD
"""


def _entries(text: str):
    entries, _errors, options = loader.load_string(text)
    return list(entries), options


def test_relabels_pending_transactions(tmp_path: Path) -> None:
    entries, _options = _entries(
        '2026-01-16 * "Amazon" "Headphones"\n'
        "  Assets:Bank    -89.99 USD\n"
        "  Expenses:Electronics  89.99 USD\n"
    )
    pending_path = tmp_path / "pending.bean"
    relabelled = [
        entry._replace(meta={**entry.meta, "filename": str(pending_path)})
        if isinstance(entry, data.Transaction)
        else entry
        for entry in entries
    ]
    out = plugin.relabel_pending(relabelled, "pending.bean", "pending", "!")
    txn = out[0]
    assert isinstance(txn, data.Transaction)
    assert "pending" in txn.tags
    assert txn.flag == "!"


def test_plugin_reports_schedule_diagnostics(tmp_path: Path) -> None:
    main = tmp_path / "main.bean"
    main.touch()
    (tmp_path / "schedules.bean").write_text(
        '2026-01-15 * "Acme" "Paycheck"\n  id: "bad"\n',
        encoding="utf-8",
    )
    entries, options = _entries('option "operating_currency" "USD"\n')
    options = {**options, "filename": str(main)}
    _out, errors = plugin.plugin(entries, options)
    assert any("missing required metadata" in error.message for error in errors)


def test_plugin_loads_when_schedules_absent(tmp_path: Path) -> None:
    main = tmp_path / "main.bean"
    main.touch()
    entries, options = _entries('option "operating_currency" "USD"\n')
    options = {**options, "filename": str(main)}
    out, errors = plugin.plugin(entries, options)
    assert out == entries
    assert not errors


def test_load_schedules_keeps_amount_less_amortization_legs(tmp_path: Path) -> None:
    # A schedule with two amount-less legs must survive loading; the strict
    # Beancount loader would drop it ("more than one auto-posting").
    path = tmp_path / "schedules.bean"
    path.write_text(
        '2026-01-01 * "Chase" "Loan"\n'
        '  id: "loan"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"\n'
        '  method: "static"\n'
        "  rate: 0.06\n"
        "  term: 12\n"
        "  Assets:Bank  -1200.00 USD\n"
        "  Liabilities:Loan\n"
        '    schedule-leg: "principal"\n'
        "  Expenses:X\n"
        '    schedule-leg: "interest"\n',
        encoding="utf-8",
    )
    schedules = plugin.load_schedules(path)
    assert len(schedules) == 1
    assert schedules[0].meta["id"] == "loan"


def test_plugin_config_keys(tmp_path: Path) -> None:
    main = tmp_path / "main.bean"
    main.touch()
    (tmp_path / "my-schedules.bean").write_text(SCHEDULES, encoding="utf-8")
    entries, options = _entries('option "operating_currency" "USD"\n')
    options = {**options, "filename": str(main)}
    config = "{'schedules_file': 'my-schedules.bean', 'pending_tag': 'waiting'}"
    _out, errors = plugin.plugin(entries, options, config)
    assert not errors


def test_plugin_config_accepts_a_mapping(tmp_path: Path) -> None:
    main = tmp_path / "main.bean"
    main.touch()
    entries, options = _entries('option "operating_currency" "USD"\n')
    options = {**options, "filename": str(main)}
    _out, errors = plugin.plugin(entries, options, {"pending_tag": "pending"})
    assert not errors


def test_pending_ledger_loads_with_plugin(tmp_path: Path) -> None:
    main = tmp_path / "main.bean"
    (tmp_path / "pending.bean").write_text(
        '2026-01-16 * "Amazon" "Headphones"\n'
        "  Assets:Bank    -89.99 USD\n"
        "  Expenses:Electronics  89.99 USD\n",
        encoding="utf-8",
    )
    main.write_text(
        'include "pending.bean"\n'
        'plugin "beanschedule.plugin"\n'
        'option "operating_currency" "USD"\n'
        "2020-01-01 open Assets:Bank\n"
        "2020-01-01 open Expenses:Electronics\n",
        encoding="utf-8",
    )
    entries, errors, _options = loader.load_file(str(main))
    assert not errors, errors
    pending = [entry for entry in entries if isinstance(entry, data.Transaction)]
    assert pending
    assert "pending" in pending[0].tags
