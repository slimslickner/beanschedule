"""Tests for the read-only command line reporting."""

from __future__ import annotations

import json
from pathlib import Path

from beanschedule.cli import main

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
