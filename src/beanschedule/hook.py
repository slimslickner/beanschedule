"""Beangulp hook for scheduled transaction matching and enrichment."""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from beancount.core import amount, data

from .loader import get_enabled_schedules, load_schedules_file
from .matcher import TransactionMatcher
from .recurrence import RecurrenceEngine
from .schema import GlobalConfig, Schedule

logger = logging.getLogger(__name__)

# Constants
MIN_BEANGULP_TUPLE_SIZE = 2  # Minimum entries in beangulp tuple


def schedule_hook(
    extracted_entries_list,
    existing_entries: Optional[list[data.Directive]] = None,
):
    """
    Beangulp hook for scheduled transaction matching and enrichment.

    Processing steps:
    1. Load schedules from schedules.yaml
    2. Extract date range from all imported transactions
    3. Generate expected dates for each schedule in range
    4. Match imported transactions to schedules
    5. Enrich matched transactions with schedule metadata
    6. Create placeholders for missing scheduled transactions
    7. Return modified entries list

    Args:
        extracted_entries_list: Entries from importers (beangulp format)
        existing_entries: Existing ledger entries from beangulp

    Returns:
        Modified entries list with enriched transactions
    """
    logger.info("Running schedule_hook")

    ledger_entries = existing_entries
    logger.info("Imported entries: %d file(s)", len(extracted_entries_list))
    logger.info("Existing ledger entries: %d entries", len(ledger_entries or []))
    if ledger_entries:
        logger.debug("Using %d existing ledger entries", len(ledger_entries))

    # Step 1: Load schedules
    try:
        schedule_file = load_schedules_file()
    except Exception as e:
        logger.error("Failed to load schedules: %s", e)
        return extracted_entries_list

    if schedule_file is None:
        logger.info("No schedules loaded, returning entries unchanged")
        return extracted_entries_list

    enabled_schedules = get_enabled_schedules(schedule_file)
    if not enabled_schedules:
        logger.info("No enabled schedules, returning entries unchanged")
        return extracted_entries_list

    # Step 2: Extract date range from all transactions (imported + ledger)
    date_range = _extract_date_range(extracted_entries_list, ledger_entries)
    if date_range is None:
        logger.info("No transactions found in imports or ledger, returning entries unchanged")
        return extracted_entries_list

    # If we have no imported entries but have ledger entries, still process schedules
    # to check for missing transactions
    if not extracted_entries_list and ledger_entries:
        logger.info(
            "No new imports, but checking schedules against %d existing ledger entries",
            len(ledger_entries),
        )

    start_date, end_date = date_range
    logger.info("Processing date range: %s to %s", start_date, end_date)

    # Step 3: Generate expected dates for each schedule
    recurrence_engine = RecurrenceEngine()
    expected_occurrences = _generate_expected_occurrences(
        enabled_schedules,
        recurrence_engine,
        start_date,
        end_date,
    )

    # Step 4 & 5: Match and enrich transactions
    matcher = TransactionMatcher(schedule_file.config)
    modified_entries_list = []
    matched_occurrences = set()
    matched_details = []  # Track matched transactions for summary

    # Build date index for lazy matching (O(n) once vs O(n*m) per lookup)
    date_index = _build_date_index(ledger_entries) if ledger_entries else {}

    # First, match any transactions already in the ledger (to avoid false missing warnings)
    if ledger_entries:
        ledger_matched = _match_ledger_transactions_lazy(
            ledger_entries,
            expected_occurrences,
            enabled_schedules,
        )
        matched_occurrences.update(ledger_matched)
        logger.debug("Matched %d transactions from existing ledger", len(ledger_matched))

    for item in extracted_entries_list:
        # Beangulp format: (filepath, entries, account, importer_wrapper)
        filepath, entries, account, importer = item

        modified_entries = []

        for entry in entries:
            if isinstance(entry, data.Transaction):
                # Try to match this transaction
                account_str = entry.postings[0].account if entry.postings else "no postings"
                units_str = str(entry.postings[0].units) if entry.postings else "no amount"
                logger.debug(
                    "Checking transaction: %s | %s | %s | %s",
                    entry.date,
                    entry.payee,
                    account_str,
                    units_str,
                )
                match_result = _match_transaction(entry, expected_occurrences, matcher)

                if match_result:
                    schedule, expected_date, score = match_result
                    logger.info(
                        "✓ Matched transaction to schedule '%s' (score: %.2f)",
                        schedule.id,
                        score,
                    )
                    # Enrich transaction
                    enriched_txn = _enrich_transaction(entry, schedule, expected_date, score)
                    modified_entries.append(enriched_txn)
                    # Mark occurrence as matched
                    matched_occurrences.add((schedule.id, expected_date))
                    matched_details.append((entry.date, schedule.transaction.payee, schedule.id))
                else:
                    # No match, keep original
                    logger.debug("  No match found")
                    modified_entries.append(entry)
            else:
                # Not a transaction, keep as-is
                modified_entries.append(entry)

        modified_entries_list.append((filepath, modified_entries, account, importer))

    # Log summary of matched transactions
    if matched_details:
        logger.info("=" * 70)
        logger.info("✓ Matched %d scheduled transaction(s)", len(matched_details))
        logger.info("=" * 70)
        for txn_date, payee, schedule_id in matched_details:
            logger.info("  • %s - %s (%s)", txn_date, payee, schedule_id)
        logger.info("=" * 70)

    # Step 6: Create placeholders for missing transactions
    placeholders = _create_placeholders(
        expected_occurrences,
        matched_occurrences,
        schedule_file.config.placeholder_flag,
    )

    if placeholders:
        # Add placeholders to a synthetic "schedules" file entry
        # Always use 4-element format (beangulp standard)
        modified_entries_list.append(("<schedules>", placeholders, None, None))

        # Log prominent warning about missing scheduled transactions
        logger.warning("=" * 70)
        logger.warning(
            "⚠️  MISSING SCHEDULED TRANSACTIONS: %d expected transaction(s) not found",
            len(placeholders),
        )
        logger.warning("=" * 70)
        for placeholder in placeholders:
            schedule_id = placeholder.meta.get("schedule_id", "unknown")
            expected_date = placeholder.meta.get("schedule_expected_date", "unknown")
            logger.warning("  • %s - %s (%s)", expected_date, placeholder.payee, schedule_id)
        logger.warning("=" * 70)

    # Log final summary
    _log_summary(enabled_schedules, matched_occurrences, placeholders, start_date, end_date)

    logger.info("schedule_hook completed")
    return modified_entries_list


