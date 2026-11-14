"""Tests for the Fava extension and its template."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import jinja2
import pytest
from beancount import loader

from beanschedule import fava_ext
from beanschedule.fava_ext import Schedules

if TYPE_CHECKING:
    from collections.abc import Mapping

    from beancount.core.data import Transaction
    from fava.core import FavaLedger

_LEDGERS = Path(__file__).parent / "ledgers"
_TEMPLATES = Path(fava_ext.__file__).parent / "templates"


def _extension(config: str | None = None) -> Schedules:
    path = _LEDGERS / "extension" / "main.bean"
    entries, _errors, options = loader.load_file(str(path))
    ledger = cast(
        "FavaLedger",
        SimpleNamespace(
            all_entries=entries,
            options=options,
            beancount_file_path=str(path),
            accounts=dict.fromkeys(
                (
                    "Assets:Bank:Checking",
                    "Liabilities:Loans:Mortgage",
                    "Expenses:House:Interest",
                    "Expenses:House:Escrow",
                    "Expenses:Taxes:Federal",
                    "Expenses:Savings",
                    "Equity:Opening-Balances",
                )
            ),
        ),
    )
    extension = Schedules(ledger, config)
    extension.after_load_file()
    return extension


def _render(extension: Schedules, args: Mapping[str, str]) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES)),
        autoescape=True,
    )
    request = SimpleNamespace(args=dict(args), path="/ledger/extension/Schedules/")
    return env.get_template("Schedules.html").render(
        ledger=extension.ledger, extension=extension, request=request
    )


def test_schedule_loads_despite_amount_less_legs() -> None:
    extension = _extension()
    ids = extension.schedule_ids()
    assert "loan-mortgage" in ids
    assert "paycheck" in ids


def test_default_tab_is_upcoming() -> None:
    html = _render(_extension(), {})
    assert (
        '<a class="schedule-tab schedule-tab-active" href="?view=upcoming">Upcoming</a>'
        in html
    )
    assert "All Schedules" in html
    assert "Detail" in html


def test_report_loads_its_js_as_a_fava_module() -> None:
    # Fava runs the extension's JS module on navigation; an inline <script>
    # would not execute for a client-side navigation, so the report has none.
    assert Schedules.has_js_module is True
    module = Path(fava_ext.__file__).parent / "Schedules.js"
    assert module.is_file()


def test_template_has_no_inline_script() -> None:
    html = _render(_extension("{'write': True}"), {"view": "schedule", "new": "1"})
    assert "<script>" not in html
    assert "</script>" not in html


def test_overview_renders_schedules() -> None:
    html = _render(_extension(), {"view": "overview"})
    assert "loan-mortgage" in html
    assert "paycheck" in html
    assert "?view=schedule" in html


def test_upcoming_tab_marks_statuses() -> None:
    html = _render(_extension(), {"view": "upcoming"})
    assert "Upcoming" in html
    assert "loan-mortgage" in html
    assert "overdue" in html.lower() or "upcoming" in html.lower()


def test_drilldown_shows_amortization() -> None:
    html = _render(_extension(), {"view": "schedule", "id": "loan-mortgage"})
    assert "Amortization" in html
    assert "Remaining payments" in html
    assert "Principal" in html
    assert "Escrow" in html


def test_drilldown_shows_source_editor_when_writable() -> None:
    html = _render(
        _extension("{'write': True}"), {"view": "schedule", "id": "paycheck"}
    )
    assert 'name="source"' in html
    assert "paycheck" in html
    assert "FREQ=MONTHLY;BYMONTHDAY=15" in html


def test_drilldown_readonly_without_write() -> None:
    html = _render(_extension(), {"view": "schedule", "id": "paycheck"})
    assert 'name="source"' not in html
    assert "read-only" in html


def test_schedule_source_round_trips() -> None:
    extension = _extension()
    source = extension.schedule_source("paycheck")
    assert 'id: "paycheck"' in source
    assert 'rrule: "FREQ=MONTHLY;BYMONTHDAY=15"' in source


def test_amortization_summary_is_correct() -> None:
    amortization = _extension().amortization("loan-mortgage")
    assert amortization is not None
    assert amortization.method == "balance-from-ledger"
    assert amortization.remaining_payments > 0
    # Principal plus interest plus escrow equals the total remaining.
    assert (
        amortization.remaining_principal
        + amortization.remaining_interest
        + amortization.remaining_escrow
        == amortization.remaining_total
    )
    first = amortization.lines[0]
    assert first.principal > 0
    assert first.interest > 0
    assert first.escrow > 0


def test_save_rejects_source_without_a_transaction() -> None:
    extension = _extension("{'write': True}")
    with pytest.raises(ValueError, match="exactly one transaction"):
        extension._save({"source": "; just a comment\n"})


def test_save_rejects_source_without_an_id() -> None:
    extension = _extension("{'write': True}")
    source = (
        '2026-01-01 * "X" "Y"\n'
        "  Assets:Bank:Checking  -1.00 USD\n"
        "  Expenses:X              1.00 USD\n"
    )
    with pytest.raises(ValueError, match="id"):
        extension._save({"source": source})


def test_save_rewrites_the_non_source_schedules_file(tmp_path: Path) -> None:
    source_dir = _LEDGERS / "extension"
    for name in ("main.bean", "schedules.bean"):
        shutil.copy(source_dir / name, tmp_path / name)
    path = tmp_path / "main.bean"
    entries, _errors, options = loader.load_file(str(path))
    notified: list[Path] = []
    ledger = SimpleNamespace(
        all_entries=entries,
        options=options,
        beancount_file_path=str(path),
        file=SimpleNamespace(_lock=threading.Lock()),
        watcher=SimpleNamespace(notify=notified.append),
        load_file=lambda: None,
    )
    extension = Schedules(cast("FavaLedger", ledger), "{'write': True}")
    extension.after_load_file()
    source = (
        '2026-01-15 * "Acme" "Paycheck" #payroll\n'
        '  id: "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=16"\n'
        '  match-payee: "Acme"\n'
        "  amount-tolerance: 7.50\n"
        "  Assets:Bank:Checking       -3000.00 USD\n"
        "  Expenses:Taxes:Federal       600.00 USD\n"
        "  Expenses:Savings            2400.00 USD\n"
    )
    extension.perform({"action": "save", "id": "paycheck", "source": source})
    written = (tmp_path / "schedules.bean").read_text()
    assert "BYMONTHDAY=16" in written
    assert "BYMONTHDAY=15" not in written
    assert tmp_path / "schedules.bean" in notified


def _tmp_ledger(tmp_path: Path) -> SimpleNamespace:
    source_dir = _LEDGERS / "extension"
    for name in ("main.bean", "schedules.bean"):
        shutil.copy(source_dir / name, tmp_path / name)
    path = tmp_path / "main.bean"
    entries, _errors, options = loader.load_file(str(path))
    return SimpleNamespace(
        all_entries=entries,
        options=options,
        beancount_file_path=str(path),
        accounts={},
        file=SimpleNamespace(_lock=threading.Lock()),
        watcher=SimpleNamespace(notify=lambda _path: None),
        load_file=lambda: None,
    )


def test_all_schedules_offers_a_new_schedule_button() -> None:
    html = _render(_extension("{'write': True}"), {"view": "overview"})
    assert "?view=schedule&amp;new=1" in html
    assert "New schedule" in html
    # The create form itself lives on the Detail tab.
    assert 'name="freq"' not in html


def test_detail_create_renders_the_structured_form() -> None:
    html = _render(_extension("{'write': True}"), {"view": "schedule", "new": "1"})
    assert 'id="schedule-accounts"' in html
    assert 'value="Assets:Bank:Checking"' in html
    assert 'name="schedule_type"' in html
    assert "Normal schedule" in html
    assert "Amortization schedule" in html
    assert 'name="freq"' in html
    assert 'name="posting_account"' in html
    assert 'name="bymonthday"' in html
    # A normal schedule hides and disables the amortization fields.
    assert 'name="method" disabled' in html
    assert "schedule-amort" in html


def test_amortized_form_preselects_legs() -> None:
    html = _render(
        _extension("{'write': True}"), {"view": "schedule", "id": "loan-mortgage"}
    )
    assert '<option value="principal" selected>' in html
    assert '<option value="interest" selected>' in html
    assert '<option value="escrow" selected>' in html
    assert 'name="method" disabled' not in html


def test_upcoming_rows_link_to_the_drilldown() -> None:
    html = _render(_extension(), {"view": "upcoming"})
    assert 'class="schedule-rowlink"' in html
    assert "?view=schedule" in html
    assert "schedule-badge schedule-upcoming" in html


def test_structured_create_builds_the_rrule_and_postings() -> None:
    entry = fava_ext._schedule_entry(
        {
            "id": "rent",
            "start": "2026-02-01",
            "account": "Assets:Bank:Checking",
            "freq": "MONTHLY",
            "interval": "1",
            "bymonthday": "1",
            "posting_account": ["Expenses:Rent", "Assets:Bank:Checking"],
            "posting_amount": ["1500.00", ""],
            "payee": "Landlord",
        },
        "USD",
    )
    assert entry.meta["rrule"] == "FREQ=MONTHLY;BYMONTHDAY=1"
    assert entry.meta["match-account"] == "Assets:Bank:Checking"
    transaction = cast("Transaction", entry)
    accounts = [posting.account for posting in transaction.postings]
    assert accounts == [
        "Assets:Bank:Checking",
        "Expenses:Rent",
        "Assets:Bank:Checking",
    ]


def test_structured_create_builds_a_weekly_rrule() -> None:
    entry = fava_ext._schedule_entry(
        {
            "id": "gym",
            "start": "2026-02-02",
            "account": "Assets:Bank:Checking",
            "freq": "WEEKLY",
            "interval": "2",
            "byday": ["MO", "FR"],
        },
        "USD",
    )
    assert entry.meta["rrule"] == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR"


def test_structured_update_rewrites_the_schedule_in_place(tmp_path: Path) -> None:
    ledger = _tmp_ledger(tmp_path)
    extension = Schedules(cast("FavaLedger", ledger), "{'write': True}")
    extension.after_load_file()
    extension.perform(
        {
            "action": "update",
            "original_id": "paycheck",
            "id": "paycheck",
            "start": "2026-01-15",
            "account": "Assets:Bank:Checking",
            "freq": "MONTHLY",
            "bymonthday": "16",
            "posting_account": ["Expenses:Taxes:Federal", "Expenses:Savings"],
            "posting_amount": ["600.00", "2400.00"],
            "payee": "Acme",
            "narration": "Paycheck",
            "amount": "-3000.00",
        }
    )
    written = (tmp_path / "schedules.bean").read_text()
    assert "BYMONTHDAY=16" in written
    assert "BYMONTHDAY=15" not in written


def test_structured_update_keeps_amortization_legs(tmp_path: Path) -> None:
    ledger = _tmp_ledger(tmp_path)
    extension = Schedules(cast("FavaLedger", ledger), "{'write': True}")
    extension.after_load_file()
    extension.perform(
        {
            "action": "update",
            "original_id": "loan-mortgage",
            "id": "loan-mortgage",
            "start": "2024-01-01",
            "account": "Assets:Bank:Checking",
            "freq": "MONTHLY",
            "bymonthday": "4",
            "method": "balance-from-ledger",
            "rate": "0.04875",
            "escrow": "368.52",
            "posting_account": [
                "Assets:Bank:Checking",
                "Expenses:House:Escrow",
                "Expenses:House:Interest",
                "Liabilities:Loans:Mortgage",
            ],
            "posting_amount": ["-2505.20", "368.52", "", ""],
            "posting_leg": ["", "escrow", "interest", "principal"],
        }
    )
    written = (tmp_path / "schedules.bean").read_text()
    assert 'method: "balance-from-ledger"' in written
    assert 'schedule-leg: "principal"' in written
    assert 'schedule-leg: "interest"' in written
    assert 'schedule-leg: "escrow"' in written
