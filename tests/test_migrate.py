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
    schedule_text = (
        'option "operating_currency" "USD"\n'
        '2026-01-05 * "Edison Power" "bill"\n'
        '  id: "power"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=5"\n'
        "  Assets:Bank  -100.00 USD\n"
        "  Expenses:Power  100.00 USD\n"
    )
    schedule_entries, _errs, _opts = loader.load_string(schedule_text)
    result = compute(
        list(schedule_entries) + list(entries), options, schedules=schedule_entries
    )
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
    assert 'id: "rent"' in out
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
    schedules = tmp_path / "schedules.bean"
    schedules.write_text(
        '2026-01-01 * "Landlord" "Rent"\n'
        '  id: "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n'
        '  match-account: "Assets:Bank"\n'
        "  Assets:Bank  -100.00 USD\n"
        "  Expenses:Rent  100.00 USD\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        directory=str(directory), ledger=None, schedules=str(schedules)
    )
    assert cmd_migrate(args) == 0
    assert 'id: "rent"' not in capsys.readouterr().out


def test_cli_check_and_list(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "main.bean"
    ledger.write_text(
        'option "operating_currency" "USD"\n'
        "2020-01-01 open Assets:Bank\n"
        "2020-01-01 open Expenses:Tax\n"
        "2020-01-01 open Equity:Opening\n"
        '2025-12-31 * "Opening"\n'
        "  Assets:Bank      1000.00 USD\n"
        "  Equity:Opening  -1000.00 USD\n",
        encoding="utf-8",
    )
    (tmp_path / "schedules.bean").write_text(
        '2026-01-15 * "Acme" "Paycheck"\n'
        '  id: "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n",
        encoding="utf-8",
    )
    assert main(["check", str(ledger), "--today", "2026-02-01"]) == 0
    assert main(["list", str(ledger), "--today", "2026-02-01"]) == 0
    out = capsys.readouterr().out
    assert "paycheck" in out


def test_cli_reconcile_batches_same_file_edits(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    ledger.write_text(
        'option "operating_currency" "USD"\n'
        "2020-01-01 open Assets:Bank\n"
        "2020-01-01 open Expenses:Tax\n"
        '2026-01-16 * "Acme" "January"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n"
        '2026-02-16 * "Acme" "February"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n",
        encoding="utf-8",
    )
    schedules = tmp_path / "schedules.bean"
    schedules.write_text(
        '2026-01-15 * "Acme" "Paycheck"\n'
        '  id: "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  Assets:Bank  -1000.00 USD\n"
        "  Expenses:Tax  1000.00 USD\n",
        encoding="utf-8",
    )
    args = [
        "reconcile",
        str(ledger),
        "--today",
        "2026-02-20",
        "--write",
        "schedules.bean",
    ]
    assert main(args) == 0
    entries, _errors, _options = loader.load_file(str(ledger))
    tagged = [
        entry
        for entry in entries
        if getattr(entry, "meta", {}).get("schedule") == "paycheck"
    ]
    assert len(tagged) == 2
    assert "2026-03-15" in schedules.read_text(encoding="utf-8")


def test_cli_reconcile_matches_a_weeks_worth_of_occurrences(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    ledger.write_text(
        'option "operating_currency" "USD"\n'
        "2020-01-01 open Assets:Bank\n"
        "2020-01-01 open Expenses:Sub\n"
        '2026-01-02 * "Weekly" "wk1"\n'
        "  Assets:Bank  -25.00 USD\n"
        "  Expenses:Sub  25.00 USD\n"
        '2026-01-09 * "Weekly" "wk2"\n'
        "  Assets:Bank  -25.00 USD\n"
        "  Expenses:Sub  25.00 USD\n"
        '2026-01-16 * "Weekly" "wk3"\n'
        "  Assets:Bank  -25.00 USD\n"
        "  Expenses:Sub  25.00 USD\n"
        '2026-01-23 * "Weekly" "wk4"\n'
        "  Assets:Bank  -25.00 USD\n"
        "  Expenses:Sub  25.00 USD\n"
        '2026-01-30 * "Weekly" "wk5"\n'
        "  Assets:Bank  -25.00 USD\n"
        "  Expenses:Sub  25.00 USD\n",
        encoding="utf-8",
    )
    schedules = tmp_path / "schedules.bean"
    schedules.write_text(
        '2026-01-01 * "Weekly" "Subscription"\n'
        '  id: "weekly"\n'
        '  rrule: "FREQ=WEEKLY;BYDAY=TH"\n'
        "  Assets:Bank  -25.00 USD\n"
        "  Expenses:Sub  25.00 USD\n",
        encoding="utf-8",
    )
    args = [
        "reconcile",
        str(ledger),
        "--today",
        "2026-02-06",
        "--write",
        "schedules.bean",
    ]
    assert main(args) == 0
    entries, _errors, _options = loader.load_file(str(ledger))
    tagged = [
        entry
        for entry in entries
        if getattr(entry, "meta", {}).get("schedule") == "weekly"
    ]
    assert len(tagged) == 5
    # The frontier advanced past all five to the next unmatched occurrence.
    assert "2026-02-05" in schedules.read_text(encoding="utf-8")


_LEGACY = Path(__file__).parent.parent / "examples" / "legacy"


def test_migrate_legacy_examples() -> None:
    migrations = migrate.directory(_LEGACY)
    ids = {migration.schedule_id for migration in migrations}
    assert {"paycheck-biweekly", "mortgage-amortized"} <= ids
    rendered = "\n".join(migrate.render(migration) for migration in migrations)
    assert 'id: "paycheck-biweekly"' in rendered
    assert "FREQ=WEEKLY;INTERVAL=2;BYDAY=TH" in rendered
    assert "VACHR" in rendered  # the multi-currency posting is reported
    assert 'method: "static"' in rendered
    assert "rate: 0.07" in rendered
    assert "term: 360" in rendered
    assert "escrow: 475" in rendered
    assert "will not balance (E011)" in rendered
    assert 'category: "income"' in rendered  # carried from the legacy metadata
    assert "transaction tags are dropped" not in rendered
    assert "transaction metadata" not in rendered


def test_migrate_carries_tags_links_and_metadata(tmp_path: Path) -> None:
    yaml_path = tmp_path / "p.yaml"
    yaml_path.write_text(
        "id: p\n"
        "match:\n  account: Assets:Bank\n  amount: -3000.00\n"
        "recurrence:\n  rrule: FREQ=MONTHLY\n  start_date: 2026-01-15\n"
        "transaction:\n  payee: Acme\n  narration: Pay\n"
        "  tags: [salary, recurring]\n  links: [payroll-2026]\n"
        "  metadata:\n    schedule_id: p\n    category: income\n"
        "  postings:\n    - account: Expenses:Tax\n      amount: 3000.00\n",
        encoding="utf-8",
    )
    migration = migrate.file(yaml_path)
    assert migration is not None
    rendered = migrate.render(migration)
    assert "#salary" in rendered
    assert "#recurring" in rendered
    assert "^payroll-2026" in rendered
    assert 'category: "income"' in rendered
    assert "schedule_id" not in rendered
    assert not any("dropped" in warning for warning in migration.warnings)


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


def test_migrated_legacy_output_renders_entries() -> None:
    migrations = [
        migration for migration in migrate.directory(_LEGACY) if not migration.disabled
    ]
    text = 'option "operating_currency" "USD"\n' + "\n\n".join(
        migrate.render(migration) for migration in migrations
    )
    entries, _errors, _options = loader.load_string(text)
    assert any(
        getattr(entry, "meta", {}).get("id") == "paycheck-biweekly" for entry in entries
    )


def test_migrate_is_idempotent_over_examples() -> None:
    existing = [migration.schedule_id for migration in migrate.directory(_LEGACY)]
    assert migrate.directory(_LEGACY, existing) == []