def _extract_date_range(
    extracted_entries_list,
    ledger_entries: Optional[list[data.Directive]] = None,
) -> Optional[tuple[date, date]]:
    """
    Extract min/max date range from all transactions (imported + ledger).

    Args:
        extracted_entries_list: List from beangulp (format varies)
        ledger_entries: Existing ledger entries (optional)

    Returns:
        Tuple of (start_date, end_date) with ±7 day buffer, or None if no transactions
    """
    dates = []

    # Extract dates from imported transactions
    for item in extracted_entries_list:
        # Handle both formats: (filepath, entries, account, importer) or (filepath, entries)
        if len(item) >= MIN_BEANGULP_TUPLE_SIZE:
            entries = item[1]
            for entry in entries:
                if isinstance(entry, data.Transaction):
                    dates.append(entry.date)

    # Extract dates from ledger transactions
    if ledger_entries:
        for entry in ledger_entries:
            if isinstance(entry, data.Transaction):
                dates.append(entry.date)

    if not dates:
        return None

    min_date = min(dates)
    max_date = max(dates)

    # Add buffer for edge cases
    buffer = timedelta(days=7)
    return (min_date - buffer, max_date + buffer)


def _generate_expected_occurrences(
    schedules: list[Schedule],
    recurrence_engine: RecurrenceEngine,
    start_date: date,
    end_date: date,
) -> dict[str, list[tuple[Schedule, date]]]:
    """
    Generate expected occurrences for all schedules.

    Args:
        schedules: List of enabled schedules
        recurrence_engine: RecurrenceEngine instance
        start_date: Start of date range
        end_date: End of date range

    Returns:
        Dict mapping account to list of (schedule, expected_date) tuples
    """
    # Group by account for efficient matching
    occurrences_by_account = defaultdict(list)

    for schedule in schedules:
        expected_dates = recurrence_engine.generate(schedule, start_date, end_date)

        for expected_date in expected_dates:
            occurrences_by_account[schedule.match.account].append((schedule, expected_date))

        logger.debug("Schedule %s: %d expected occurrences", schedule.id, len(expected_dates))

    return occurrences_by_account


