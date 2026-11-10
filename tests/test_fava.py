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


def test_overview_renders_schedules() -> None:
    html = _render(_extension(), {})
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
