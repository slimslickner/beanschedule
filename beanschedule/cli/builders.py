"""Helper functions for building and completing CLI data."""

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pydantic
import yaml
from beancount.core import data

from beanschedule import constants
from beanschedule.loader import load_schedules_from_path
from beanschedule.types import DayOfWeek, FrequencyType

_WEEKDAY_RRULE = {
    DayOfWeek.MON: "MO",
    DayOfWeek.TUE: "TU",
    DayOfWeek.WED: "WE",
    DayOfWeek.THU: "TH",
    DayOfWeek.FRI: "FR",
    DayOfWeek.SAT: "SA",
    DayOfWeek.SUN: "SU",
}


def build_rrule(
    frequency: FrequencyType,
    day_of_month: int | None = None,
    month: int | None = None,
    day_of_week: DayOfWeek | None = None,
    interval: int = 1,
    days_of_month: list[int] | None = None,
    interval_months: int | None = None,
    nth_occurrence: int | None = None,
) -> str:
    """Build an RRULE string from discrete frequency parameters."""
    if frequency == FrequencyType.MONTHLY:
        return f"FREQ=MONTHLY;BYMONTHDAY={day_of_month}"
    if frequency == FrequencyType.WEEKLY:
        byday = _WEEKDAY_RRULE[day_of_week]
        parts = ["FREQ=WEEKLY"]
        if interval > 1:
            parts.append(f"INTERVAL={interval}")
        parts.append(f"BYDAY={byday}")
        return ";".join(parts)
    if frequency == FrequencyType.YEARLY:
        return f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day_of_month}"
    if frequency == FrequencyType.INTERVAL:
        return f"FREQ=MONTHLY;INTERVAL={interval_months};BYMONTHDAY={day_of_month}"
    if frequency in (FrequencyType.BIMONTHLY, FrequencyType.MONTHLY_ON_DAYS):
        days_str = ",".join(str(d) for d in (days_of_month or []))
        return f"FREQ=MONTHLY;BYMONTHDAY={days_str}"
    if frequency == FrequencyType.NTH_WEEKDAY:
        byday = _WEEKDAY_RRULE[day_of_week]
        nth = int(nth_occurrence or 1)
        prefix = f"+{nth}" if nth > 0 else str(nth)
        return f"FREQ=MONTHLY;BYDAY={prefix}{byday}"
    if frequency == FrequencyType.LAST_DAY_OF_MONTH:
        return "FREQ=MONTHLY;BYMONTHDAY=-1"
    raise ValueError(f"Unknown frequency: {frequency}")


logger = logging.getLogger(__name__)


def complete_schedule_id(ctx, _, incomplete):
    """Complete schedule IDs from the schedules path.

    Loads available schedule IDs and returns those matching the incomplete string.
    Falls back to default 'schedules' path if --schedules-path not yet parsed.
    Used for shell tab completion on schedule_id arguments.
    """
    # Try to get schedules-path from context, use default if not available or None
    schedules_path = ctx.params.get("schedules_path") or constants.DEFAULT_SCHEDULES_DIR
    path_obj = Path(schedules_path)

    try:
        # Load schedules silently for completion
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            return []

        # Return matching schedule IDs, sorted
        schedule_ids = sorted([s.id for s in schedule_file.schedules])
        return [sid for sid in schedule_ids if sid.startswith(incomplete)]
    except (ValueError, OSError, yaml.YAMLError, pydantic.ValidationError):
        return []


def day_of_week_from_date(d: date) -> DayOfWeek:
    """Get the DayOfWeek enum from a date."""
    # Python weekday: 0=Monday, 6=Sunday
    # DayOfWeek enum: MON=0, TUE=1, ..., SUN=6
    day_index = d.weekday()
    days = [
        DayOfWeek.MON,
        DayOfWeek.TUE,
        DayOfWeek.WED,
        DayOfWeek.THU,
        DayOfWeek.FRI,
        DayOfWeek.SAT,
        DayOfWeek.SUN,
    ]
    return days[day_index]


def extract_transaction_details(txn: data.Transaction) -> dict[str, Any]:
    """Extract schedule-relevant details from a beancount transaction.

    Returns:
        Dictionary with transaction details: date, payee, narration, account,
        amount, tags, and postings list.

    Raises:
        ValueError: If transaction has no postings.
    """
    if not txn.postings:
        raise ValueError("Transaction has no postings")

    first_posting = txn.postings[0]

    postings = []
    for posting in txn.postings:
        posting_dict = {
            "account": posting.account,
            "amount": float(posting.units.number)
            if posting.units and posting.units.number is not None
            else None,
            "narration": posting.meta.get("narration") if posting.meta else None,
        }
        postings.append(posting_dict)

    return {
        "date": txn.date,
        "payee": txn.payee,
        "narration": txn.narration,
        "account": first_posting.account,
        "amount": float(first_posting.units.number)
        if first_posting.units and first_posting.units.number is not None
        else None,
        "tags": list(txn.tags),
        "postings": postings,
    }