def _match_transaction(
    transaction: data.Transaction,
    expected_occurrences: dict[str, list[tuple[Schedule, date]]],
    matcher: TransactionMatcher,
) -> Optional[tuple[Schedule, date, float]]:
    """
    Match transaction to best matching schedule.

    Prioritizes pre-existing schedule_id metadata if present, otherwise uses fuzzy matching.

    Args:
        transaction: Transaction to match
        expected_occurrences: Dict of account -> [(schedule, expected_date)]
        matcher: TransactionMatcher instance

    Returns:
        Tuple of (schedule, expected_date, score) or None if no match
    """
    if not transaction.postings:
        return None

    # Get main account from first posting
    main_account = transaction.postings[0].account

    # Get candidates for this account
    candidates = expected_occurrences.get(main_account, [])
    if not candidates:
        return None

    # Check for pre-existing schedule_id metadata
    existing_schedule_id = transaction.meta.get("schedule_id")
    if existing_schedule_id:
        # Try to find matching schedule in candidates
        matching_candidates = [
            (sched, exp_date) for sched, exp_date in candidates if sched.id == existing_schedule_id
        ]

        if matching_candidates:
            # Find the candidate with closest date to transaction date
            # This handles cases where a schedule occurs multiple times
            closest_match = min(
                matching_candidates,
                key=lambda x: abs((x[1] - transaction.date).days),
            )
            schedule, expected_date = closest_match
            logger.info(
                "✓ Using pre-existing schedule_id metadata: '%s'",
                existing_schedule_id,
            )
            # Return with perfect confidence score since it's explicitly set
            return (schedule, expected_date, 1.0)
        # Pre-existing schedule_id not found in candidates for this account
        logger.debug(
            "Pre-existing schedule_id '%s' not found in candidates for account %s",
            existing_schedule_id,
            main_account,
        )

    # Fall back to fuzzy matching
    return matcher.find_best_match(transaction, candidates)


def _build_date_index(
    ledger_entries: Optional[list[data.Directive]],
) -> dict[date, list[data.Transaction]]:
    """
    Build an index mapping dates to transactions for fast lookups.

    Speeds up lazy matching by allowing O(1) lookup instead of scanning all entries.

    Args:
        ledger_entries: Existing ledger entries

    Returns:
        Dict mapping date -> List of transactions on that date
    """
    index = defaultdict(list)

    if not ledger_entries:
        return index

    for entry in ledger_entries:
        if isinstance(entry, data.Transaction):
            index[entry.date].append(entry)

    logger.debug(
        "Built date index with %d unique dates from %d entries",
        len(index),
        len(ledger_entries),
    )
    return index


