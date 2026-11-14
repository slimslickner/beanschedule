"""Tests for the RRULE form helpers."""

from __future__ import annotations

import pytest

from beanschedule import recurrence


def test_build_rrule_defaults_to_frequency_only() -> None:
    assert recurrence.build_rrule("monthly") == "FREQ=MONTHLY"


def test_build_rrule_includes_interval_byday_bymonthday() -> None:
    text = recurrence.build_rrule(
        "WEEKLY", interval=2, byday=("MO", "FR"), bymonthday=None, bymonth=3
    )
    assert text == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;BYMONTH=3"


def test_build_rrule_rejects_an_invalid_frequency() -> None:
    with pytest.raises(ValueError, match="invalid rrule"):
        recurrence.build_rrule("NEVER")


def test_rrule_fields_round_trips_a_built_rule() -> None:
    text = recurrence.build_rrule("MONTHLY", interval=3, bymonthday=15)
    assert recurrence.rrule_fields(text) == recurrence.RuleFields(
        freq="MONTHLY", interval=3, bymonthday=15
    )


def test_rrule_fields_defaults_are_lenient() -> None:
    assert recurrence.rrule_fields("EVERY DAY").freq == ""
    assert recurrence.rrule_fields("").interval == 1
