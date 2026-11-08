"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from beancount import loader

from beanschedule.core import ScheduleResult, compute
from beanschedule.report import ScheduleViewResult, build_view

if TYPE_CHECKING:
    from collections.abc import Callable

_LEDGERS = Path(__file__).parent / "ledgers"


@pytest.fixture
def load_result() -> Callable[..., ScheduleResult]:
    """Return a loader computing the result for a fixture ledger.

    Returns:
        A callable mapping ``(name, today=...)`` to its
        :class:`~beanschedule.core.ScheduleResult`.
    """

    def _load(name: str, today: date | None = None) -> ScheduleResult:
        entries, _errors, options = loader.load_file(_LEDGERS / name)
        return compute(entries, options, today=today)

    return _load


@pytest.fixture
def load_view() -> Callable[..., ScheduleViewResult]:
    """Return a loader building the report view for a fixture ledger.

    Returns:
        A callable mapping ``(name, today=...)`` to its
        :class:`~beanschedule.report.ScheduleViewResult`.
    """

    def _load(name: str, today: date | None = None) -> ScheduleViewResult:
        entries, _errors, options = loader.load_file(_LEDGERS / name)
        result = compute(entries, options, today=today)
        return build_view(result, entries, options, today=today)

    return _load


@pytest.fixture
def load_ledger() -> Callable[..., tuple[list[object], dict[str, object]]]:
    """Return a loader giving a fixture ledger's entries and options.

    Returns:
        A callable mapping a fixture name to ``(entries, options)``.
    """

    def _load(name: str) -> tuple[list[object], dict[str, object]]:
        entries, _errors, options = loader.load_file(_LEDGERS / name)
        return list(entries), options

    return _load


@pytest.fixture
def compute_string() -> Callable[..., ScheduleResult]:
    """Return a helper computing the result for a ledger string.

    Returns:
        A callable mapping ``(text, today=...)`` to its
        :class:`~beanschedule.core.ScheduleResult`.
    """

    def _compute(text: str, today: date | None = None) -> ScheduleResult:
        entries, errors, options = loader.load_string(text)
        assert not errors, errors
        return compute(entries, options, today=today)

    return _compute