def _match_ledger_transactions_lazy(
    ledger_entries: list[data.Directive],
    expected_occurrences: dict[str, list[tuple[Schedule, date]]],
    enabled_schedules: list[Schedule],
) -> set[tuple[str, date]]:
    """
    Match ledger transactions using lazy evaluation with date windows.

    Only checks transactions within each schedule's date_window_days instead of
    scanning all ledger entries. Uses explicit schedule_id metadata when available.

    Args:
        ledger_entries: Existing ledger entries
        expected_occurrences: Dict of account -> [(schedule, expected_date)]
        enabled_schedules: List of enabled schedules for lookup

    Returns:
        Set of (schedule_id, expected_date) tuples for transactions already in ledger
    """
    matched = set()
    schedule_id_map = {sched.id: sched for sched in enabled_schedules}

    # Fast path: transactions with explicit schedule_id metadata
    for entry in ledger_entries:
        if not isinstance(entry, data.Transaction):
            continue

        schedule_id = entry.meta.get("schedule_id")
        if not schedule_id:
            continue

        schedule = schedule_id_map.get(schedule_id)
        if not schedule:
            logger.debug("Ledger transaction has unknown schedule_id: %s", schedule_id)
            continue

        if not entry.postings:
            continue

        main_account = entry.postings[0].account
        if main_account != schedule.match.account:
            logger.debug(
                "Ledger transaction account %s doesn't match schedule account %s",
                main_account,
                schedule.match.account,
            )
            continue

        # Find matching expected occurrence within date window
        date_window = schedule.match.date_window_days or 0

        for sched, expected_date in expected_occurrences.get(main_account, []):
            if sched.id == schedule_id:
                days_diff = abs((entry.date - expected_date).days)
                if days_diff <= date_window:
                    matched.add((schedule_id, expected_date))
                    logger.debug(
                        "Matched ledger transaction %s to schedule %s (expected %s)",
                        entry.date,
                        schedule_id,
                        expected_date,
                    )
                    break

    # Note: We do NOT do fuzzy matching on ledger transactions without schedule_id
    # Only transactions with explicit schedule_id metadata are considered "confirmed" matches
    # This prevents false positives from accidentally matching unrelated transactions
    # Fuzzy matching is reserved for newly imported transactions that we're enriching

    return matched


def _match_ledger_transactions(
    ledger_entries: list[data.Directive],
    expected_occurrences: dict[str, list[tuple[Schedule, date]]],
    enabled_schedules: list[Schedule],
) -> set[tuple[str, date]]:
    """
    Match transactions already in the ledger to expected schedule occurrences.

    Uses schedule_id metadata if present, otherwise doesn't match (those transactions
    were already imported and shouldn't be re-matched).

    Args:
        ledger_entries: Existing ledger entries
        expected_occurrences: Dict of account -> [(schedule, expected_date)]
        enabled_schedules: List of enabled schedules for lookup

    Returns:
        Set of (schedule_id, expected_date) tuples for transactions already in ledger
    """
    matched = set()
    schedule_id_map = {sched.id: sched for sched in enabled_schedules}

    for entry in ledger_entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Only match if transaction has explicit schedule_id metadata
        schedule_id = entry.meta.get("schedule_id")
        if not schedule_id:
            continue

        # Check if this schedule_id exists
        schedule = schedule_id_map.get(schedule_id)
        if not schedule:
            logger.debug("Ledger transaction has unknown schedule_id: %s", schedule_id)
            continue

        # Check if transaction's account matches the schedule's account
        if not entry.postings:
            continue

        main_account = entry.postings[0].account
        if main_account != schedule.match.account:
            logger.debug(
                "Ledger transaction account %s doesn't match schedule account %s",
                main_account,
                schedule.match.account,
            )
            continue

        # Find expected occurrence for this schedule_id and date
        # Allow some date flexibility (within the date window) for ledger transactions
        date_window = schedule.match.date_window_days or 0
        found = False

        for sched, expected_date in expected_occurrences.get(main_account, []):
            if sched.id == schedule_id:
                # Check if dates match (with window tolerance)
                days_diff = abs((entry.date - expected_date).days)
                if days_diff <= date_window:
                    matched.add((schedule_id, expected_date))
                    logger.debug(
                        "Matched ledger transaction %s to schedule %s (expected %s)",
                        entry.date,
                        schedule_id,
                        expected_date,
                    )
                    found = True
                    break

        if not found:
            logger.debug(
                "Ledger transaction %s with schedule_id %s doesn't match any expected occurrence",
                entry.date,
                schedule_id,
            )

    return matched


