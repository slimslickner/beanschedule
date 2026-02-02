"""Pydantic schema models for schedule validation."""

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from .types import DayOfWeek, FlagType, FrequencyType

# Constants for validation
MIN_DAY_OF_MONTH = 1
MAX_DAY_OF_MONTH = 31
MIN_MONTH = 1
MAX_MONTH = 12


class MatchCriteria(BaseModel):
    """Matching criteria for identifying transactions."""

    account: str = Field(..., description="Account to match (exact)")
    payee_pattern: str = Field(..., description="Payee pattern (regex or fuzzy)")
    amount: Optional[Decimal] = Field(
        None,
        description="[DEPRECATED] Expected amount - prefer specifying amount in postings instead. "
        "Amount is now derived from the posting for the matched account.",
    )
    amount_tolerance: Optional[Decimal] = Field(None, description="Amount tolerance (±)")
    amount_min: Optional[Decimal] = Field(None, description="Minimum amount for range")
    amount_max: Optional[Decimal] = Field(None, description="Maximum amount for range")
    date_window_days: Optional[int] = Field(3, description="Date matching window (±days)")

    @field_validator("amount_tolerance")
    @classmethod
    def validate_amount_tolerance(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        """Ensure amount_tolerance is positive."""
        if v is not None and v < 0:
            raise ValueError("amount_tolerance must be positive")
        return v

    @field_validator("date_window_days")
    @classmethod
    def validate_date_window(cls, v: Optional[int]) -> Optional[int]:
        """Ensure date_window_days is positive."""
        if v is not None and v < 0:
            raise ValueError("date_window_days must be positive")
        return v


class RecurrenceRule(BaseModel):
    """Recurrence rule for generating expected dates."""

    frequency: FrequencyType = Field(..., description="Recurrence frequency")
    start_date: date = Field(..., description="Start date for recurrence")
    end_date: Optional[date] = Field(None, description="End date (null = ongoing)")

    # Monthly/Yearly
    day_of_month: Optional[int] = Field(None, description="Day of month (1-31)")
    month: Optional[int] = Field(None, description="Month for yearly (1-12)")

    # Weekly
    day_of_week: Optional[DayOfWeek] = Field(None, description="Day of week")
    interval: Optional[int] = Field(1, description="Interval (e.g., 2 for bi-weekly)")

    # Bi-monthly / MONTHLY_ON_DAYS
    days_of_month: Optional[list[int]] = Field(
        None, description="Days of month (for BIMONTHLY/MONTHLY_ON_DAYS)"
    )

    # Interval (every X months)
    interval_months: Optional[int] = Field(None, description="Month interval")

    # NTH_WEEKDAY (e.g., 2nd Tuesday)
    nth_occurrence: Optional[int] = Field(
        None, description="Nth occurrence of weekday (1-5, -1 for last)"
    )

    @field_validator("day_of_month")
    @classmethod
    def validate_day_of_month(cls, v: Optional[int]) -> Optional[int]:
        """Ensure day_of_month is in valid range."""
        if v is not None and (v < MIN_DAY_OF_MONTH or v > MAX_DAY_OF_MONTH):
            msg = f"day_of_month must be between {MIN_DAY_OF_MONTH} and {MAX_DAY_OF_MONTH}"
            raise ValueError(msg)
        return v

    @field_validator("month")
    @classmethod
    def validate_month(cls, v: Optional[int]) -> Optional[int]:
        """Ensure month is in valid range."""
        if v is not None and (v < MIN_MONTH or v > MAX_MONTH):
            msg = f"month must be between {MIN_MONTH} and {MAX_MONTH}"
            raise ValueError(msg)
        return v

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, v: Optional[int]) -> Optional[int]:
        """Ensure interval is positive."""
        if v is not None and v < 1:
            raise ValueError("interval must be at least 1")
        return v

    @field_validator("interval_months")
    @classmethod
    def validate_interval_months(cls, v: Optional[int]) -> Optional[int]:
        """Ensure interval_months is positive."""
        if v is not None and v < 1:
            raise ValueError("interval_months must be at least 1")
        return v

    @field_validator("days_of_month")
    @classmethod
    def validate_days_of_month(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        """Ensure days_of_month are in valid range."""
        if v is not None:
            for day in v:
                if day < MIN_DAY_OF_MONTH or day > MAX_DAY_OF_MONTH:
                    msg = f"days_of_month must be between {MIN_DAY_OF_MONTH} and {MAX_DAY_OF_MONTH}"
                    raise ValueError(msg)
        return v

    @field_validator("nth_occurrence")
    @classmethod
    def validate_nth_occurrence(cls, v: Optional[int]) -> Optional[int]:
        """Ensure nth_occurrence is valid (1-5 or -1 for last)."""
        if v is not None and (v < -1 or v == 0 or v > 5):
            raise ValueError("nth_occurrence must be 1-5 or -1 (for last)")
        return v


class Posting(BaseModel):
    """Transaction posting."""

    account: str = Field(..., description="Account name")
    amount: Optional[Decimal] = Field(None, description="Amount (null = use imported)")
    narration: Optional[str] = Field(None, description="Comment for this posting")


class TransactionTemplate(BaseModel):
    """Transaction template for schedule."""

    payee: Optional[str] = Field(None, description="Payee (overrides imported)")
    narration: Optional[str] = Field(None, description="Narration (overrides imported)")
    tags: Optional[list[str]] = Field(default_factory=list, description="Tags to add")
    links: Optional[list[str]] = Field(default_factory=list, description="Links to add")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata to add")
    postings: Optional[list[Posting]] = Field(None, description="Full posting list")

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
    flag: FlagType = Field("!", description="Transaction flag for placeholder")
    narration_prefix: str = Field("[MISSING]", description="Prefix for narration")


class Schedule(BaseModel):
    """Complete schedule definition."""

    id: str = Field(..., description="Unique schedule identifier")
    enabled: bool = Field(True, description="Whether schedule is enabled")
    match: MatchCriteria = Field(..., description="Match criteria")
    recurrence: RecurrenceRule = Field(..., description="Recurrence rule")
    transaction: TransactionTemplate = Field(..., description="Transaction template")
    missing_transaction: MissingTransactionConfig = Field(
        default_factory=MissingTransactionConfig,
        description="Missing transaction config",
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

    default_currency: str = Field("USD", description="Default currency for transactions")
    fuzzy_match_threshold: float = Field(0.80, description="Fuzzy match threshold (0.0-1.0)")
    default_date_window_days: int = Field(3, description="Default date window (±days)")
    default_amount_tolerance_percent: float = Field(
        0.02,
        description="Default amount tolerance (%)",
    )
    placeholder_flag: FlagType = Field("!", description="Flag for placeholder transactions")

    @field_validator("fuzzy_match_threshold")
    @classmethod
    def validate_fuzzy_threshold(cls, v: float) -> float:
        """Ensure fuzzy_match_threshold is in valid range."""
        if v < 0.0 or v > 1.0:
            raise ValueError("fuzzy_match_threshold must be between 0.0 and 1.0")
        return v


class ScheduleFile(BaseModel):
    """Root schedule file structure."""

    version: str = Field("1.0", description="Schedule file format version")
    schedules: list[Schedule] = Field(default_factory=list, description="List of schedules")
    config: GlobalConfig = Field(default_factory=GlobalConfig, description="Global configuration")
