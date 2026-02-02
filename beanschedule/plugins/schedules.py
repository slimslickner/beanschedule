"""Beanschedule plugin for Beancount - generates forecast transactions from YAML schedules.

This plugin reads schedule definitions from schedules.yaml and generates
forecast transactions for future occurrences.

Usage in ledger:
    plugin "beanschedule.plugins.schedules"

    ; Or specify custom path:
    plugin "beanschedule.plugins.schedules" "path/to/schedules.yaml"

The plugin will:
1. Auto-discover schedules.yaml (or use provided path)
2. Load schedule definitions
3. Generate forecast transactions for enabled schedules
4. Return them as # (forecast) flag transactions

Schedules are defined in YAML format. Example:

    version: "1.0"
    schedules:
      - id: rent-monthly
        enabled: true
        match:
          account: Assets:Checking
          payee_pattern: ".*LANDLORD.*"
        recurrence:
          frequency: MONTHLY
          start_date: 2024-01-01
          day_of_month: 1
        transaction:
          payee: "Rent Payment"
          narration: "Monthly rent"
          metadata:
            schedule_id: rent-monthly
          postings:
            - account: Expenses:Housing:Rent
              amount: 1500.00
            - account: Assets:Checking

For more information, see: https://github.com/yourusername/beanschedule
"""

__copyright__ = "Copyright (C) 2026 beanschedule"
__license__ = "GNU GPLv2"

import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from beancount.core import amount, data

logger = logging.getLogger(__name__)

__plugins__ = ("schedules",)


def schedules(entries, options_map, config_file=None):
    """Generate forecast transactions from YAML schedule definitions.

    Args:
        entries: Existing beancount entries
        options_map: Beancount options
        config_file: Optional path to schedules.yaml (auto-discovers if not provided)

    Returns:
        Tuple of (entries + forecast_entries, errors)

    Example:
        ; Auto-discover schedules.yaml
        plugin "beanschedule.plugins.schedules"

        ; Custom path
        plugin "beanschedule.plugins.schedules" "config/schedules.yaml"
    """
    from beanschedule.loader import (
        find_schedules_location,
        load_schedules_file,
        load_schedules_from_directory,
    )
    from beanschedule.recurrence import RecurrenceEngine

    errors = []

    # 1. Load YAML schedules
    try:
        if config_file:
            # Use provided path
            schedule_path = Path(config_file)
            if not schedule_path.is_absolute():
                # Make relative to ledger file location
                ledger_file = options_map.get("filename")
                if ledger_file:
                    ledger_dir = Path(ledger_file).parent
                    schedule_path = ledger_dir / schedule_path

            if not schedule_path.exists():
                error_msg = f"Schedules file not found: {schedule_path}"
                logger.error(error_msg)
                errors.append(error_msg)
                return entries, errors

            schedule_file = load_schedules_file(schedule_path)
        else:
            # Auto-discover
            schedule_location = find_schedules_location()
            if schedule_location:
                location_type, schedule_path = schedule_location
                if location_type == "dir":
                    schedule_file = load_schedules_from_directory(schedule_path)
                else:  # "file"
                    schedule_file = load_schedules_file(schedule_path)
            else:
                logger.info("No schedules.yaml found, skipping forecast generation")
                return entries, []

        if not schedule_file:
            logger.warning("Failed to load schedules, skipping forecast generation")
            return entries, []

    except Exception as e:
        error_msg = f"Failed to load schedules: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return entries, errors

    # 2. Determine forecast horizon
    # Default: Today + 1 year
    # Can be configured via plugin options in future
    today = date.today()
    forecast_start = today
    forecast_end = today + timedelta(days=365)

    logger.info(
        f"Generating forecasts from {forecast_start} to {forecast_end} "
        f"({len(schedule_file.schedules)} schedule(s))"
    )

    # 3. Generate forecast transactions
    forecast_entries = []
    engine = RecurrenceEngine()

    for schedule in schedule_file.schedules:
        if not schedule.enabled:
            logger.debug(f"Skipping disabled schedule: {schedule.id}")
            continue

        try:
            # Generate occurrence dates
            occurrences = engine.generate(schedule, forecast_start, forecast_end)

            # Create forecast transaction for each occurrence
            for occurrence_date in occurrences:
                forecast_txn = _create_forecast_transaction(
                    schedule, occurrence_date, schedule_file.config
                )
                forecast_entries.append(forecast_txn)

            logger.debug(f"Generated {len(occurrences)} forecast(s) for {schedule.id}")

        except Exception as e:
            error_msg = f"Failed to generate forecasts for {schedule.id}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    logger.info(f"Generated {len(forecast_entries)} forecast transaction(s)")

    # 4. Sort and return
    forecast_entries.sort(key=data.entry_sortkey)

    return entries + forecast_entries, errors


