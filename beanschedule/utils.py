"""Utility functions for beanschedule.

This module provides shared utilities used by both the hook (for import matching)
and the plugin (for forecast generation). These utilities handle:

1. Transaction Indexing
   - Organize transactions by date, schedule_id, or other attributes
   - Enable O(1) lookups instead of O(n) scans

2. Occurrence Generation
   - Generate expected occurrence dates for schedules
   - Support filtering to avoid duplicates with existing transactions

3. Schedule ID Querying
   - Find transactions and dates associated with specific schedules

By centralizing these utilities, both the hook and plugin can reuse the same
logic without duplication, ensuring consistency and making maintenance easier.

Usage Patterns:
  - Hook uses generate_all_schedule_occurrences() for batch account-grouped matching
  - Plugin uses generate_schedule_occurrences() per-schedule and then filters
  - Both use build_date_index() for fast date-based lookups
  - Plugin uses get_scheduled_dates_from_entries() to avoid duplicate forecasts
"""

import re
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Optional

from beancount.core import data

if TYPE_CHECKING:
    from .schema import Schedule
    from .recurrence import RecurrenceEngine


def get_scheduled_dates_from_entries(
    entries: list[data.Directive],
    schedule_id: str,
    include_forecast: bool = False,
) -> set[date]:
    """Get all dates in entries that have a specific schedule_id.

    This utility is used primarily by the plugin to find which dates already
    have actual (or forecast) transactions for a given schedule. This allows
    the plugin to avoid generating duplicate forecast transactions.

    Example: If paycheck-captech has a transaction on 2026-02-05, this function
    will return {2026-02-05, ...}, allowing the plugin to skip generating a
    forecast for that date.

    Args:
        entries: List of beancount entries (typically the full ledger)
        schedule_id: The schedule_id to search for (e.g., "paycheck-captech")
        include_forecast: If True, include forecast transactions (flag="#")
                         If False (default), only include actual transactions.
                         The plugin uses False to find existing actual transactions,
                         excluding forecasts it might have already generated.

    Returns:
        Set of dates where transactions with this schedule_id exist
        (empty set if no matches found)
    """
    dates = set()

    for entry in entries:
        if isinstance(entry, data.Transaction):
            # Skip forecast transactions if requested
            if not include_forecast and entry.flag == "#":
                continue

            # Check if transaction has matching schedule_id
            if entry.meta.get("schedule_id") == schedule_id:
                dates.add(entry.date)

    return dates


def get_transactions_by_schedule_id(
    entries: list[data.Directive],
    schedule_id: str,
    include_forecast: bool = False,
) -> list[data.Transaction]:
    """Get all transactions matching a specific schedule_id.

    Similar to get_scheduled_dates_from_entries(), but returns the full
    Transaction objects rather than just dates. Useful when you need to
    inspect posting amounts, payees, or other transaction details.

    Args:
        entries: List of beancount entries (typically the full ledger)
        schedule_id: The schedule_id to search for (e.g., "paycheck-captech")
        include_forecast: If True, include forecast transactions (flag="#")
                         If False (default), only include actual transactions

    Returns:
        List of Transaction objects with matching schedule_id
        (empty list if no matches found)
    """
    transactions = []

    for entry in entries:
        if isinstance(entry, data.Transaction):
            # Skip forecast transactions if requested
            if not include_forecast and entry.flag == "#":
                continue

            # Check if transaction has matching schedule_id
            if entry.meta.get("schedule_id") == schedule_id:
                transactions.append(entry)

    return transactions


def build_date_index(
    ledger_entries: Optional[list[data.Directive]],
) -> dict[date, list[data.Transaction]]:
    """Build an index mapping dates to transactions for fast lookups.

    This index enables O(1) date lookups instead of O(n) scans through all
    entries. Used by the hook for lazy matching: instead of checking all
    ledger entries for potential matches, it only checks transactions on
    the relevant date.

    Performance Note: Building this index is O(n) but pays off immediately
    if you'll be doing multiple date lookups.

    Args:
        ledger_entries: Existing ledger entries (can be None for empty ledger)

    Returns:
        Dict mapping date -> List of transactions on that date.
        Returns empty dict if ledger_entries is None or empty.
    """
    index = defaultdict(list)

    if not ledger_entries:
        return index

    for entry in ledger_entries:
        if isinstance(entry, data.Transaction):
            index[entry.date].append(entry)

    return index


