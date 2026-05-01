"""Pydantic schema models for schedule validation."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dateutil.rrule import rrulestr
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import constants
from .types import CompoundingFrequency, FlagType


def _validate_positive(v: Any, name: str) -> Any:
    """Raise if v is provided and not strictly positive."""
    if v is not None and v <= 0:
        raise ValueError(f"{name} must be positive")
    return v


def _validate_nonnegative(v: Any, name: str) -> Any:
    """Raise if v is provided and negative."""
    if v is not None and v < 0:
        raise ValueError(f"{name} must be non-negative")
    return v


class MatchCriteria(BaseModel):
    """Matching criteria for identifying transactions.

    Amount matching supports two mutually exclusive modes:
    - Exact with tolerance: set ``amount`` (reference value) and optionally
      ``amount_tolerance`` (±). If ``amount_tolerance`` is set, ``amount`` is required.
    - Range: set both ``amount_min`` and ``amount_max``.

    Posting amounts in the schedule's ``transaction`` block are for enrichment only
    and play no role in matching.
    """

    account: str = Field(..., description="Account to match (exact)")
    payee_pattern: str = Field(..., description="Payee pattern (regex or fuzzy)")
    amount: Decimal | None = Field(
        None,
        description=(
            "Reference amount for matching (used with amount_tolerance). "
            "Must match the sign of the posting on match.account as it appears "
            "in the imported transaction (e.g. negative for outgoing payments on "
            "asset/liability accounts)."
        ),
    )
    amount_tolerance: Decimal | None = Field(
        None, description="Amount tolerance (±). Requires amount to be set."
    )
    amount_min: Decimal | None = Field(
        None, description="Minimum amount for range matching"
    )
    amount_max: Decimal | None = Field(
        None, description="Maximum amount for range matching"
    )
    date_window_days: int | None = Field(
        constants.DEFAULT_DATE_WINDOW_DAYS, description="Date matching window (±days)"
    )

    @field_validator("amount_tolerance")
    @classmethod
    def validate_amount_tolerance(cls, v: Decimal | None) -> Decimal | None:
        """Ensure amount_tolerance is non-negative."""
        if v is not None and v < 0:
            raise ValueError("amount_tolerance must be non-negative")
        return v

    @field_validator("date_window_days")
    @classmethod
    def validate_date_window(cls, v: int | None) -> int | None:
        """Ensure date_window_days is non-negative."""
        if v is not None and v < 0:
            raise ValueError("date_window_days must be non-negative")
        return v

    @model_validator(mode="after")
    def validate_amount_fields(self) -> "MatchCriteria":
        """Enforce mutual exclusivity and dependency of amount fields."""
        has_tolerance = self.amount_tolerance is not None
        has_amount = self.amount is not None
        has_range = self.amount_min is not None or self.amount_max is not None

        if has_tolerance and not has_amount:
            raise ValueError(
                "amount_tolerance requires amount to be set (tolerance has no reference without it)"
            )

        if has_amount and has_range:
            raise ValueError(
                "amount and amount_min/amount_max are mutually exclusive — use one or the other"
            )

        if has_range and (self.amount_min is None or self.amount_max is None):
            raise ValueError(
                "amount_min and amount_max must both be set for range matching"
            )

        return self


_LEGACY_WEEKDAY_MAP = {
    "MON": "MO",
    "TUE": "TU",
    "WED": "WE",
    "THU": "TH",
    "FRI": "FR",
    "SAT": "SA",
    "SUN": "SU",
}


def _build_rrule_from_legacy(data: dict[str, Any]) -> str:
    """Convert old frequency/day_of_month/etc fields to an RRULE string."""
    freq_raw = data.get("frequency", "")
    # Handle both enum instances and plain strings
    frequency = (getattr(freq_raw, "value", freq_raw) or "").upper()
    day_of_month = data.get("day_of_month")
    month = data.get("month")
    dow_raw = data.get("day_of_week") or ""
    day_of_week = (getattr(dow_raw, "value", dow_raw) or "").upper()
    interval = int(data.get("interval") or 1)
    days_of_month = data.get("days_of_month")
    interval_months = data.get("interval_months")
    nth_occurrence = data.get("nth_occurrence")

    if frequency == "MONTHLY":
        return f"FREQ=MONTHLY;BYMONTHDAY={day_of_month}"
    if frequency == "WEEKLY":
        byday = _LEGACY_WEEKDAY_MAP.get(day_of_week, day_of_week)
        parts = ["FREQ=WEEKLY"]
        if interval > 1:
            parts.append(f"INTERVAL={interval}")
        parts.append(f"BYDAY={byday}")
        return ";".join(parts)
    if frequency == "YEARLY":
        return f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day_of_month}"
    if frequency == "INTERVAL":
        return f"FREQ=MONTHLY;INTERVAL={interval_months};BYMONTHDAY={day_of_month}"
    if frequency in ("BIMONTHLY", "MONTHLY_ON_DAYS"):
        days_str = ",".join(str(d) for d in (days_of_month or []))
        return f"FREQ=MONTHLY;BYMONTHDAY={days_str}"
    if frequency == "NTH_WEEKDAY":
        byday = _LEGACY_WEEKDAY_MAP.get(day_of_week, day_of_week)
        nth = int(nth_occurrence or 1)
        prefix = f"+{nth}" if nth > 0 else str(nth)
        return f"FREQ=MONTHLY;BYDAY={prefix}{byday}"
    if frequency == "LAST_DAY_OF_MONTH":
        return "FREQ=MONTHLY;BYMONTHDAY=-1"
    raise ValueError(f"Unknown legacy frequency: {frequency!r}")


class RecurrenceRule(BaseModel):
    """Recurrence rule for generating expected dates."""

    rrule: str = Field(
        ...,
        description="RRULE string (RFC 5545), e.g. FREQ=MONTHLY;BYMONTHDAY=15",
    )
    start_date: date = Field(..., description="Start date for recurrence")
    end_date: date | None = Field(None, description="End date (null = ongoing)")

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_format(cls, data: Any) -> Any:
        """Convert old frequency/day_of_month/etc fields to rrule string."""
        if isinstance(data, dict) and "frequency" in data and "rrule" not in data:
            data = dict(data)
            data["rrule"] = _build_rrule_from_legacy(data)
        return data

    @field_validator("rrule")
    @classmethod
    def validate_rrule(cls, v: str) -> str:
        """Ensure rrule is parseable by dateutil."""
        try:
            rrulestr(v, dtstart=datetime(2024, 1, 1), ignoretz=True)
        except Exception as e:
            raise ValueError(f"Invalid RRULE '{v}': {e}") from e
        return v.upper()


class Posting(BaseModel):
    """Transaction posting."""

    account: str = Field(..., description="Account name")
    amount: Decimal | None = Field(None, description="Amount (null = use imported)")
    currency: str | None = Field(
        None,
        description=(
            "Currency for this posting (overrides default_currency). "
            "Use for non-default-currency postings such as vacation days (VACDAY) "
            "or stock grants (TSLA). When null, the schedule's default currency is used."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Posting metadata (e.g. narration, order_id)"
    )
    role: str | None = Field(
        None,
        description=(
            "Posting role for amortization: 'principal', 'interest', 'payment', or 'escrow'. "
            "If not specified, account name keywords are used (deprecated)."
        ),
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        """Ensure role is valid."""
        if v is not None:
            allowed_roles = {"principal", "interest", "payment", "escrow"}
            if v not in allowed_roles:
                msg = f"role must be one of {allowed_roles}, got '{v}'"
                raise ValueError(msg)
        return v


class TransactionTemplate(BaseModel):
    """Transaction template for schedule."""

    payee: str | None = Field(None, description="Payee (overrides imported)")
    narration: str | None = Field(None, description="Narration (overrides imported)")
    tags: list[str] = Field(default_factory=list, description="Tags to add")
    links: list[str] = Field(default_factory=list, description="Links to add")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadata to add"
    )
    postings: list[Posting] | None = Field(None, description="Full posting list")

    @field_validator("metadata")
    @classmethod
    def validate_metadata_has_schedule_id(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure metadata contains schedule_id."""
        if "schedule_id" not in v:
            raise ValueError("metadata must contain 'schedule_id' field")
        return v


