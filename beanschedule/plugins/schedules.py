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

    # Check if amortization is configured
    amortization_split = None
    if schedule.amortization:
        from beanschedule.amortization import AmortizationSchedule

        # Create amortization schedule
        amort_schedule = AmortizationSchedule(
            principal=schedule.amortization.principal,
            annual_rate=schedule.amortization.annual_rate,
            term_months=schedule.amortization.term_months,
            start_date=schedule.amortization.start_date,
            extra_principal=schedule.amortization.extra_principal,
        )

        # Get payment number for this occurrence
        payment_number = amort_schedule.get_payment_number_for_date(occurrence_date)

        if payment_number is not None:
            # Calculate principal/interest split
            amortization_split = amort_schedule.get_payment_split(payment_number)

            # Add amortization metadata
            meta["amortization_payment_number"] = payment_number
            meta["amortization_balance_after"] = str(amortization_split.remaining_balance)
            meta["amortization_principal"] = str(amortization_split.principal)
            meta["amortization_interest"] = str(amortization_split.interest)

    # Build postings - calculate balancing amounts for forecast transactions
    postings = []

    # First pass: collect amounts and validate posting structure
    null_amount_indices = []
    specified_amounts = []
    amortized_amounts = {}  # Track which postings will use amortization

    for idx, posting_template in enumerate(schedule.transaction.postings):
        if posting_template.amount is not None:
            specified_amounts.append(Decimal(str(posting_template.amount)))
        else:
            null_amount_indices.append(idx)
            # Check if this null posting will be filled by amortization
            if amortization_split:
                # Use explicit role - required for amortization
                role = posting_template.role
                if role == "interest":
                    amortized_amounts[idx] = amortization_split.interest
                elif role == "principal":
                    amortized_amounts[idx] = amortization_split.principal
                elif role is None:
                    # No role specified - this posting won't be filled by amortization
                    pass

    # With amortization: allow multiple null amounts (they'll be calculated)
    # Without amortization: only allow one null amount (balancing posting)
    if not amortization_split:
        if len(null_amount_indices) > 1:
            raise ValueError(
                f"Schedule {schedule.id}: Multiple postings have null amounts. "
                f"At most one posting can have a null amount (the balancing posting)."
            )

    # Validation: if all amounts are null, that's an error
    if len(null_amount_indices) == len(schedule.transaction.postings):
        if amortization_split:
            raise ValueError(
                f"Schedule {schedule.id}: All postings have null amounts. "
                f"For amortization schedules, postings must have explicit 'role' fields "
                f"(payment, interest, principal, escrow). See POSTING_ROLES.md for details."
            )
        else:
            raise ValueError(
                f"Schedule {schedule.id}: All postings have null amounts. "
                f"At least one posting must specify an amount."
            )

    # Calculate amounts for all non-payment postings first
    total_non_payment = sum(specified_amounts)  # Fixed amounts (e.g., escrow)
    total_non_payment += sum(amortized_amounts.values())  # Amortized amounts (principal, interest)

    # Second pass: create postings
    for idx, posting_template in enumerate(schedule.transaction.postings):
        # Determine amount - check if this is an amortization posting
        posting_amount_value = None

        # Priority 1: Use explicit amount from YAML
        if posting_template.amount is not None:
            posting_amount_value = Decimal(str(posting_template.amount))

        # Priority 2: Use amortized amount
        elif idx in amortized_amounts:
            posting_amount_value = amortized_amounts[idx]

        # Priority 3: Calculate balancing amount
        elif posting_template.amount is None:
            role = posting_template.role

            # Check if this is a payment account (for amortization or regular balancing)
            if role == "payment":
                # Payment account balances all other postings
                if amortization_split or amortized_amounts:
                    # With amortization: balance principal + interest + fixed amounts
                    posting_amount_value = -total_non_payment
                else:
                    # Without amortization: standard balancing
                    posting_amount_value = -sum(specified_amounts)
            else:
                # Non-payment account with null - must be balancing posting
                balancing_posting_idx = null_amount_indices[0] if null_amount_indices else None
                if idx == balancing_posting_idx and not amortization_split:
                    posting_amount_value = -sum(specified_amounts)

        # Validation: posting_amount_value should never be None at this point
        if posting_amount_value is None:
            # Provide helpful error message
            if amortization_split:
                raise ValueError(
                    f"Schedule {schedule.id}: Could not determine amount for posting "
                    f"to account '{posting_template.account}' (index {idx}). "
                    f"For amortization schedules, postings with 'amount: null' must have an explicit 'role' field. "
                    f"Valid roles: 'payment', 'interest', 'principal', 'escrow'. "
                    f"See POSTING_ROLES.md for details."
                )
            else:
                raise ValueError(
                    f"Schedule {schedule.id}: Could not determine amount for posting "
                    f"to account '{posting_template.account}' (index {idx})"
                )

        posting_amount = amount.Amount(
            posting_amount_value,
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