def _create_forecast_transaction(schedule, occurrence_date, global_config):
    """Create a forecast transaction from a schedule.

    Args:
        schedule: Schedule object from schema
        occurrence_date: Date for this forecast occurrence
        global_config: GlobalConfig with defaults

    Returns:
        beancount.core.data.Transaction with forecast flag (#)
    """
    # Compute display filename for metadata
    display_filename = "<schedules.yaml>"  # Default fallback
    if schedule.source_file:
        # Try to make path relative to CWD or base directory from env var
        base_dir = os.getenv("BEANSCHEDULE_DISPLAY_BASE")
        if base_dir:
            try:
                display_filename = str(schedule.source_file.relative_to(Path(base_dir)))
            except ValueError:
                # source_file is not relative to base_dir, use relative to CWD
                try:
                    display_filename = str(schedule.source_file.relative_to(Path.cwd()))
                except ValueError:
                    # Can't make relative, use absolute path
                    display_filename = str(schedule.source_file)
        else:
            # No base dir specified, try CWD
            try:
                display_filename = str(schedule.source_file.relative_to(Path.cwd()))
            except ValueError:
                # Can't make relative to CWD, use absolute path
                display_filename = str(schedule.source_file)

    # Build metadata
    meta = {
        "filename": display_filename,
        "lineno": 0,
        "schedule_id": schedule.id,  # For tracking, not matching
    }

    # Add schedule metadata if present
    if schedule.transaction.metadata:
        for key, value in schedule.transaction.metadata.items():
            # Don't duplicate schedule_id
            if key != "schedule_id":
                meta[key] = value

    # Build postings - calculate balancing amounts for forecast transactions
    postings = []

    # First pass: collect amounts and validate posting structure
    null_amount_indices = []
    specified_amounts = []

    for idx, posting_template in enumerate(schedule.transaction.postings):
        if posting_template.amount is not None:
            specified_amounts.append(Decimal(str(posting_template.amount)))
        else:
            null_amount_indices.append(idx)

    # Validation: at most one posting can have null amount
    if len(null_amount_indices) > 1:
        raise ValueError(
            f"Schedule {schedule.id}: Multiple postings have null amounts. "
            f"At most one posting can have a null amount (the balancing posting)."
        )

    # Validation: if all amounts are null, that's an error
    if len(null_amount_indices) == len(schedule.transaction.postings):
        raise ValueError(
            f"Schedule {schedule.id}: All postings have null amounts. "
            f"At least one posting must specify an amount."
        )

    # Calculate balancing amount if there's exactly one null posting
    balancing_posting_idx = null_amount_indices[0] if null_amount_indices else None
    balancing_amount = None
    if balancing_posting_idx is not None:
        # Sum all specified amounts and negate for balance
        total = sum(specified_amounts)
        balancing_amount = -total

    # Second pass: create postings
    for idx, posting_template in enumerate(schedule.transaction.postings):
        # Determine amount
        if idx == balancing_posting_idx:
            # This is the balancing posting
            posting_amount = amount.Amount(
                balancing_amount,
                global_config.default_currency,
            )
        else:
            # This posting must have an explicit amount (validated above)
            posting_amount = amount.Amount(
                Decimal(str(posting_template.amount)),
                global_config.default_currency,
            )

        # Build posting metadata if any
        posting_meta = {}
        if posting_template.narration:
            posting_meta["narration"] = posting_template.narration

        posting = data.Posting(
            account=posting_template.account,
            units=posting_amount,
            cost=None,
            price=None,
            flag=None,
            meta=posting_meta if posting_meta else None,
        )
        postings.append(posting)

    # Create transaction with # flag (forecast)
    txn = data.Transaction(
        meta=meta,
        date=occurrence_date,
        flag="#",  # Forecast flag
        payee=schedule.transaction.payee,
        narration=schedule.transaction.narration,
        tags=frozenset(schedule.transaction.tags or []),
        links=frozenset(schedule.transaction.links or []),
        postings=postings,
    )

    return txn