class MissingTransactionConfig(BaseModel):
    """Configuration for missing transactions."""

    create_placeholder: bool = Field(True, description="Create placeholder transaction")
    flag: FlagType = Field(
        constants.DEFAULT_PLACEHOLDER_FLAG,
        description="Transaction flag for placeholder",
    )
    narration_prefix: str = Field(
        constants.DEFAULT_MISSING_PREFIX, description="Prefix for narration"
    )


class AmortizationOverride(BaseModel):
    """Override amortization parameters starting from a specific date.

    Allows adjusting loan parameters mid-term (e.g., starting extra payments,
    updating balance after lump sum payment, changing rate after refinance).

    Example:
        overrides:
          - effective_date: 2029-01-01
            principal: 285432.18
            extra_principal: 500.00
    """

    effective_date: date = Field(
        ..., description="Date when override becomes effective"
    )
    principal: Decimal | None = Field(None, description="New principal balance")
    annual_rate: Decimal | None = Field(None, description="New annual interest rate")
    term_months: int | None = Field(None, description="New remaining term in months")
    extra_principal: Decimal | None = Field(
        None, description="New extra principal amount"
    )

    @field_validator("principal")
    @classmethod
    def validate_principal_positive(cls, v: Decimal | None) -> Decimal | None:
        return _validate_positive(v, "principal")

    @field_validator("annual_rate")
    @classmethod
    def validate_rate_nonnegative(cls, v: Decimal | None) -> Decimal | None:
        return _validate_nonnegative(v, "annual_rate")

    @field_validator("term_months")
    @classmethod
    def validate_term_positive(cls, v: int | None) -> int | None:
        return _validate_positive(v, "term_months")

    @field_validator("extra_principal")
    @classmethod
    def validate_extra_principal_nonnegative(cls, v: Decimal | None) -> Decimal | None:
        return _validate_nonnegative(v, "extra_principal")


