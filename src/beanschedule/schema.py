"""Pydantic schema models for schedule validation."""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from .types import DayOfWeek, FlagType, FrequencyType


class MatchCriteria(BaseModel):
    """Matching criteria for identifying transactions."""

    account: str = Field(..., description="Account to match (exact)")
    payee_pattern: str = Field(..., description="Payee pattern (regex or fuzzy)")
    amount: Optional[Decimal] = Field(None, description="Expected amount")
    amount_tolerance: Optional[Decimal] = Field(None, description="Amount tolerance (±)")
    amount_min: Optional[Decimal] = Field(None, description="Minimum amount for range")
    amount_max: Optional[Decimal] = Field(None, description="Maximum amount for range")
    date_window_days: Optional[int] = Field(3, description="Date matching window (±days)")

    @field_validator("amount_tolerance")
    @classmethod
    def validate_amount_tolerance(cls, v, info):
        """Ensure amount_tolerance is positive."""
        if v is not None and v < 0:
            raise ValueError("amount_tolerance must be positive")
        return v

    @field_validator("date_window_days")
    @classmethod
    def validate_date_window(cls, v):
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

    # Bi-monthly
    days_of_month: Optional[List[int]] = Field(None, description="Days of month for bi-monthly")

    # Interval (every X months)
    interval_months: Optional[int] = Field(None, description="Month interval")

    @field_validator("day_of_month")
    @classmethod
    def validate_day_of_month(cls, v):
        """Ensure day_of_month is in valid range."""
        if v is not None and (v < 1 or v > 31):
            raise ValueError("day_of_month must be between 1 and 31")
        return v

    @field_validator("month")
    @classmethod
    def validate_month(cls, v):
        """Ensure month is in valid range."""
        if v is not None and (v < 1 or v > 12):
            raise ValueError("month must be between 1 and 12")
        return v

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, v):
        """Ensure interval is positive."""
        if v is not None and v < 1:
            raise ValueError("interval must be at least 1")
        return v

    @field_validator("interval_months")
    @classmethod
    def validate_interval_months(cls, v):
        """Ensure interval_months is positive."""
        if v is not None and v < 1:
            raise ValueError("interval_months must be at least 1")
        return v

    @field_validator("days_of_month")
    @classmethod
    def validate_days_of_month(cls, v):
        """Ensure days_of_month are in valid range."""
        if v is not None:
            for day in v:
                if day < 1 or day > 31:
                    raise ValueError("days_of_month must be between 1 and 31")
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
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags to add")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata to add")
    postings: Optional[List[Posting]] = Field(None, description="Full posting list")

    @field_validator("metadata")
    @classmethod
    def validate_metadata_has_schedule_id(cls, v):
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
    def validate_id(cls, v):
        """Ensure id is valid."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v

    @field_validator("transaction")
    @classmethod
    def validate_schedule_id_matches(cls, v, info):
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

    fuzzy_match_threshold: float = Field(0.80, description="Fuzzy match threshold (0.0-1.0)")
    default_date_window_days: int = Field(3, description="Default date window (±days)")
    default_amount_tolerance_percent: float = Field(
        0.02,
        description="Default amount tolerance (%)",
    )
    placeholder_flag: FlagType = Field("!", description="Flag for placeholder transactions")

    @field_validator("fuzzy_match_threshold")
    @classmethod
    def validate_fuzzy_threshold(cls, v):
        """Ensure fuzzy_match_threshold is in valid range."""
        if v < 0.0 or v > 1.0:
            raise ValueError("fuzzy_match_threshold must be between 0.0 and 1.0")
        return v


class ScheduleFile(BaseModel):
    """Root schedule file structure."""

    version: str = Field("1.0", description="Schedule file format version")
    schedules: List[Schedule] = Field(default_factory=list, description="List of schedules")
    config: GlobalConfig = Field(default_factory=GlobalConfig, description="Global configuration")
