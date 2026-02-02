"""Tests for schema validation using Pydantic models."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from beanschedule.schema import (
    GlobalConfig,
    MatchCriteria,
    MissingTransactionConfig,
    RecurrenceRule,
    Schedule,
    ScheduleFile,
    TransactionTemplate,
)
from beanschedule.types import FrequencyType


class TestMatchCriteria:
    """Tests for MatchCriteria validation."""

    def test_create_valid_match_criteria(self):
        """Test creating valid MatchCriteria."""
        criteria = MatchCriteria(
            account="Assets:Bank:Checking",
            payee_pattern="Test",
            amount=Decimal("-100.00"),
        )
        assert criteria.account == "Assets:Bank:Checking"
        assert criteria.payee_pattern == "Test"
        assert criteria.amount == Decimal("-100.00")

    def test_amount_tolerance_must_be_positive(self):
        """Test that negative amount_tolerance is rejected."""
        with pytest.raises(ValueError, match="amount_tolerance must be positive"):
            MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
                amount_tolerance=Decimal("-5.00"),
            )

    def test_date_window_days_must_be_positive(self):
        """Test that negative date_window_days is rejected."""
        with pytest.raises(ValueError, match="date_window_days must be positive"):
            MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
                date_window_days=-5,
            )

    def test_date_window_days_zero_is_allowed(self):
        """Test that zero date_window_days is allowed (exact match only)."""
        criteria = MatchCriteria(
            account="Assets:Bank:Checking",
            payee_pattern="Test",
            date_window_days=0,
        )
        assert criteria.date_window_days == 0

    def test_optional_amounts(self):
        """Test that amount fields are optional."""
        criteria = MatchCriteria(
            account="Assets:Bank:Checking",
            payee_pattern="Test",
            amount=None,
            amount_min=None,
            amount_max=None,
        )
        assert criteria.amount is None


class TestRecurrenceRule:
    """Tests for RecurrenceRule validation."""

    def test_create_monthly_rule(self):
        """Test creating valid MONTHLY recurrence rule."""
        rule = RecurrenceRule(
            frequency=FrequencyType.MONTHLY,
            start_date=date(2024, 1, 1),
            day_of_month=15,
        )
        assert rule.frequency == FrequencyType.MONTHLY
        assert rule.day_of_month == 15

    def test_day_of_month_valid_range(self):
        """Test that day_of_month accepts 1-31."""
        for day in [1, 15, 28, 31]:
            rule = RecurrenceRule(
                frequency=FrequencyType.MONTHLY,
                start_date=date(2024, 1, 1),
                day_of_month=day,
            )
            assert rule.day_of_month == day

    def test_day_of_month_zero_rejected(self):
        """Test that day_of_month=0 is rejected."""
        with pytest.raises(ValueError, match="day_of_month must be between 1 and 31"):
            RecurrenceRule(
                frequency=FrequencyType.MONTHLY,
                start_date=date(2024, 1, 1),
                day_of_month=0,
            )

    def test_day_of_month_32_rejected(self):
        """Test that day_of_month=32 is rejected."""
        with pytest.raises(ValueError, match="day_of_month must be between 1 and 31"):
            RecurrenceRule(
                frequency=FrequencyType.MONTHLY,
                start_date=date(2024, 1, 1),
                day_of_month=32,
            )

    def test_month_valid_range(self):
        """Test that month accepts 1-12."""
        for month in [1, 6, 12]:
            rule = RecurrenceRule(
                frequency=FrequencyType.YEARLY,
                start_date=date(2024, 1, 1),
                day_of_month=15,
                month=month,
            )
            assert rule.month == month

    def test_month_zero_rejected(self):
        """Test that month=0 is rejected."""
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            RecurrenceRule(
                frequency=FrequencyType.YEARLY,
                start_date=date(2024, 1, 1),
                month=0,
            )

    def test_month_13_rejected(self):
        """Test that month=13 is rejected."""
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            RecurrenceRule(
                frequency=FrequencyType.YEARLY,
                start_date=date(2024, 1, 1),
                month=13,
            )

    def test_interval_must_be_positive(self):
        """Test that interval must be at least 1."""
        with pytest.raises(ValueError, match="interval must be at least 1"):
            RecurrenceRule(
                frequency=FrequencyType.WEEKLY,
                start_date=date(2024, 1, 1),
                interval=0,
            )

    def test_interval_months_must_be_positive(self):
        """Test that interval_months must be at least 1."""
        with pytest.raises(ValueError, match="interval_months must be at least 1"):
            RecurrenceRule(
                frequency=FrequencyType.INTERVAL,
                start_date=date(2024, 1, 1),
                day_of_month=15,
                interval_months=0,
            )

    def test_days_of_month_valid_range(self):
        """Test that days_of_month accepts valid days."""
        rule = RecurrenceRule(
            frequency=FrequencyType.BIMONTHLY,
            start_date=date(2024, 1, 1),
            days_of_month=[5, 20],
        )
        assert rule.days_of_month == [5, 20]

    def test_days_of_month_invalid_zero(self):
        """Test that days_of_month rejects 0."""
        with pytest.raises(ValueError, match="days_of_month must be between 1 and 31"):
            RecurrenceRule(
                frequency=FrequencyType.BIMONTHLY,
                start_date=date(2024, 1, 1),
                days_of_month=[0, 20],
            )

    def test_days_of_month_invalid_32(self):
        """Test that days_of_month rejects 32."""
        with pytest.raises(ValueError, match="days_of_month must be between 1 and 31"):
            RecurrenceRule(
                frequency=FrequencyType.BIMONTHLY,
                start_date=date(2024, 1, 1),
                days_of_month=[5, 32],
            )


class TestTransactionTemplate:
    """Tests for TransactionTemplate validation."""

    def test_metadata_requires_schedule_id(self):
        """Test that metadata must contain schedule_id."""
        with pytest.raises(ValueError, match="metadata must contain 'schedule_id' field"):
            TransactionTemplate(
                payee="Test",
                metadata={"other_key": "value"},
            )

    def test_metadata_with_schedule_id_succeeds(self):
        """Test that metadata with schedule_id is accepted."""
        template = TransactionTemplate(
            payee="Test",
            metadata={"schedule_id": "test-schedule"},
        )
        assert template.metadata["schedule_id"] == "test-schedule"

    def test_empty_metadata_fails(self):
        """Test that empty metadata dict fails."""
        with pytest.raises(ValueError, match="metadata must contain 'schedule_id' field"):
            TransactionTemplate(
                payee="Test",
                metadata={},
            )

    def test_additional_metadata_allowed(self):
        """Test that additional metadata fields are allowed."""
        template = TransactionTemplate(
            payee="Test",
            metadata={
                "schedule_id": "test-schedule",
                "category": "income",
                "custom_field": "custom_value",
            },
        )
        assert template.metadata["category"] == "income"
        assert template.metadata["custom_field"] == "custom_value"


class TestSchedule:
    """Tests for Schedule validation."""

    def test_create_valid_schedule(self, sample_schedule):
        """Test creating a valid schedule."""
        schedule = sample_schedule()
        assert schedule.id == "test-schedule"
        assert schedule.enabled is True

    def test_empty_id_rejected(self, global_config):
        """Test that empty id is rejected."""
        with pytest.raises(ValueError, match="id cannot be empty"):
            Schedule(
                id="",
                match=MatchCriteria(
                    account="Assets:Bank:Checking",
                    payee_pattern="Test",
                ),
                recurrence=RecurrenceRule(
                    frequency=FrequencyType.MONTHLY,
                    start_date=date(2024, 1, 1),
                    day_of_month=15,
                ),
                transaction=TransactionTemplate(
                    metadata={"schedule_id": "test"},
                ),
            )

    def test_schedule_id_matches_metadata_schedule_id(self):
        """Test that schedule id matches transaction.metadata.schedule_id."""
        schedule = Schedule(
            id="my-schedule",
            match=MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
            ),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.MONTHLY,
                start_date=date(2024, 1, 1),
                day_of_month=15,
            ),
            transaction=TransactionTemplate(
                metadata={"schedule_id": "my-schedule"},
            ),
        )
        assert schedule.id == "my-schedule"
        assert schedule.transaction.metadata["schedule_id"] == "my-schedule"

    def test_schedule_id_mismatch_rejected(self):
        """Test that mismatched schedule_id is rejected."""
        with pytest.raises(
            ValueError,
            match="transaction.metadata.schedule_id.*must match schedule id",
        ):
            Schedule(
                id="my-schedule",
                match=MatchCriteria(
                    account="Assets:Bank:Checking",
                    payee_pattern="Test",
                ),
                recurrence=RecurrenceRule(
                    frequency=FrequencyType.MONTHLY,
                    start_date=date(2024, 1, 1),
                    day_of_month=15,
                ),
                transaction=TransactionTemplate(
                    metadata={"schedule_id": "different-schedule"},
                ),
            )


class TestGlobalConfig:
    """Tests for GlobalConfig validation."""

    def test_create_valid_config(self):
        """Test creating valid GlobalConfig."""
        config = GlobalConfig()
        assert config.fuzzy_match_threshold == 0.80
        assert config.default_date_window_days == 3

    def test_fuzzy_match_threshold_bounds(self):
        """Test that fuzzy_match_threshold must be between 0.0 and 1.0."""
        # Valid boundaries
        GlobalConfig(fuzzy_match_threshold=0.0)
        GlobalConfig(fuzzy_match_threshold=1.0)
        GlobalConfig(fuzzy_match_threshold=0.5)

    def test_fuzzy_match_threshold_too_low(self):
        """Test that fuzzy_match_threshold < 0.0 is rejected."""
        with pytest.raises(ValueError, match="fuzzy_match_threshold must be between"):
            GlobalConfig(fuzzy_match_threshold=-0.1)

    def test_fuzzy_match_threshold_too_high(self):
        """Test that fuzzy_match_threshold > 1.0 is rejected."""
        with pytest.raises(ValueError, match="fuzzy_match_threshold must be between"):
            GlobalConfig(fuzzy_match_threshold=1.1)

    def test_custom_placeholder_flag(self):
        """Test setting custom placeholder flag."""
        config = GlobalConfig(placeholder_flag="*")
        assert config.placeholder_flag == "*"


class TestMissingTransactionConfig:
    """Tests for MissingTransactionConfig."""

    def test_create_with_defaults(self):
        """Test creating MissingTransactionConfig with defaults."""
        config = MissingTransactionConfig()
        assert config.create_placeholder is True
        assert config.flag == "!"
        assert config.narration_prefix == "[MISSING]"

    def test_customize_all_fields(self):
        """Test customizing all fields."""
        config = MissingTransactionConfig(
            create_placeholder=False,
            flag="*",
            narration_prefix="PENDING",
        )
        assert config.create_placeholder is False
        assert config.flag == "*"
        assert config.narration_prefix == "PENDING"


class TestScheduleFile:
    """Tests for ScheduleFile."""

    def test_create_empty_schedule_file(self):
        """Test creating empty ScheduleFile."""
        schedule_file = ScheduleFile()
        assert len(schedule_file.schedules) == 0
        assert schedule_file.config is not None

    def test_schedule_file_with_schedules(self, sample_schedule):
        """Test ScheduleFile with multiple schedules."""
        schedules = [sample_schedule(id=f"schedule-{i}") for i in range(3)]
        schedule_file = ScheduleFile(schedules=schedules)
        assert len(schedule_file.schedules) == 3
        assert schedule_file.schedules[0].id == "schedule-0"


class TestAmortizationConfig:
    """Tests for AmortizationConfig validation."""

    def test_create_valid_amortization_config(self):
        """Should create valid amortization configuration."""
        from beanschedule.schema import AmortizationConfig

        config = AmortizationConfig(
            principal=Decimal("300000"),
            annual_rate=Decimal("0.0675"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        assert config.principal == Decimal("300000")
        assert config.annual_rate == Decimal("0.0675")
        assert config.term_months == 360
        assert config.start_date == date(2024, 1, 1)
        assert config.extra_principal is None

    def test_amortization_with_extra_principal(self):
        """Should accept extra principal payment."""
        from beanschedule.schema import AmortizationConfig

        config = AmortizationConfig(
            principal=Decimal("300000"),
            annual_rate=Decimal("0.0675"),
            term_months=360,
            start_date=date(2024, 1, 1),
            extra_principal=Decimal("100"),
        )

        assert config.extra_principal == Decimal("100")

    def test_principal_must_be_positive(self):
        """Should reject zero or negative principal."""
        from beanschedule.schema import AmortizationConfig

        with pytest.raises(ValidationError, match="principal must be positive"):
            AmortizationConfig(
                principal=Decimal("0"),
                annual_rate=Decimal("0.06"),
                term_months=360,
                start_date=date(2024, 1, 1),
            )

        with pytest.raises(ValidationError, match="principal must be positive"):
            AmortizationConfig(
                principal=Decimal("-100"),
                annual_rate=Decimal("0.06"),
                term_months=360,
                start_date=date(2024, 1, 1),
            )

    def test_annual_rate_must_be_nonnegative(self):
        """Should reject negative annual rate."""
        from beanschedule.schema import AmortizationConfig

        with pytest.raises(ValidationError, match="annual_rate must be non-negative"):
            AmortizationConfig(
                principal=Decimal("100000"),
                annual_rate=Decimal("-0.01"),
                term_months=360,
                start_date=date(2024, 1, 1),
            )

    def test_term_months_must_be_positive(self):
        """Should reject zero or negative term."""
        from beanschedule.schema import AmortizationConfig

        with pytest.raises(ValidationError, match="term_months must be positive"):
            AmortizationConfig(
                principal=Decimal("100000"),
                annual_rate=Decimal("0.06"),
                term_months=0,
                start_date=date(2024, 1, 1),
            )

    def test_extra_principal_must_be_nonnegative(self):
        """Should reject negative extra principal."""
        from beanschedule.schema import AmortizationConfig

        with pytest.raises(ValidationError, match="extra_principal must be non-negative"):
            AmortizationConfig(
                principal=Decimal("100000"),
                annual_rate=Decimal("0.06"),
                term_months=360,
                start_date=date(2024, 1, 1),
                extra_principal=Decimal("-50"),
            )


class TestPosting:
    """Tests for Posting validation with role field."""

    def test_create_posting_with_valid_role(self):
        """Should accept valid role values."""
        from beanschedule.schema import Posting

        for role in ["principal", "interest", "payment", "escrow"]:
            posting = Posting(
                account="Assets:Checking",
                amount=Decimal("100.00"),
                role=role,
            )
            assert posting.role == role

    def test_create_posting_without_role(self):
        """Should allow posting without role (backward compatibility)."""
        from beanschedule.schema import Posting

        posting = Posting(
            account="Assets:Checking",
            amount=Decimal("100.00"),
        )
        assert posting.role is None

    def test_invalid_role_rejected(self):
        """Should reject invalid role values."""
        from beanschedule.schema import Posting

        with pytest.raises(ValidationError, match="role must be one of"):
            Posting(
                account="Assets:Checking",
                amount=Decimal("100.00"),
                role="invalid_role",
            )