def build_schedule_dict(  # noqa: PLR0913
    schedule_id: str,
    txn_details: dict[str, Any],
    payee_pattern: str,
    amount_tolerance: Decimal,
    date_window_days: int,
    frequency: FrequencyType,
    day_of_month: int | None = None,
    month: int | None = None,
    day_of_week: DayOfWeek | None = None,
    interval: int = 1,
    days_of_month: list[int] | None = None,
    interval_months: int | None = None,
) -> dict[str, Any]:
    """Build a complete schedule dictionary matching the Pydantic schema."""
    rrule = build_rrule(
        frequency=frequency,
        day_of_month=day_of_month,
        month=month,
        day_of_week=day_of_week,
        interval=interval,
        days_of_month=days_of_month,
        interval_months=interval_months,
    )
    return {
        "id": schedule_id,
        "enabled": True,
        "match": {
            "account": txn_details["account"],
            "payee_pattern": payee_pattern,
            "amount": float(txn_details["amount"])
            if txn_details["amount"] is not None
            else None,
            "amount_tolerance": float(amount_tolerance),
            "amount_min": None,
            "amount_max": None,
            "date_window_days": date_window_days,
        },
        "recurrence": {
            "rrule": rrule,
            "start_date": str(txn_details["date"]),
            "end_date": None,
        },
        "transaction": {
            "payee": txn_details["payee"],
            "narration": txn_details["narration"],
            "tags": txn_details["tags"],
            "metadata": {
                "schedule_id": schedule_id,
            },
            "postings": txn_details["postings"],
        },
        "missing_transaction": {
            "create_placeholder": True,
            "flag": "!",
            "narration_prefix": "[MISSING]",
        },
    }


def save_detected_schedules(candidates: list, output_dir: Path) -> int:
    """Save detected candidates as YAML schedule files.

    Creates a schedules directory with individual YAML files for each
    detected pattern, ready to be customized and used.

    Args:
        candidates: List of RecurringCandidate objects.
        output_dir: Directory to save schedule files.

    Returns:
        Number of schedules saved.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create _config.yaml if it doesn't exist
    config_file = output_dir / "_config.yaml"
    if not config_file.exists():
        config = {
            "fuzzy_match_threshold": 0.80,
            "default_date_window_days": 3,
            "default_amount_tolerance_percent": 0.02,
            "placeholder_flag": "!",
        }
        with config_file.open("w") as f:
            yaml.dump(config, f)

    saved_count = 0

    for candidate in candidates:
        # Build schedule dictionary
        schedule_dict = {
            "id": candidate.schedule_id,
            "enabled": True,
            "match": {
                "account": candidate.account,
                "payee_pattern": candidate.payee_pattern,
                "amount": float(candidate.amount),
                "amount_tolerance": float(candidate.amount_tolerance),
                "amount_min": None,
                "amount_max": None,
                "date_window_days": 3,
            },
            "recurrence": {
                "rrule": build_rrule(
                    frequency=candidate.frequency.frequency,
                    day_of_month=candidate.frequency.day_of_month,
                    month=candidate.frequency.month,
                    day_of_week=candidate.frequency.day_of_week,
                    interval=candidate.frequency.interval or 1,
                    interval_months=candidate.frequency.interval_months,
                ),
                "start_date": str(candidate.first_date),
                "end_date": None,
            },
            "transaction": {
                "payee": candidate.payee,
                "narration": f"{candidate.frequency.formatted_name()} transaction",
                "tags": [],
                "metadata": {
                    "schedule_id": candidate.schedule_id,
                },
                "postings": None,
            },
            "missing_transaction": {
                "create_placeholder": True,
                "flag": "!",
                "narration_prefix": "[MISSING]",
            },
        }

        # Write YAML file
        output_file = output_dir / f"{candidate.schedule_id}.yaml"
        with output_file.open("w") as f:
            f.write(f"# Auto-detected {candidate.frequency.formatted_name()} pattern\n")
            f.write(
                f"# Confidence: {candidate.confidence * 100:.0f}% ({candidate.transaction_count} transactions)\n",
            )
            f.write(f"# Date range: {candidate.first_date} to {candidate.last_date}\n")
            f.write(f"# Payee: {candidate.payee}\n\n")
            yaml.dump(
                schedule_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        saved_count += 1
        logger.info("Saved schedule: %s", output_file)

    return saved_count