def _enrich_transaction(
    transaction: data.Transaction,
    schedule: Schedule,
    expected_date: date,
    score: float,
) -> data.Transaction:
    """
    Enrich transaction with schedule metadata, tags, and postings.

    Args:
        transaction: Original transaction
        schedule: Matching schedule
        expected_date: Expected occurrence date
        score: Match confidence score

    Returns:
        Modified transaction with schedule enrichment
    """
    # Copy existing metadata and add schedule info
    new_meta = transaction.meta.copy()
    new_meta["schedule_id"] = schedule.transaction.metadata["schedule_id"]
    new_meta["schedule_matched_date"] = expected_date.isoformat()
    new_meta["schedule_confidence"] = f"{score:.2f}"

    # Add any custom metadata from schedule
    for key, value in schedule.transaction.metadata.items():
        if key != "schedule_id":  # Already added
            new_meta[key] = value

    # Merge tags
    new_tags = transaction.tags.copy()
    if schedule.transaction.tags:
        new_tags.update(schedule.transaction.tags)

    # Override payee/narration if specified
    new_payee = schedule.transaction.payee or transaction.payee
    new_narration = schedule.transaction.narration or transaction.narration

    # Handle postings
    if schedule.transaction.postings:
        new_postings = _apply_schedule_postings(transaction, schedule)
    else:
        new_postings = transaction.postings

    return transaction._replace(
        meta=new_meta,
        payee=new_payee,
        narration=new_narration,
        tags=new_tags,
        postings=new_postings,
    )


def _apply_schedule_postings(
    transaction: data.Transaction,
    schedule: Schedule,
) -> list[data.Posting]:
    """
    Apply schedule posting template to transaction.

    If posting has amount=null, use imported amount.
    Otherwise use schedule amount.

    Args:
        transaction: Original transaction
        schedule: Schedule with posting template

    Returns:
        List of postings
    """
    if not schedule.transaction.postings:
        return transaction.postings

    # Get original amount from first posting (for null amounts)
    original_amount = None
    if transaction.postings:
        original_amount = transaction.postings[0].units

    new_postings = []
    for posting_template in schedule.transaction.postings:
        if posting_template.amount is None:
            # Use imported amount (or None for second+ postings)
            if posting_template.account == transaction.postings[0].account:
                posting_amount = original_amount
            else:
                posting_amount = None
        else:
            # Use schedule amount
            currency = original_amount.currency if original_amount else "USD"
            posting_amount = amount.Amount(Decimal(str(posting_template.amount)), currency)

        # Build posting metadata (for comments)
        posting_meta = None
        if posting_template.narration:
            posting_meta = {"narration": posting_template.narration}

        posting = data.Posting(
            account=posting_template.account,
            units=posting_amount,
            cost=None,
            price=None,
            flag=None,
            meta=posting_meta,
        )
        new_postings.append(posting)

    return new_postings


def _create_placeholders(
    expected_occurrences: dict[str, list[tuple[Schedule, date]]],
    matched_occurrences: set[tuple[str, date]],
    placeholder_flag: str,
) -> list[data.Transaction]:
    """
    Create placeholder transactions for missing scheduled transactions.

    Args:
        expected_occurrences: All expected occurrences
        matched_occurrences: Set of (schedule_id, expected_date) that were matched
        placeholder_flag: Flag character for placeholders

    Returns:
        List of placeholder transactions
    """
    placeholders = []

    for _account, occurrence_list in expected_occurrences.items():
        for schedule, expected_date in occurrence_list:
            # Skip if already matched
            if (schedule.id, expected_date) in matched_occurrences:
                continue

            # Skip if placeholder creation disabled
            if not schedule.missing_transaction.create_placeholder:
                continue

            # Create placeholder transaction
            placeholder = _create_placeholder_transaction(schedule, expected_date, placeholder_flag)
            placeholders.append(placeholder)

    return placeholders


