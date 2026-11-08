"""Tests for the detector, migrate and the CLI surface."""

from __future__ import annotations

import argparse
from pathlib import Path

from beancount import loader

from beanschedule import detector, migrate
from beanschedule.cli import cmd_migrate, main
from beanschedule.core import compute

LEDGER = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:Power
2026-01-05 * "Edison Power" "bill"
  Assets:Bank   -100.00 USD
  Expenses:Power 100.00 USD
2026-02-05 * "Edison Power" "bill"
  Assets:Bank   -102.00 USD
  Expenses:Power 102.00 USD
2026-03-05 * "Edison Power" "bill"
  Assets:Bank   -101.00 USD
  Expenses:Power 101.00 USD
"""


def test_detector_proposes_monthly() -> None:
    entries, _errors, _options = loader.load_string(LEDGER)
    proposals = detector.detect(entries)
    assert proposals
    proposal = proposals[0]
    assert proposal.account == "Assets:Bank"
    assert proposal.payee == "Edison Power"
    assert proposal.rrule.startswith("FREQ=MONTHLY")
    assert proposal.confidence >= 0.6


def test_detector_ignores_covered_accounts() -> None:
    entries, _errors, options = loader.load_string(LEDGER)
    text = (
        'option "operating_currency" "USD"\n'
        '2026-01-01 custom "schedule" "new" "power"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=5"\n'
        "  start: 2026-01-05\n"
        '  match-account: "Assets:Bank"\n'
        '  amount-mode: "any"\n'
    )
    schedule_entries, _errs, _opts = loader.load_string(text)
    result = compute(schedule_entries + list(entries), options)
    assert detector.detect(entries, exclude=result) == []


def test_migrate_converts_yaml(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "schedules"
    directory.mkdir()
    (directory / "rent.yaml").write_text(
        "id: rent\n"
        "match:\n  account: Assets:Bank\n  payee_pattern: LANDLORD\n"
        "recurrence:\n  frequency: MONTHLY\n  start_date: 2026-01-01\n"
        "  day_of_month: 1\n"
        "transaction:\n  payee: Landlord\n  narration: Rent\n"
        "  postings:\n    - account: Expenses:Rent\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(directory=str(directory), ledger=None, schedules=None)
    assert cmd_migrate(args) == 0
    out = capsys.readouterr().out
    assert '"new" "rent"' in out
    assert "FREQ=MONTHLY" in out
    assert "Expenses:Rent" in out


def test_migrate_is_idempotent(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "schedules"
    directory.mkdir()
    (directory / "rent.yaml").write_text(
        "id: rent\nmatch:\n  account: Assets:Bank\n"
        "recurrence:\n  rrule: FREQ=MONTHLY\n  start_date: 2026-01-01\n"
        "transaction:\n  postings:\n    - account: Expenses:Rent\n",
        encoding="utf-8",
    )
    schedules = tmp_path / "Schedules.bean"
    schedules.write_text(
        '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n'
        "  start: 2026-01-01\n"
        '  match-account: "Assets:Bank"\n',
        encoding="utf-8",
    )
    args = argparse.Namespace(
        directory=str(directory), ledger=None, schedules=str(schedules)
    )
    assert cmd_migrate(args) == 0
    assert '"new" "rent"' not in capsys.readouterr().out


def test_cli_check_and_list(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "main.bean"
    ledger.write_text(
        'option "operating_currency" "USD"\n'
        "2020-01-01 open Assets:Bank\n"
        "2020-01-01 open Expenses:Tax\n"
        '2025-12-31 * "Opening"\n'
        "  Assets:Bank      1000.00 USD\n"
        "  Equity:Opening  -1000.00 USD\n"
        '2026-01-01 custom "schedule" "new" "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  start: 2026-01-15\n"
        '  match-account: "Assets:Bank"\n'
        '  amount-mode: "any"\n',
        encoding="utf-8",
    )
    assert main(["check", str(ledger), "--today", "2026-02-01"]) == 0
    assert main(["list", str(ledger), "--today", "2026-02-01"]) == 0
    out = capsys.readouterr().out
    assert "paycheck" in out


_LEGACY = Path(__file__).parent.parent / "examples" / "legacy"


def test_migrate_legacy_examples() -> None:
    migrations = migrate.directory(_LEGACY)
    ids = {migration.schedule_id for migration in migrations}
    assert {"paycheck-biweekly", "mortgage-amortized"} <= ids
    rendered = "\n".join(migrate.render(migration) for migration in migrations)
    assert "FREQ=WEEKLY;INTERVAL=2;BYDAY=TH" in rendered
    assert "VACHR" in rendered  # the multi-currency posting is reported
    assert 'method: "static"' in rendered
    assert "rate: 0.07" in rendered
    assert "term: 360" in rendered
    assert "escrow: 475.00" in rendered
    assert "will not balance (E011)" in rendered


def test_migrate_leaves_a_single_null_posting_alone(tmp_path) -> None:
    yaml_path = tmp_path / "p.yaml"
    yaml_path.write_text(
        "id: p\n"
        "match:\n  account: Assets:Bank\n  amount: -100.00\n"
        "recurrence:\n  rrule: FREQ=MONTHLY\n  start_date: 2026-01-01\n"
        "transaction:\n  postings:\n"
        "    - account: Assets:Bank\n      amount: null\n"
        "    - account: Expenses:A\n      amount: 40.00\n"
        "    - account: Expenses:B\n      amount: null\n",
        encoding="utf-8",
    )
    migration = migrate.file(yaml_path)
    assert migration is not None
    assert not any("E011" in warning for warning in migration.warnings)


def test_migrated_legacy_output_parses() -> None:
    migrations = [
        migration for migration in migrate.directory(_LEGACY) if not migration.disabled
    ]
    text = 'option "operating_currency" "USD"\n' + "\n\n".join(
        migrate.render(migration) for migration in migrations
    )
    _entries, errors, _options = loader.load_string(text)
    assert not errors, errors


def test_migrate_is_idempotent_over_examples() -> None:
    existing = [migration.schedule_id for migration in migrate.directory(_LEGACY)]
    assert migrate.directory(_LEGACY, existing) == []
