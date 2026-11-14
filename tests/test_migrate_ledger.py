"""Tests for the v1-tracking ledger migration."""

from __future__ import annotations

from pathlib import Path

from beanschedule import migrate_ledger
from beanschedule.cli import main

LEDGER = """option "operating_currency" "USD"

2020-01-01 open Assets:Bank
2020-01-01 open Expenses:Tax
2020-01-01 open Equity:Opening

; An enriched v1 transaction with the whole tracking trail.
2026-01-16 * "Acme" "January"
  schedule_id: "paycheck"
  schedule_matched_date: 2026-01-16
  schedule_confidence: 0.95
  amortization_principal: 100.00
  Assets:Bank    -1000.00 USD
  Expenses:Tax    1000.00 USD

; A v1 placeholder for a missing occurrence.
2026-02-15 * "Acme" "[MISSING] February"
  schedule_placeholder: TRUE
  Assets:Bank    -1000.00 USD
  Expenses:Tax    1000.00 USD
"""


def _write_ledger(tmp_path: Path) -> Path:
    ledger = tmp_path / "main.bean"
    ledger.write_text(LEDGER, encoding="utf-8")
    return ledger


def test_scan_finds_all_three_changes(tmp_path: Path) -> None:
    plan = migrate_ledger.scan(_write_ledger(tmp_path))
    assert len(plan) == 1
    assert plan[0].placeholders == 1
    assert plan[0].stripped == 3  # matched_date, confidence, amortization_principal
    assert plan[0].renamed == 1


def test_scan_is_empty_when_clean(tmp_path: Path) -> None:
    clean = tmp_path / "main.bean"
    clean.write_text(
        'option "operating_currency" "USD"\n'
        '2026-01-16 * "Acme" "January"\n'
        '  schedule: "paycheck"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n",
        encoding="utf-8",
    )
    assert migrate_ledger.scan(clean) == []


def test_summarise_reports_counts(tmp_path: Path) -> None:
    plan = migrate_ledger.scan(_write_ledger(tmp_path))
    summary = migrate_ledger.summarise(plan)
    assert "1 placeholder(s)" in summary
    assert "3 tracking metadata line(s)" in summary
    assert "1 schedule_id(s) renamed" in summary
    assert migrate_ledger.summarise([]) == "nothing to migrate"


def test_apply_strips_renames_and_preserves_the_rest(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path)
    before = ledger.read_text(encoding="utf-8")
    plans = migrate_ledger.scan(ledger)
    migrate_ledger.apply(plans)
    after = ledger.read_text(encoding="utf-8")
    assert before != after
    # The link is renamed, the tracking trail and the placeholder are gone.
    assert 'schedule: "paycheck"' in after
    assert "schedule_id" not in after
    assert "schedule_matched_date" not in after
    assert "schedule_confidence" not in after
    assert "amortization_principal" not in after
    assert "schedule_placeholder" not in after
    assert "MISSING" not in after
    # Comments and unrelated transactions survive, byte for byte.
    assert "; An enriched v1 transaction" in after
    assert "; A v1 placeholder" in after
    assert "2020-01-01 open Assets:Bank" in after
    assert "  Assets:Bank    -1000.00 USD" in after


def test_apply_is_idempotent(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path)
    migrate_ledger.apply(migrate_ledger.scan(ledger))
    assert migrate_ledger.scan(ledger) == []


def test_both_keys_drop_the_legacy_one(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    ledger.write_text(
        'option "operating_currency" "USD"\n'
        '2026-01-16 * "Acme" "January"\n'
        '  schedule: "paycheck"\n'
        '  schedule_id: "paycheck"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n",
        encoding="utf-8",
    )
    migrate_ledger.apply(migrate_ledger.scan(ledger))
    after = ledger.read_text(encoding="utf-8")
    assert after.count('schedule: "paycheck"') == 1
    assert "schedule_id" not in after


def test_cli_dry_run_then_write(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path)
    before = ledger.read_text(encoding="utf-8")
    assert main(["migrate-ledger", str(ledger)]) == 0
    assert ledger.read_text(encoding="utf-8") == before  # dry run
    assert main(["migrate-ledger", str(ledger), "--write"]) == 0
    assert 'schedule: "paycheck"' in ledger.read_text(encoding="utf-8")
