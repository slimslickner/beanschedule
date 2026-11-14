"""Tests for the read-only command line reporting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from beanschedule.cli import _complete_schedule, main

_LEDGER = Path(__file__).parent / "ledgers" / "extension" / "main.bean"


def test_list_json(capsys) -> None:
    code = main(["list", str(_LEDGER), "--today", "2026-01-01", "--json"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    ids = {row["id"] for row in rows}
    assert ids == {"paycheck", "loan-mortgage"}


def test_upcoming_json(capsys) -> None:
    code = main(["upcoming", str(_LEDGER), "--today", "2026-01-01", "--json"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows
    assert any(row["status"] == "overdue" for row in rows)
    assert {row["schedule"] for row in rows} == {"paycheck", "loan-mortgage"}


def test_upcoming_text(capsys) -> None:
    code = main(["upcoming", str(_LEDGER), "--today", "2026-01-01"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Schedule" in out
    assert "loan-mortgage" in out


def test_amortize_json(capsys) -> None:
    code = main(["amortize", str(_LEDGER), "--today", "2026-01-01", "--json"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    loan = rows[0]
    assert loan["id"] == "loan-mortgage"
    assert loan["method"] == "balance-from-ledger"
    assert loan["remaining_payments"] == len(loan["lines"])
    assert loan["payoff"]


def test_amortize_filters_by_id(capsys) -> None:
    code = main(
        [
            "amortize",
            str(_LEDGER),
            "--today",
            "2026-01-01",
            "--id",
            "paycheck",
            "--json",
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_report_text_aligns(capsys) -> None:
    code = main(["report", str(_LEDGER), "--today", "2026-02-01"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Nominal" in out
    assert "Effective" in out
    assert "loan-mortgage" in out


def test_upcoming_days_trims_to_window(capsys) -> None:
    code = main(
        [
            "upcoming",
            str(_LEDGER),
            "--today",
            "2026-01-01",
            "--days",
            "3",
            "--json",
        ]
    )
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    # Overdue occurrences are always kept; upcoming ones stop at the horizon.
    assert any(row["status"] == "overdue" for row in rows)
    assert all(row["nominal"] <= "2026-01-04" for row in rows)
    assert not any(row["schedule"] == "paycheck" for row in rows)


def test_list_days_filters_to_window(capsys) -> None:
    code = main(
        ["list", str(_LEDGER), "--today", "2026-01-01", "--days", "3", "--json"]
    )
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["id"] for row in rows} == {"loan-mortgage"}


def test_list_without_days_keeps_every_schedule(capsys) -> None:
    code = main(["list", str(_LEDGER), "--today", "2026-01-01", "--json"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["id"] for row in rows} == {"paycheck", "loan-mortgage"}


def test_report_days_trims_upcoming(capsys) -> None:
    code = main(
        ["report", str(_LEDGER), "--today", "2026-01-01", "--days", "3", "--json"]
    )
    assert code == 0
    schedules = {row["id"]: row for row in json.loads(capsys.readouterr().out)}
    # The paycheck's next occurrence (2026-01-15) is beyond the window.
    assert schedules["paycheck"]["lines"] == []


def test_days_rejects_negative() -> None:
    with pytest.raises(SystemExit):
        main(["upcoming", str(_LEDGER), "--days", "-1"])


def test_complete_schedule_offers_ids() -> None:
    parsed = argparse.Namespace(ledger=str(_LEDGER), schedules=None)
    assert _complete_schedule(
        prefix="", action=None, parser=None, parsed_args=parsed
    ) == ["loan-mortgage", "paycheck"]
    assert _complete_schedule(
        prefix="pay", action=None, parser=None, parsed_args=parsed
    ) == ["paycheck"]


def test_complete_schedule_without_ledger() -> None:
    parsed = argparse.Namespace(ledger=None, schedules=None)
    assert (
        _complete_schedule(prefix="", action=None, parser=None, parsed_args=parsed)
        == []
    )