def build_scheduled_transactions_index(
    entries: list[data.Directive],
) -> dict[str, set[date]]:
    """Build an index of transactions by schedule_id and date.

    This index prevents the plugin from generating duplicate forecasts.
    For each schedule_id that appears in the ledger, it tracks which dates
    already have actual (non-forecast) transactions.

    Used by: filter_occurrences_by_existing_transactions() to skip dates
    that shouldn't have forecasts generated.

    Example Output:
        {
            "paycheck-captech": {2026-01-05, 2026-01-20, 2026-02-05},
            "paycheck-lmtsd": {2026-01-29, 2026-02-12}
        }

    Args:
        entries: List of beancount entries (typically the full ledger)

    Returns:
        Dict mapping schedule_id -> set of dates with actual transactions.
        Forecast transactions (flag="#") are excluded.
    """
    scheduled_dates = {}

    for entry in entries:
        if isinstance(entry, data.Transaction):
            # Skip forecast transactions
            if entry.flag == "#":
                continue

            # Check if transaction has schedule_id metadata
            schedule_id = entry.meta.get("schedule_id")
            if schedule_id:
                if schedule_id not in scheduled_dates:
                    scheduled_dates[schedule_id] = set()
                scheduled_dates[schedule_id].add(entry.date)

    return scheduled_dates


def generate_schedule_occurrences(
    schedule: "Schedule",
    recurrence_engine: "RecurrenceEngine",
    start_date: date,
    end_date: date,
) -> list[date]:
    """Generate expected occurrence dates for a single schedule.

    Wrapper around RecurrenceEngine.generate() for consistency and future
    extensibility. Currently delegates directly to the engine, but provides
    a stable API if engine behavior changes.

    Used by: The plugin (schedules.py) to generate individual schedule
    occurrences, and by generate_all_schedule_occurrences() for batch
    generation.

    Args:
        schedule: Schedule definition (contains recurrence rules)
        recurrence_engine: RecurrenceEngine instance for date computation
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        List of dates when this schedule is expected to occur, in ascending order
        (empty list if no occurrences in range)
    """
    return recurrence_engine.generate(schedule, start_date, end_date)


def generate_all_schedule_occurrences(
    schedules: list["Schedule"],
    recurrence_engine: "RecurrenceEngine",
    start_date: date,
    end_date: date,
) -> dict[str, list[tuple["Schedule", date]]]:
    """Generate expected occurrences for all schedules, grouped by account.

    This batch operation is optimized for the hook's matching workflow:
    - Transactions are matched based on account
    - Grouping by account allows O(1) candidate lookup instead of O(n)
    - Each schedule only appears for its configured account

    The hook uses this to build a lookup table, then searches the table
    during transaction matching to find candidate schedules.

    Moved from: hook.py::_generate_expected_occurrences()

    Args:
        schedules: List of enabled schedules to process
        recurrence_engine: RecurrenceEngine instance for date computation
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        Dict mapping account (str) -> list of (schedule, expected_date) tuples.
        Example: {
            "Assets:Checking:Ally:Spending": [
                (schedule_paycheck_captech, 2026-02-05),
                (schedule_paycheck_captech, 2026-02-20),
            ],
            "Assets:Checking:Chase": [
                (schedule_chase_payment, 2026-02-15),
            ]
        }
    """
    # Group by account for efficient matching
    occurrences_by_account = defaultdict(list)

    for schedule in schedules:
        expected_dates = generate_schedule_occurrences(
            schedule, recurrence_engine, start_date, end_date
        )

        for expected_date in expected_dates:
            occurrences_by_account[schedule.match.account].append((schedule, expected_date))

    return occurrences_by_account


def filter_occurrences_by_existing_transactions(
    schedule_id: str,
    occurrence_dates: list[date],
    entries: list[data.Directive],
) -> list[date]:
    """Filter out occurrence dates that already have actual transactions.

    This is the key function that prevents duplicate forecasts. When the plugin
    generates forecast transactions for future dates, it should skip any dates
    where an actual transaction has already been imported and matched to this
    schedule.

    Why This Matters:
    - Hook matches imported transactions on 2026-02-05 for paycheck-captech
    - Plugin independently generates forecasts for all dates in date range
    - Without filtering: both would appear, showing duplicate transactions
    - With filtering: plugin skips 2026-02-05, only generating for future dates

    Used by: The plugin (schedules.py) after generating occurrence dates and
    before creating forecast transactions.

    Args:
        schedule_id: The schedule_id to filter for (e.g., "paycheck-captech")
        occurrence_dates: List of occurrence dates generated by recurrence engine
        entries: Existing ledger entries (to check for existing transactions)

    Returns:
        Filtered list of dates, with dates that have actual transactions removed.
        Returns unmodified list if no actual transactions exist.
    """
    covered_dates = get_scheduled_dates_from_entries(entries, schedule_id, include_forecast=False)
    return [d for d in occurrence_dates if d not in covered_dates]


def slugify(text: str) -> str:
    """Convert text to valid schedule ID.

    Converts text to lowercase, removes special characters,
    replaces spaces with hyphens, and strips leading/trailing hyphens.

    Args:
        text: The text to slugify.

    Returns:
        A valid schedule ID string.
    """
    # Lowercase and replace spaces with hyphens
    slug = text.lower().replace(" ", "-")
    # Remove special characters, keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove leading/trailing hyphens and multiple consecutive hyphens
    slug = slug.strip("-")
    return re.sub(r"-+", "-", slug)