def _log_summary(
    schedules: list[Schedule],
    matched_occurrences: set[tuple[str, date]],
    missing_placeholders: list[data.Transaction],
    start_date: date,
    end_date: date,
) -> None:
    """
    Log a summary of schedule processing results.

    Args:
        schedules: All enabled schedules
        matched_occurrences: Set of (schedule_id, expected_date) that were matched
        missing_placeholders: List of placeholder transactions created for missing
        start_date: Start of processing date range
        end_date: End of processing date range
    """
    logger.info("=" * 70)
    logger.info("SCHEDULE PROCESSING SUMMARY")
    logger.info("=" * 70)
    logger.info("Date range: %s to %s", start_date, end_date)
    logger.info("")

    # Count expected vs matched by schedule
    total_expected = 0
    total_matched = 0
    missing_by_schedule = defaultdict(int)

    for schedule in schedules:
        # Count expected occurrences
        expected_count = sum(
            1 for schedule_id, _ in matched_occurrences if schedule_id == schedule.id
        )
        # Add missing count
        missing_count = sum(
            1
            for placeholder in missing_placeholders
            if placeholder.meta.get("schedule_id") == schedule.id
        )
        total_expected_for_schedule = expected_count + missing_count

        total_expected += total_expected_for_schedule
        total_matched += expected_count

        if missing_count > 0:
            missing_by_schedule[schedule.id] = missing_count

        status = "✓" if missing_count == 0 else "⚠"
        logger.info(
            "%s %-40s %2d/%2d matched",
            status,
            schedule.id,
            expected_count,
            total_expected_for_schedule,
        )

    logger.info("=" * 70)
    logger.info("TOTAL: %d/%d scheduled transaction(s) matched", total_matched, total_expected)

    if missing_by_schedule:
        logger.warning("Missing in %d schedule(s):", len(missing_by_schedule))
        for schedule_id, count in sorted(missing_by_schedule.items()):
            logger.warning("  • %s: %d missing", schedule_id, count)

    logger.info("=" * 70)


def _create_placeholder_transaction(
    schedule: Schedule,
    expected_date: date,
    placeholder_flag: str,
) -> data.Transaction:
    """
    Create a placeholder transaction for missing scheduled transaction.

    Args:
        schedule: Schedule definition
        expected_date: Expected occurrence date
        placeholder_flag: Flag character

    Returns:
        Placeholder transaction
    """
    # Build metadata
    meta = data.new_metadata("<schedules>", 0)
    meta["schedule_id"] = schedule.transaction.metadata["schedule_id"]
    meta["schedule_placeholder"] = "true"
    meta["schedule_expected_date"] = expected_date.isoformat()

    # Add custom metadata
    for key, value in schedule.transaction.metadata.items():
        if key not in ["schedule_id"]:
            meta[key] = value

    # Build narration with prefix
    prefix = schedule.missing_transaction.narration_prefix
    base_narration = schedule.transaction.narration or ""
    narration = f"{prefix} {base_narration}".strip()

    # Build postings
    if schedule.transaction.postings:
        postings = []
        for posting_template in schedule.transaction.postings:
            if posting_template.amount is not None:
                posting_amount = amount.Amount(Decimal(str(posting_template.amount)), "USD")
            else:
                posting_amount = None

            # Build posting metadata (for comments)
            posting_meta = None
            if posting_template.narration:
                posting_meta = {"narration": posting_template.narration}

            posting = data.Posting(
                account=posting_template.account,
                units=posting_amount,
                cost=None,
                price=None,
                flag=None,
                meta=posting_meta,
            )
            postings.append(posting)
    else:
        # Create single posting to main account
        postings = [
            data.Posting(
                account=schedule.match.account,
                units=None,
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
        ]

    return data.Transaction(
        meta=meta,
        date=expected_date,
        flag=placeholder_flag,
        payee=schedule.transaction.payee or "",
        narration=narration,
        tags=set(schedule.transaction.tags or []),
        links=set(),
        postings=postings,
    )