class AmortizationConfig(BaseModel):
    """Loan amortization configuration for automatic principal/interest split.

    Two modes, selected by ``balance_from_ledger``:

    **Static mode** (default) — PMT is derived from original loan terms.
      Required: principal, annual_rate, term_months, start_date.

    **Stateful mode** (balance_from_ledger: true) — balance is read from the
      liability account in the ledger at runtime; only the current fixed payment
      and rate are needed.  Original loan terms are not required.
      Required: annual_rate, monthly_payment.

    Static example::

        amortization:
          principal: 300000.00
          annual_rate: 0.0675
          term_months: 360
          start_date: 2024-01-01

    Stateful example::

        amortization:
          annual_rate: 0.04875
          balance_from_ledger: true
          monthly_payment: 1931.67
          compounding: MONTHLY          # or DAILY
          extra_principal: 200.00       # optional
    """

    # ── shared ────────────────────────────────────────────────────────────
    annual_rate: Decimal = Field(
        ..., description="Annual interest rate (e.g., 0.0675 for 6.75%)"
    )
    extra_principal: Decimal | None = Field(
        None, description="Optional extra principal payment per period"
    )
    overrides: list[AmortizationOverride] | None = Field(
        None, description="Date-based parameter overrides for mid-loan changes"
    )

    # ── static mode ───────────────────────────────────────────────────────
    principal: Decimal | None = Field(
        None, description="Initial loan principal (required for static mode)"
    )
    term_months: int | None = Field(
        None, description="Loan term in months (required for static mode)"
    )
    start_date: date | None = Field(
        None, description="First payment date (required for static mode)"
    )

    # ── stateful mode ─────────────────────────────────────────────────────
    balance_from_ledger: bool = Field(
        False,
        description="Read starting balance from the liability account in the ledger",
    )
    monthly_payment: Decimal | None = Field(
        None, description="Fixed P&I payment amount (required for stateful mode)"
    )
    compounding: CompoundingFrequency = Field(
        CompoundingFrequency.MONTHLY,
        description="Interest compounding frequency (MONTHLY or DAILY)",
    )
    payment_day_of_month: int | None = Field(
        None,
        description="Day of month for amortization payments (1-31). If set, overrides the transaction recurrence day for amortization calculations. Defaults to transaction recurrence day if not specified.",
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("principal")
    @classmethod
    def validate_principal_positive(cls, v: Decimal | None) -> Decimal | None:
        return _validate_positive(v, "principal")

    @field_validator("annual_rate")
    @classmethod
    def validate_rate_nonnegative(cls, v: Decimal) -> Decimal:
        return _validate_nonnegative(v, "annual_rate")

    @field_validator("term_months")
    @classmethod
    def validate_term_positive(cls, v: int | None) -> int | None:
        return _validate_positive(v, "term_months")

    @field_validator("extra_principal")
    @classmethod
    def validate_extra_principal_nonnegative(cls, v: Decimal | None) -> Decimal | None:
        return _validate_nonnegative(v, "extra_principal")

    @field_validator("monthly_payment")
    @classmethod
    def validate_monthly_payment_positive(cls, v: Decimal | None) -> Decimal | None:
        """Ensure monthly_payment is positive if provided."""
        if v is not None and v <= 0:
            raise ValueError("monthly_payment must be positive")
        return v

    @field_validator("payment_day_of_month")
    @classmethod
    def validate_payment_day_of_month(cls, v: int | None) -> int | None:
        """Ensure payment_day_of_month is between 1 and 31 if provided."""
        if v is not None and (v < 1 or v > 31):
            raise ValueError("payment_day_of_month must be between 1 and 31")
        return v

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "AmortizationConfig":
        """Enforce required fields based on selected mode."""
        if self.balance_from_ledger:
            if self.monthly_payment is None:
                raise ValueError(
                    "monthly_payment is required when balance_from_ledger is true"
                )
        else:
            if self.principal is None:
                raise ValueError(
                    "principal is required when balance_from_ledger is false (static mode)"
                )
            if self.term_months is None:
                raise ValueError(
                    "term_months is required when balance_from_ledger is false (static mode)"
                )
            if self.start_date is None:
                raise ValueError(
                    "start_date is required when balance_from_ledger is false (static mode)"
                )
        return self


class Schedule(BaseModel):
    """Complete schedule definition."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(..., description="Unique schedule identifier")
    enabled: bool = Field(True, description="Whether schedule is enabled")
    match: MatchCriteria = Field(..., description="Match criteria")
    recurrence: RecurrenceRule = Field(..., description="Recurrence rule")
    transaction: TransactionTemplate = Field(..., description="Transaction template")
    missing_transaction: MissingTransactionConfig = Field(
        default_factory=MissingTransactionConfig,
        description="Missing transaction config",
    )
    amortization: AmortizationConfig | None = Field(
        None, description="Optional loan amortization configuration"
    )
    source_file: Path | None = Field(
        None,
        exclude=True,
        description="Source file path (populated during loading, not from YAML)",
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure id is valid."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v

    @field_validator("transaction")
    @classmethod
    def validate_schedule_id_matches(
        cls,
        v: "TransactionTemplate",
        info,
    ) -> "TransactionTemplate":
        """Ensure transaction.metadata.schedule_id matches the schedule id."""
        schedule_id = info.data.get("id")
        metadata_schedule_id = v.metadata.get("schedule_id")

        if metadata_schedule_id != schedule_id:
            raise ValueError(
                f"transaction.metadata.schedule_id ('{metadata_schedule_id}') "
                f"must match schedule id ('{schedule_id}')",
            )
        return v


class GlobalConfig(BaseModel):
    """Global configuration for beanschedule."""

    default_currency: str | None = Field(
        None,
        description=(
            "Default currency for transactions. When null (the default), the currency "
            "is auto-detected: the plugin reads it from the ledger's "
            "'option \"operating_currency\"' directive; the hook infers it from the "
            "existing ledger entries. Set explicitly to override auto-detection."
        ),
    )
    fuzzy_match_threshold: float = Field(
        constants.DEFAULT_FUZZY_MATCH_THRESHOLD,
        description="Fuzzy match threshold (0.0-1.0)",
    )
    default_date_window_days: int = Field(
        constants.DEFAULT_DATE_WINDOW_DAYS, description="Default date window (±days)"
    )
    default_amount_tolerance_percent: float = Field(
        constants.DEFAULT_AMOUNT_TOLERANCE_PERCENT,
        description="Default amount tolerance (%)",
    )
    placeholder_flag: FlagType = Field(
        constants.DEFAULT_PLACEHOLDER_FLAG,
        description="Flag for placeholder transactions",
    )
    forecast_months: int = Field(
        constants.DEFAULT_FORECAST_MONTHS,
        description="How many months forward to forecast",
    )
    min_forecast_date: date | None = Field(
        None,
        description="Override start date for forecasting (null = use transaction range)",
    )
    include_past_dates: bool = Field(
        constants.DEFAULT_INCLUDE_PAST_DATES,
        description="Generate placeholders for dates in the past",
    )

    @field_validator("fuzzy_match_threshold")
    @classmethod
    def validate_fuzzy_threshold(cls, v: float) -> float:
        """Ensure fuzzy_match_threshold is in valid range."""
        if v < 0.0 or v > 1.0:
            raise ValueError("fuzzy_match_threshold must be between 0.0 and 1.0")
        return v

    @field_validator("forecast_months")
    @classmethod
    def validate_forecast_months(cls, v: int) -> int:
        """Ensure forecast_months is positive."""
        if v < 0:
            raise ValueError("forecast_months must be non-negative")
        return v


class ScheduleFile(BaseModel):
    """Root schedule file structure."""

    version: str = Field(
        constants.SCHEDULE_FILE_VERSION, description="Schedule file format version"
    )
    schedules: list[Schedule] = Field(
        default_factory=list, description="List of schedules"
    )
    config: GlobalConfig = Field(
        default_factory=GlobalConfig, description="Global configuration"
    )
