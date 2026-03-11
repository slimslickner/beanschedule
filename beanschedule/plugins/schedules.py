"""Beanschedule plugin for Beancount - generates forecast transactions from YAML schedules.

This plugin reads schedule definitions from a schedules/ directory and generates
forecast transactions for future occurrences.

Usage in ledger:
    plugin "beanschedule.plugins.schedules"

    ; Or specify custom path:
    plugin "beanschedule.plugins.schedules" "path/to/schedules"

The plugin will:
1. Auto-discover schedules/ directory (or use provided path)
2. Load schedule definitions
3. Generate forecast transactions for enabled schedules
4. Return them as # (forecast) flag transactions

Schedules are defined in individual YAML files within the schedules/ directory. Example:

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
from dateutil.relativedelta import relativedelta

from beanschedule.constants import DEFAULT_CURRENCY

logger = logging.getLogger(__name__)

__plugins__ = ("schedules",)


def schedules(entries, options_map, config=None):
    """Generate forecast transactions from YAML schedule definitions.

    This Beancount plugin generates forecast (#) transactions for scheduled events
    (paychecks, loan payments, etc.) that haven't occurred yet. Unlike the hook
    which runs during import and enriches actual transactions, this plugin runs
    when reading the ledger and creates speculative future transactions.

    Architecture & Design:
    ════════════════════
    The plugin operates independently from the hook but coordinates with it:

    1. FORECAST GENERATION
       - For each enabled schedule, generates expected occurrence dates (using
         shared generate_schedule_occurrences() utility)
       - Restricts to future dates based on forecast_months config
       - Creates forecast transactions (flag="#") for each date

    2. DUPLICATE AVOIDANCE (Key Fix)
       - Filters out dates that already have actual transactions with matching
         schedule_id using filter_occurrences_by_existing_transactions()
       - Why: Hook may have matched a paycheck today; we don't want to forecast
         for today if it already has an actual transaction

    3. AMORTIZATION SUPPORT
       - For loan schedules, computes principal/interest splits
       - Supports both static (balance_from_ledger=False) and stateful
         (balance_from_ledger=True) amortization modes

    Hook & Plugin Interaction:
    When you import on 2026-02-05 with a paycheck received today:
      - Hook: Matches the 2026-02-05 paycheck, adds schedule_id metadata
      - Plugin: Generates forecasts, but filters out 2026-02-05, generates 2026-02-20 (next occurrence)
      - Result: No duplicate forecasts, only actual transaction appears on 2026-02-05

    Processing steps:
    1. Load YAML schedules (auto-discover or use provided path)
    2. Determine forecast window based on configuration
    3. Build index of existing scheduled transactions (shared utility)
    4. For each enabled schedule:
       a. Generate expected occurrence dates using recurrence engine
       b. Handle special cases (amortization, payment day of month overrides)
       c. Filter dates that already have actual transactions
       d. Create forecast transaction for each remaining date
    5. Return combined entries (original + forecast)

    Args:
        entries: Existing beancount entries (the full ledger being read)
        options_map: Beancount options (includes filename for path resolution)
        config: Can be:
            - A string: path to schedules/ directory (auto-discovers if not provided)
            - A dict: forecast configuration with keys:
                - forecast_months: months to forecast ahead (overrides YAML config)
                - min_forecast_date: forecast start date (overrides YAML config)
                - include_past_dates: include past dates in placeholders (overrides YAML config)
            - None: auto-discover schedules/ directory

    Returns:
        Tuple of (entries + forecast_entries, errors)
        - Entries include both original entries and new forecast transactions
        - Errors is a list of error strings (empty if successful)

    Example:
        ; Auto-discover schedules/ in ledger directory
        plugin "beanschedule.plugins.schedules"

        ; Custom path relative to ledger file
        plugin "beanschedule.plugins.schedules" "schedules"
    """
    from beanschedule.loader import (
        find_schedules_location,
        load_schedules_from_directory,
        load_schedules_from_path,
    )
    from beanschedule.recurrence import RecurrenceEngine
    from beanschedule.utils import (
        filter_occurrences_by_existing_transactions,
        generate_schedule_occurrences,
    )

    errors = []

    # 1. Load YAML schedules
    schedule_file = None
    forecast_config = None
    config_file_path = None
    shadow_upcoming_account: str | None = None
    shadow_overdue_account: str | None = None
    forecast_flag: str = "#"

    try:
        # Separate file path from forecast config
        if isinstance(config, dict):
            # config is forecast configuration
            forecast_config = config
        elif isinstance(config, str):
            # config could be a file path or a dict string from Beancount
            # Try to parse as Python dict/JSON first
            import ast
            import json

            config_str = config.strip()
            parsed_dict = None

            # Try JSON first (with double quotes)
            try:
                parsed_dict = json.loads(config_str)
            except (json.JSONDecodeError, ValueError):
                pass

            # Try Python literal (with single quotes)
            if parsed_dict is None:
                try:
                    parsed_dict = ast.literal_eval(config_str)
                except (ValueError, SyntaxError):
                    pass

            if isinstance(parsed_dict, dict):
                # Successfully parsed as dict config
                forecast_config = parsed_dict
            else:
                # Treat as file path
                config_file_path = config
        # else: None means auto-discover

        if config_file_path:
            # Use provided path
            schedule_path = Path(config_file_path)
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

            schedule_file = load_schedules_from_path(schedule_path)
        else:
            # Auto-discover
            schedule_path = find_schedules_location()
            if schedule_path:
                schedule_file = load_schedules_from_directory(schedule_path)
            else:
                logger.info(
                    "No schedules directory found, skipping forecast generation"
                )
                return entries, []

        if not schedule_file:
            logger.warning("Failed to load schedules, skipping forecast generation")
            return entries, []

        # Override config with plugin parameters if provided
        if forecast_config:
            if "forecast_months" in forecast_config:
                schedule_file.config.forecast_months = forecast_config[
                    "forecast_months"
                ]
            if "min_forecast_date" in forecast_config:
                min_date_str = forecast_config["min_forecast_date"]
                if isinstance(min_date_str, str):
                    schedule_file.config.min_forecast_date = date.fromisoformat(
                        min_date_str
                    )
                else:
                    schedule_file.config.min_forecast_date = min_date_str
            if "include_past_dates" in forecast_config:
                schedule_file.config.include_past_dates = forecast_config[
                    "include_past_dates"
                ]
            if "shadow_upcoming_account" in forecast_config:
                shadow_upcoming_account = forecast_config["shadow_upcoming_account"]
            if "shadow_overdue_account" in forecast_config:
                shadow_overdue_account = forecast_config["shadow_overdue_account"]
            if "forecast_flag" in forecast_config:
                forecast_flag = forecast_config["forecast_flag"]

    except Exception as e:
        error_msg = f"Failed to load schedules: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return entries, errors

    # Resolve effective default currency:
    # explicit beanschedule.yaml config > ledger operating_currency option > USD
    if schedule_file.config.default_currency is not None:
        effective_currency = schedule_file.config.default_currency
    else:
        ledger_currencies = options_map.get("operating_currency", [])
        effective_currency = (
            ledger_currencies[0] if ledger_currencies else DEFAULT_CURRENCY
        )
        if ledger_currencies:
            logger.debug(
                "Using ledger operating_currency as default: %s", effective_currency
            )
    schedule_file.config.default_currency = effective_currency

    # 2. Determine forecast horizon
    # Determine forecast window based on configuration
    #
    # By default we start from TOMORROW to avoid duplicating actual transactions
    # imported today. When shadow_overdue_account is configured, each schedule
    # uses its own recurrence.start_date as the generation start so all past-due
    # occurrences are covered regardless of age. Dates that already have an actual
    # matched transaction are always filtered out by filter_occurrences_by_existing_transactions.
    today = date.today()
    forecast_start = today + timedelta(days=1)  # Start from tomorrow by default

    # Apply min_forecast_date override if configured
    if schedule_file.config.min_forecast_date:
        forecast_start = min(forecast_start, schedule_file.config.min_forecast_date)
        logger.info(
            "Using configured min_forecast_date: %s",
            schedule_file.config.min_forecast_date,
        )

    # Calculate forecast_end using forecast_months
    forecast_months = (
        schedule_file.config.forecast_months or 3
    )  # Fallback to 3 if not set
    forecast_end = today + relativedelta(months=forecast_months)
    logger.info(
        "Using forecast_months=%d to extend forecast window to: %s",
        forecast_months,
        forecast_end,
    )

    logger.info(
        "Generating forecasts to %s (%d schedule(s))%s",
        forecast_end,
        len(schedule_file.schedules),
        " [overdue enabled: per-schedule start]"
        if shadow_overdue_account
        else f" [upcoming from {forecast_start}]",
    )

    # 3. Generate forecast transactions
    forecast_entries = []
    engine = RecurrenceEngine()

    # ── stateful-amortization setup (single pass through entries) ─────────
    stateful_accounts: set[str] = set()
    for schedule in schedule_file.schedules:
        if (
            schedule.enabled
            and schedule.amortization
            and schedule.amortization.balance_from_ledger
        ):
            principal_account = _get_principal_account(schedule)
            if principal_account:
                stateful_accounts.add(principal_account)

    from beanschedule.amortization import build_liability_balance_index

    liability_balances = (
        build_liability_balance_index(entries, stateful_accounts)
        if stateful_accounts
        else {}
    )

    # ── per-schedule forecast generation ──────────────────────────────────
    for schedule in schedule_file.schedules:
        if not schedule.enabled:
            logger.debug("Skipping disabled schedule: %s", schedule.id)
            continue

        try:
            # When overdue is enabled, generate from the schedule's own start_date so
            # every past-due occurrence is included. Otherwise start from tomorrow.
            gen_start = (
                schedule.recurrence.start_date
                if shadow_overdue_account
                else forecast_start
            )

            # Generate occurrence dates within the forecast window
            occurrences = generate_schedule_occurrences(
                schedule, engine, gen_start, forecast_end
            )

            # Determine forecast dates: use payment_day_of_month if set (for amortization)
            forecast_dates = occurrences
            amort_occurrences = None
            if schedule.amortization and schedule.amortization.payment_day_of_month:
                # Generate amortization dates based on payment day of month
                amort_occurrences = []
                current = gen_start
                try:
                    if current.day <= schedule.amortization.payment_day_of_month:
                        current = current.replace(
                            day=schedule.amortization.payment_day_of_month
                        )
                    else:
                        current = (current + relativedelta(months=1)).replace(
                            day=schedule.amortization.payment_day_of_month
                        )
                except ValueError:
                    # Day doesn't exist in this month
                    import calendar

                    last_day = calendar.monthrange(current.year, current.month)[1]
                    current = current.replace(day=last_day)

                while current <= forecast_end:
                    if current >= gen_start:
                        amort_occurrences.append(current)
                    try:
                        current = (current + relativedelta(months=1)).replace(
                            day=schedule.amortization.payment_day_of_month
                        )
                    except ValueError:
                        import calendar

                        last_day = calendar.monthrange(current.year, current.month)[1]
                        current = (current + relativedelta(months=1)).replace(
                            day=last_day
                        )

                logger.debug(
                    "Loan %s: Using custom amortization payment day (day %d)",
                    schedule.id,
                    schedule.amortization.payment_day_of_month,
                )
                forecast_dates = amort_occurrences

            # Filter out dates that already have actual transactions with this schedule_id
            #
            # This is critical to prevent duplicates when the hook has already matched
            # and enriched actual transactions. For example:
            # - Hook matched paycheck-captech on 2026-02-05, added schedule_id metadata
            # - Plugin generates 2026-02-05 in its forecast window
            # - Without filtering: both actual + forecast appear (user sees duplicate)
            # - With filtering: forecast is skipped, only actual appears
            #
            # Uses shared utility: filter_occurrences_by_existing_transactions()
            original_count = len(forecast_dates)
            forecast_dates = filter_occurrences_by_existing_transactions(
                schedule, forecast_dates, entries
            )
            if len(forecast_dates) < original_count:
                logger.debug(
                    "Filtered %d occurrence(s) for %s (actual transaction exists)",
                    original_count - len(forecast_dates),
                    schedule.id,
                )

            # Pre-compute stateful P/I splits when applicable
            amort_splits = None
            if schedule.amortization and schedule.amortization.balance_from_ledger:
                from beanschedule.amortization import compute_stateful_splits

                principal_account = _get_principal_account(schedule)
                if principal_account and principal_account in liability_balances:
                    balance, balance_date = liability_balances[principal_account]
                    if balance > Decimal("0"):
                        if (today - balance_date).days > 60:
                            logger.warning(
                                "Loan %s: most recent cleared posting to %s is %d days old. "
                                "Missing payments may cause incorrect forecasts.",
                                schedule.id,
                                principal_account,
                                (today - balance_date).days,
                            )

                        # Use amort_occurrences if available (payment_day_of_month), else use regular occurrences
                        split_dates = (
                            amort_occurrences if amort_occurrences else occurrences
                        )

                        amort_splits = compute_stateful_splits(
                            monthly_payment=schedule.amortization.monthly_payment,  # type: ignore[arg-type]
                            annual_rate=schedule.amortization.annual_rate,
                            compounding=schedule.amortization.compounding.value,
                            starting_balance=balance,
                            starting_date=balance_date,
                            occurrence_dates=split_dates,
                            extra_principal=schedule.amortization.extra_principal
                            or Decimal("0"),
                        )
                    else:
                        logger.info(
                            "Loan %s: liability balance is zero or negative, skipping forecasts",
                            schedule.id,
                        )
                        continue
                else:
                    logger.warning(
                        "Loan %s: balance_from_ledger enabled but no cleared transactions "
                        "found for %s. Skipping forecasts for this schedule.",
                        schedule.id,
                        principal_account,
                    )
                    continue

            # Create forecast transaction for each occurrence
            for occurrence_date in forecast_dates:
                # In stateful mode, skip dates beyond loan payoff
                if amort_splits is not None and occurrence_date not in amort_splits:
                    continue

                # Select shadow account based on whether the date is overdue or upcoming
                shadow_account = (
                    shadow_overdue_account
                    if occurrence_date <= today
                    else shadow_upcoming_account
                )

                forecast_txn = _create_forecast_transaction(
                    schedule,
                    occurrence_date,
                    schedule_file.config,
                    amort_splits,
                    shadow_account,
                    forecast_flag,
                )
                forecast_entries.append(forecast_txn)

            logger.debug(
                "Generated %d forecast(s) for %s", len(forecast_dates), schedule.id
            )

        except Exception as e:
            error_msg = f"Failed to generate forecasts for {schedule.id}: {e}"
            logger.error("%s", error_msg)
            errors.append(error_msg)

    logger.info("Generated %d forecast transaction(s)", len(forecast_entries))

    # 4. Open directives for shadow accounts
    # Automatically open any shadow accounts that aren't already open in the ledger,
    # using the earliest date the account appears in the generated forecast entries.
    shadow_accounts_used: dict[str, date] = {}
    for txn in forecast_entries:
        if not isinstance(txn, data.Transaction):
            continue
        for posting in txn.postings:
            if posting.account in (shadow_upcoming_account, shadow_overdue_account):
                if posting.account not in shadow_accounts_used:
                    shadow_accounts_used[posting.account] = txn.date
                else:
                    shadow_accounts_used[posting.account] = min(
                        shadow_accounts_used[posting.account], txn.date
                    )

    existing_open_accounts = {
        entry.account for entry in entries if isinstance(entry, data.Open)
    }

    for idx, (account, open_date) in enumerate(sorted(shadow_accounts_used.items())):
        if account not in existing_open_accounts:
            meta = data.new_metadata("<beanschedule.plugins.schedules>", idx)
            forecast_entries.append(data.Open(meta, open_date, account, None, None))  # type: ignore[arg-type]
            logger.debug(
                "Added Open directive for shadow account %s on %s", account, open_date
            )

    # 5. Sort and return
    # Must sort ALL entries together (not just forecast_entries) so that shadow
    # account Open directives appear before any transactions that post to them,
    # even if the original ledger contains future-dated entries (balance assertions,
    # notes, etc.) that would otherwise appear after the Open directives.
    all_entries = entries + forecast_entries
    all_entries.sort(key=data.entry_sortkey)

    return all_entries, errors


def _get_active_amortization_override(amortization_config, occurrence_date):
    """Find the most recent override before or on the occurrence date.

    Args:
        amortization_config: AmortizationConfig with optional overrides
        occurrence_date: Date to find override for

    Returns:
        AmortizationOverride or None if no override is active
    """
    if not amortization_config.overrides:
        return None

    # Find the most recent override that is <= occurrence_date
    active_override = None
    for override in sorted(
        amortization_config.overrides, key=lambda x: x.effective_date
    ):
        if override.effective_date <= occurrence_date:
            active_override = override
        else:
            # Overrides are sorted, so we can stop once we pass the occurrence date
            break

    return active_override


def _get_principal_account(schedule) -> str | None:
    """Return the account with role='principal' from a schedule's postings, or None."""
    if not schedule.transaction.postings:
        return None
    for posting in schedule.transaction.postings:
        if posting.role == "principal":
            return posting.account
    return None


def _create_forecast_transaction(
    schedule,
    occurrence_date,
    global_config,
    amort_splits=None,
    shadow_account: str | None = None,
    forecast_flag: str = "#",
):
    """Create a forecast transaction from a schedule.

    Args:
        schedule: Schedule object from schema
        occurrence_date: Date for this forecast occurrence
        global_config: GlobalConfig with defaults

    Returns:
        beancount.core.data.Transaction with forecast flag (#)
    """
    # Compute display filename for metadata
    display_filename = "<schedules>"  # Default fallback
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
        "filing_account": schedule.match.account,  # Original match account before shadow redirect
    }

    # Add schedule metadata if present
    if schedule.transaction.metadata:
        for key, value in schedule.transaction.metadata.items():
            # Don't duplicate schedule_id
            if key != "schedule_id":
                meta[key] = value

    # Check if amortization is configured
    amortization_split = None
    if amort_splits and occurrence_date in amort_splits:
        # ── stateful mode: split was pre-computed from ledger balance ──────
        amortization_split = amort_splits[occurrence_date]
        meta["amortization_balance_after"] = str(amortization_split.remaining_balance)
        meta["amortization_principal"] = str(amortization_split.principal)
        meta["amortization_interest"] = str(amortization_split.interest)
    elif schedule.amortization and not schedule.amortization.balance_from_ledger:
        # ── static mode: derive from original loan terms ───────────────────
        from beanschedule.amortization import AmortizationSchedule

        # Check for active override for this occurrence date
        active_override = _get_active_amortization_override(
            schedule.amortization, occurrence_date
        )

        # Determine effective parameters (base + overrides)
        if active_override:
            # Use override values, falling back to base config
            effective_principal = (
                active_override.principal
                if active_override.principal is not None
                else schedule.amortization.principal
            )
            effective_rate = (
                active_override.annual_rate
                if active_override.annual_rate is not None
                else schedule.amortization.annual_rate
            )
            effective_term = (
                active_override.term_months
                if active_override.term_months is not None
                else schedule.amortization.term_months
            )
            effective_extra = (
                active_override.extra_principal
                if active_override.extra_principal is not None
                else schedule.amortization.extra_principal
            )
            # Start date becomes the override effective date
            effective_start = active_override.effective_date
        else:
            # Use base config
            effective_principal = schedule.amortization.principal
            effective_rate = schedule.amortization.annual_rate
            effective_term = schedule.amortization.term_months
            effective_extra = schedule.amortization.extra_principal
            effective_start = schedule.amortization.start_date

        # Create amortization schedule with effective parameters
        amort_schedule = AmortizationSchedule(
            principal=effective_principal,
            annual_rate=effective_rate,
            term_months=effective_term,
            start_date=effective_start,
            extra_principal=effective_extra,
        )

        # Get payment number for this occurrence
        payment_number = amort_schedule.get_payment_number_for_date(occurrence_date)

        if payment_number is not None:
            # Calculate principal/interest split
            amortization_split = amort_schedule.get_payment_split(payment_number)

            # Add amortization metadata
            meta["amortization_payment_number"] = payment_number
            meta["amortization_balance_after"] = str(
                amortization_split.remaining_balance
            )
            meta["amortization_principal"] = str(amortization_split.principal)
            meta["amortization_interest"] = str(amortization_split.interest)

    # Build postings - calculate balancing amounts for forecast transactions
    postings = []

    # First pass: collect amounts and validate posting structure
    null_amount_indices = []
    specified_amounts = []
    amortized_amounts = {}  # Track which postings will use amortization
    match_account_amounts = {}  # Track match account postings using match.amount

    for idx, posting_template in enumerate(schedule.transaction.postings):
        if posting_template.amount is not None:
            specified_amounts.append(Decimal(str(posting_template.amount)))
        elif (
            posting_template.account == schedule.match.account
            and schedule.match.amount is not None
            and not amortization_split
            and posting_template.role
            not in ("payment", "interest", "principal", "escrow")
        ):
            # Match account posting with null amount — use match.amount for the forecast
            match_amount = Decimal(str(schedule.match.amount))
            match_account_amounts[idx] = match_amount
            specified_amounts.append(match_amount)
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
    if not schedule.amortization:
        if len(null_amount_indices) > 1:
            raise ValueError(
                f"Schedule {schedule.id}: Multiple postings have null amounts. "
                f"At most one posting can have a null amount (the balancing posting)."
            )

    # Validation: if all amounts are null AND no amortization, that's an error
    # (With amortization, null amounts are OK as long as they have roles)
    if (
        len(null_amount_indices) == len(schedule.transaction.postings)
        and not schedule.amortization
    ):
        raise ValueError(
            f"Schedule {schedule.id}: All postings have null amounts. "
            f"At least one posting must specify an amount."
        )

    # Calculate amounts for all non-payment postings first
    total_non_payment = sum(specified_amounts)  # Fixed amounts (e.g., escrow)
    total_non_payment += sum(
        amortized_amounts.values()
    )  # Amortized amounts (principal, interest)

    # Second pass: create postings
    for idx, posting_template in enumerate(schedule.transaction.postings):
        # Determine amount - check if this is an amortization posting
        posting_amount_value = None

        # Priority 1: Use explicit amount from YAML
        if posting_template.amount is not None:
            posting_amount_value = Decimal(str(posting_template.amount))

        # Priority 2: Use match.amount for match account posting (null template)
        elif idx in match_account_amounts:
            posting_amount_value = match_account_amounts[idx]

        # Priority 3: Use amortized amount
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
                balancing_posting_idx = (
                    null_amount_indices[0] if null_amount_indices else None
                )
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
            raise ValueError(
                f"Schedule {schedule.id}: Could not determine amount for posting "
                f"to account '{posting_template.account}' (index {idx})"
            )

        posting_currency = (
            posting_template.currency
            or global_config.default_currency
            or DEFAULT_CURRENCY
        )
        posting_amount = amount.Amount(
            Decimal(posting_amount_value),
            posting_currency,
        )

        # Redirect matched account posting to shadow account if configured
        posting_account = posting_template.account
        if shadow_account and posting_account == schedule.match.account:
            posting_account = shadow_account

        posting_meta: dict = {"filename": display_filename, "lineno": 0}
        if posting_template.metadata:
            posting_meta.update(posting_template.metadata)
        posting = data.Posting(
            account=posting_account,
            units=posting_amount,
            cost=None,
            price=None,
            flag=None,
            meta=posting_meta,
        )
        postings.append(posting)

    # Create transaction with # flag (forecast)
    # Default narration to empty string if not specified (required by Beancount)
    narration = schedule.transaction.narration or ""

    txn = data.Transaction(
        meta=meta,
        date=occurrence_date,
        flag=forecast_flag,
        payee=schedule.transaction.payee,
        narration=narration,
        tags=frozenset(schedule.transaction.tags or []) | {"scheduled"},
        links=frozenset(schedule.transaction.links or []),
        postings=postings,
    )

    return txn
