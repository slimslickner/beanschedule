"""Beangulp hook for scheduled transaction matching and enrichment."""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from beancount.core import amount, data

from .loader import get_enabled_schedules, load_schedules_file
from .matcher import TransactionMatcher
from .recurrence import RecurrenceEngine
from .schema import Schedule

logger = logging.getLogger(__name__)


def schedule_hook(
    extracted_entries_list,
    ledger_entries: Optional[List[data.Directive]] = None,
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
        ledger_entries: Existing ledger entries (optional, for duplicate detection)

    Returns:
        Modified entries list with enriched transactions
    """
    logger.info("Running schedule_hook")

    # Step 1: Load schedules
    try:
        schedule_file = load_schedules_file()
    except Exception as e:
        logger.error(f"Failed to load schedules: {e}")
        return extracted_entries_list

    if schedule_file is None:
        logger.info("No schedules loaded, returning entries unchanged")
        return extracted_entries_list

    enabled_schedules = get_enabled_schedules(schedule_file)
    if not enabled_schedules:
        logger.info("No enabled schedules, returning entries unchanged")
        return extracted_entries_list

    # Step 2: Extract date range from all transactions
    date_range = _extract_date_range(extracted_entries_list)
    if date_range is None:
        logger.info("No transactions found, returning entries unchanged")
        return extracted_entries_list

    start_date, end_date = date_range
    logger.info(f"Processing date range: {start_date} to {end_date}")

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

    for item in extracted_entries_list:
        # Beangulp format: (filepath, entries, account, importer_wrapper)
        filepath, entries, account, importer = item

        modified_entries = []

        for entry in entries:
            if isinstance(entry, data.Transaction):
                # Try to match this transaction
                logger.debug(
                    f"Checking transaction: {entry.date} | {entry.payee} | {entry.postings[0].account if entry.postings else 'no postings'} | {entry.postings[0].units if entry.postings else 'no amount'}",
                )
                match_result = _match_transaction(entry, expected_occurrences, matcher)

                if match_result:
                    schedule, expected_date, score = match_result
                    logger.info(
                        f"✓ Matched transaction to schedule '{schedule.id}' (score: {score:.2f})",
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
        logger.info(f"✓ Matched {len(matched_details)} scheduled transaction(s)")
        logger.info("=" * 70)
        for txn_date, payee, schedule_id in matched_details:
            logger.info(f"  • {txn_date} - {payee} ({schedule_id})")
        logger.info("=" * 70)

    # Step 6: Create placeholders for missing transactions
    placeholders = _create_placeholders(
        expected_occurrences,
        matched_occurrences,
        schedule_file.config.placeholder_flag,
    )

    if placeholders:
        # Add placeholders to a synthetic "schedules" file entry
        # Use 4-element format if original list uses it
        if extracted_entries_list and len(extracted_entries_list[0]) == 4:
            modified_entries_list.append(("<schedules>", placeholders, None, None))
        else:
            modified_entries_list.append(("<schedules>", placeholders))

        # Log prominent warning about missing scheduled transactions
        logger.warning("=" * 70)
        logger.warning(
            f"⚠️  MISSING SCHEDULED TRANSACTIONS: {len(placeholders)} expected transaction(s) not found",
        )
        logger.warning("=" * 70)
        for placeholder in placeholders:
            schedule_id = placeholder.meta.get("schedule_id", "unknown")
            expected_date = placeholder.meta.get("schedule_expected_date", "unknown")
            logger.warning(f"  • {expected_date} - {placeholder.payee} ({schedule_id})")
        logger.warning("=" * 70)

    logger.info("schedule_hook completed")
    return modified_entries_list


def _extract_date_range(extracted_entries_list) -> Optional[Tuple[date, date]]:
    """
    Extract min/max date range from all transactions.

    Args:
        extracted_entries_list: List from beangulp (format varies)

    Returns:
        Tuple of (start_date, end_date) with ±7 day buffer, or None if no transactions
    """
    dates = []

    for item in extracted_entries_list:
        # Handle both formats: (filepath, entries, account, importer) or (filepath, entries)
        if len(item) >= 2:
            entries = item[1]
            for entry in entries:
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
    schedules: List[Schedule],
    recurrence_engine: RecurrenceEngine,
    start_date: date,
    end_date: date,
) -> Dict[str, List[Tuple[Schedule, date]]]:
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

        logger.debug(f"Schedule {schedule.id}: {len(expected_dates)} expected occurrences")

    return occurrences_by_account


def _match_transaction(
    transaction: data.Transaction,
    expected_occurrences: Dict[str, List[Tuple[Schedule, date]]],
    matcher: TransactionMatcher,
) -> Optional[Tuple[Schedule, date, float]]:
    """
    Match transaction to best matching schedule.

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

    # Find best match
    return matcher.find_best_match(transaction, candidates)


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
) -> List[data.Posting]:
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
    expected_occurrences: Dict[str, List[Tuple[Schedule, date]]],
    matched_occurrences: Set[Tuple[str, date]],
    placeholder_flag: str,
) -> List[data.Transaction]:
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

    for account, occurrence_list in expected_occurrences.items():
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
