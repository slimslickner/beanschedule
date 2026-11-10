"""Tests for the shipped example ledger's file split."""

from __future__ import annotations

from pathlib import Path

from beancount import loader
from beancount.core import data

from beanschedule.plugin import load_schedules

_EXAMPLES = Path(__file__).parent.parent / "examples"


def _load(name: str):
    entries, errors, options = loader.load_file(str(_EXAMPLES / name))
    assert not errors, errors
    return list(entries), options


def _txns(entries) -> list:
    return [entry for entry in entries if isinstance(entry, data.Transaction)]


def test_import_ledger_excludes_pending_and_schedules() -> None:
    entries, _options = _load("import.bean")
    transactions = _txns(entries)
    assert transactions
    # No pending placeholders (they would defeat beangulp's duplicate detection).
    assert not any("pending" in (txn.tags or frozenset()) for txn in transactions)
    # No schedule definitions (they live in schedules.bean, read by path).
    assert not any("id" in (txn.meta or {}) for txn in transactions)


def test_main_ledger_includes_tagged_pending() -> None:
    entries, _options = _load("main.bean")
    assert any("pending" in (txn.tags or frozenset()) for txn in _txns(entries))


def test_schedules_file_is_loadable_by_path() -> None:
    schedules = load_schedules(_EXAMPLES / "schedules.bean")
    assert [entry.meta["id"] for entry in schedules] == ["paycheck"]
