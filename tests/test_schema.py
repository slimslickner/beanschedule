"""Tests for schema validation using Pydantic models."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from beanschedule.schema import (
    AmortizationConfig,
    AmortizationOverride,
    GlobalConfig,
    MatchCriteria,
    MissingTransactionConfig,
    Posting,
    RecurrenceRule,
    Schedule,
    ScheduleFile,
    TransactionTemplate,
)


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

    def test_amount_tolerance_must_be_nonnegative(self):
        """Test that negative amount_tolerance is rejected."""
        with pytest.raises(ValueError, match="amount_tolerance must be non-negative"):
            MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
                amount_tolerance=Decimal("-5.00"),
            )

    def test_date_window_days_must_be_nonnegative(self):
        """Test that negative date_window_days is rejected."""
        with pytest.raises(ValueError, match="date_window_days must be non-negative"):
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

    def test_amount_tolerance_requires_amount(self):
        """Test that amount_tolerance without amount is rejected."""
        with pytest.raises(ValueError, match="amount_tolerance requires amount"):
            MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
                amount=None,
                amount_tolerance=Decimal("5.00"),
            )

    def test_amount_and_range_are_mutually_exclusive(self):
        """Test that amount and amount_min/max cannot both be set."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
                amount=Decimal("-100.00"),
                amount_min=Decimal("-110.00"),
                amount_max=Decimal("-90.00"),
            )

    def test_range_requires_both_min_and_max(self):
        """Test that amount_min without amount_max is rejected."""
        with pytest.raises(ValueError, match="both be set"):
            MatchCriteria(
                account="Assets:Bank:Checking",
                payee_pattern="Test",
                amount_min=Decimal("-110.00"),
            )

    def test_amount_with_tolerance_is_valid(self):
        """Test that amount + amount_tolerance is valid."""
        criteria = MatchCriteria(
            account="Assets:Bank:Checking",
            payee_pattern="Test",
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("50.00"),
        )
        assert criteria.amount == Decimal("-1500.00")
        assert criteria.amount_tolerance == Decimal("50.00")

    def test_range_without_amount_is_valid(self):
        """Test that amount_min + amount_max without amount is valid."""
        criteria = MatchCriteria(
            account="Assets:Bank:Checking",
            payee_pattern="Test",
            amount_min=Decimal("-110.00"),
            amount_max=Decimal("-90.00"),
        )
        assert criteria.amount_min == Decimal("-110.00")
        assert criteria.amount_max == Decimal("-90.00")


class TestRecurrenceRule:
    """Tests for RecurrenceRule validation."""

    def test_create_monthly_rrule(self):
        rule = RecurrenceRule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        assert rule.rrule == "FREQ=MONTHLY;BYMONTHDAY=15"
        assert rule.start_date == date(2024, 1, 1)
        assert rule.end_date is None

    def test_rrule_stored_uppercase(self):
        rule = RecurrenceRule(
            rrule="freq=monthly;bymonthday=15", start_date=date(2024, 1, 1)
        )
        assert rule.rrule == "FREQ=MONTHLY;BYMONTHDAY=15"

    def test_invalid_rrule_rejected(self):
        with pytest.raises(ValueError, match="Invalid RRULE"):
            RecurrenceRule(rrule="NOT_VALID_RRULE", start_date=date(2024, 1, 1))

    def test_invalid_bymonthday_rejected(self):
        with pytest.raises(ValueError, match="Invalid RRULE"):
            RecurrenceRule(
                rrule="FREQ=MONTHLY;BYMONTHDAY=", start_date=date(2024, 1, 1)
            )

    def test_end_date_stored(self):
        rule = RecurrenceRule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert rule.end_date == date(2024, 12, 31)

    def test_legacy_monthly_migration(self):
        """Old-format YAML with frequency/day_of_month migrates to rrule."""
        rule = RecurrenceRule.model_validate(
            {"frequency": "MONTHLY", "start_date": date(2024, 1, 1), "day_of_month": 15}
        )
        assert rule.rrule == "FREQ=MONTHLY;BYMONTHDAY=15"

    def test_legacy_weekly_migration(self):
        rule = RecurrenceRule.model_validate(
            {
                "frequency": "WEEKLY",
                "start_date": date(2024, 1, 1),
                "day_of_week": "MON",
                "interval": 2,
            }
        )
        assert rule.rrule == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"

    def test_legacy_yearly_migration(self):
        rule = RecurrenceRule.model_validate(
            {
                "frequency": "YEARLY",
                "start_date": date(2024, 1, 1),
                "month": 3,
                "day_of_month": 15,
            }
        )
        assert rule.rrule == "FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=15"

    def test_legacy_interval_migration(self):
        rule = RecurrenceRule.model_validate(
            {
                "frequency": "INTERVAL",
                "start_date": date(2024, 1, 1),
                "interval_months": 3,
                "day_of_month": 15,
            }
        )
        assert rule.rrule == "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15"

    def test_legacy_bimonthly_migration(self):
        rule = RecurrenceRule.model_validate(
            {
                "frequency": "BIMONTHLY",
                "start_date": date(2024, 1, 1),
                "days_of_month": [5, 20],
            }
        )
        assert rule.rrule == "FREQ=MONTHLY;BYMONTHDAY=5,20"

    def test_legacy_last_day_migration(self):
        rule = RecurrenceRule.model_validate(
            {"frequency": "LAST_DAY_OF_MONTH", "start_date": date(2024, 1, 1)}
        )
        assert rule.rrule == "FREQ=MONTHLY;BYMONTHDAY=-1"


class TestTransactionTemplate:
    """Tests for TransactionTemplate validation."""

    def test_metadata_requires_schedule_id(self):
        """Test that metadata must contain schedule_id."""
        with pytest.raises(
            ValueError, match="metadata must contain 'schedule_id' field"
        ):
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
        with pytest.raises(
            ValueError, match="metadata must contain 'schedule_id' field"
        ):
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
                    rrule="FREQ=MONTHLY;BYMONTHDAY=15",
                    start_date=date(2024, 1, 1),
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
                rrule="FREQ=MONTHLY;BYMONTHDAY=15",
                start_date=date(2024, 1, 1),
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
                    rrule="FREQ=MONTHLY;BYMONTHDAY=15",
                    start_date=date(2024, 1, 1),
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

    def test_forecast_months_defaults_to_3(self):
        """Test that forecast_months defaults to 3."""
        config = GlobalConfig()
        assert config.forecast_months == 3

    def test_forecast_months_custom_value(self):
        """Test setting custom forecast_months."""
        config = GlobalConfig(forecast_months=6)
        assert config.forecast_months == 6

    def test_forecast_months_zero(self):
        """Test that forecast_months can be set to 0 to disable forecasting."""
        config = GlobalConfig(forecast_months=0)
        assert config.forecast_months == 0

    def test_forecast_months_negative_rejected(self):
        """Test that negative forecast_months is rejected."""
        with pytest.raises(ValueError, match="forecast_months must be non-negative"):
            GlobalConfig(forecast_months=-1)

    def test_min_forecast_date_defaults_to_none(self):
        """Test that min_forecast_date defaults to None."""
        config = GlobalConfig()
        assert config.min_forecast_date is None

    def test_min_forecast_date_custom_value(self):
        """Test setting custom min_forecast_date."""
        test_date = date(2026, 1, 1)
        config = GlobalConfig(min_forecast_date=test_date)
        assert config.min_forecast_date == test_date

    def test_include_past_dates_defaults_to_true(self):
        """Test that include_past_dates defaults to True."""
        config = GlobalConfig()
        assert config.include_past_dates is True

    def test_include_past_dates_true(self):
        """Test setting include_past_dates to True."""
        config = GlobalConfig(include_past_dates=True)
        assert config.include_past_dates is True

    def test_forecast_config_combined(self):
        """Test setting all forecast-related config values together."""
        config = GlobalConfig(
            forecast_months=12,
            min_forecast_date=date(2025, 1, 1),
            include_past_dates=True,
        )
        assert config.forecast_months == 12
        assert config.min_forecast_date == date(2025, 1, 1)
        assert config.include_past_dates is True


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

        with pytest.raises(ValidationError, match="annual_rate must be non-negative"):
            AmortizationConfig(
                principal=Decimal("100000"),
                annual_rate=Decimal("-0.01"),
                term_months=360,
                start_date=date(2024, 1, 1),
            )

    def test_term_months_must_be_positive(self):
        """Should reject zero or negative term."""

        with pytest.raises(ValidationError, match="term_months must be positive"):
            AmortizationConfig(
                principal=Decimal("100000"),
                annual_rate=Decimal("0.06"),
                term_months=0,
                start_date=date(2024, 1, 1),
            )

    def test_extra_principal_must_be_nonnegative(self):
        """Should reject negative extra principal."""

        with pytest.raises(
            ValidationError, match="extra_principal must be non-negative"
        ):
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

        for role in ["principal", "interest", "payment", "escrow"]:
            posting = Posting(
                account="Assets:Checking",
                amount=Decimal("100.00"),
                role=role,
            )
            assert posting.role == role

    def test_create_posting_without_role(self):
        """Should allow posting without role (backward compatibility)."""

        posting = Posting(
            account="Assets:Checking",
            amount=Decimal("100.00"),
        )
        assert posting.role is None

    def test_invalid_role_rejected(self):
        """Should reject invalid role values."""

        with pytest.raises(ValidationError, match="role must be one of"):
            Posting(
                account="Assets:Checking",
                amount=Decimal("100.00"),
                role="invalid_role",
            )


class TestAmortizationOverride:
    """Tests for AmortizationOverride validation."""

    def test_create_valid_override(self):
        """Should create valid override with all fields."""
        from beanschedule.schema import AmortizationOverride

        override = AmortizationOverride(
            effective_date=date(2029, 1, 1),
            principal=Decimal("285000"),
            annual_rate=Decimal("0.05"),
            term_months=300,
            extra_principal=Decimal("500"),
        )
        assert override.effective_date == date(2029, 1, 1)
        assert override.principal == Decimal("285000")
        assert override.annual_rate == Decimal("0.05")
        assert override.term_months == 300
        assert override.extra_principal == Decimal("500")

    def test_create_partial_override(self):
        """Should allow overriding only some fields."""
        from beanschedule.schema import AmortizationOverride

        # Only override extra_principal
        override = AmortizationOverride(
            effective_date=date(2029, 1, 1),
            extra_principal=Decimal("500"),
        )
        assert override.effective_date == date(2029, 1, 1)
        assert override.extra_principal == Decimal("500")
        assert override.principal is None
        assert override.annual_rate is None

    def test_override_principal_must_be_positive(self):
        """Should reject zero or negative principal."""
        from beanschedule.schema import AmortizationOverride

        with pytest.raises(ValidationError, match="principal must be positive"):
            AmortizationOverride(
                effective_date=date(2029, 1, 1),
                principal=Decimal("0"),
            )

    def test_override_rate_must_be_nonnegative(self):
        """Should reject negative rate."""
        from beanschedule.schema import AmortizationOverride

        with pytest.raises(ValidationError, match="annual_rate must be non-negative"):
            AmortizationOverride(
                effective_date=date(2029, 1, 1),
                annual_rate=Decimal("-0.01"),
            )

    def test_override_term_must_be_positive(self):
        """Should reject zero or negative term."""
        from beanschedule.schema import AmortizationOverride

        with pytest.raises(ValidationError, match="term_months must be positive"):
            AmortizationOverride(
                effective_date=date(2029, 1, 1),
                term_months=0,
            )

    def test_override_extra_principal_must_be_nonnegative(self):
        """Should reject negative extra principal."""
        from beanschedule.schema import AmortizationOverride

        with pytest.raises(
            ValidationError, match="extra_principal must be non-negative"
        ):
            AmortizationOverride(
                effective_date=date(2029, 1, 1),
                extra_principal=Decimal("-50"),
            )


class TestAmortizationConfigWithOverrides:
    """Tests for AmortizationConfig with overrides."""

    def test_create_amortization_with_overrides(self):
        """Should create config with overrides list."""

        config = AmortizationConfig(
            principal=Decimal("300000"),
            annual_rate=Decimal("0.07"),
            term_months=360,
            start_date=date(2024, 1, 1),
            overrides=[
                AmortizationOverride(
                    effective_date=date(2029, 1, 1),
                    extra_principal=Decimal("500"),
                ),
                AmortizationOverride(
                    effective_date=date(2034, 1, 1),
                    principal=Decimal("200000"),
                    extra_principal=Decimal("1000"),
                ),
            ],
        )
        assert config.overrides is not None
        assert len(config.overrides) == 2
        assert config.overrides[0].effective_date == date(2029, 1, 1)
        assert config.overrides[1].effective_date == date(2034, 1, 1)


class TestStatefulAmortizationConfig:
    """Tests for stateful (balance_from_ledger) mode in AmortizationConfig."""

    def test_stateful_config_valid(self):
        """Should accept valid stateful config with only rate + payment."""
        from beanschedule.types import CompoundingFrequency

        config = AmortizationConfig(
            annual_rate=Decimal("0.04875"),
            balance_from_ledger=True,
            monthly_payment=Decimal("1931.67"),
        )
        assert config.balance_from_ledger is True
        assert config.monthly_payment == Decimal("1931.67")
        assert config.compounding == CompoundingFrequency.MONTHLY
        assert config.principal is None
        assert config.term_months is None
        assert config.start_date is None

    def test_stateful_config_daily_compounding(self):
        """Should accept DAILY compounding in stateful mode."""
        from beanschedule.types import CompoundingFrequency

        config = AmortizationConfig(
            annual_rate=Decimal("0.065"),
            balance_from_ledger=True,
            monthly_payment=Decimal("450.00"),
            compounding=CompoundingFrequency.DAILY,
        )
        assert config.compounding == CompoundingFrequency.DAILY

    def test_stateful_config_with_extra_principal(self):
        """Should accept extra_principal in stateful mode."""

        config = AmortizationConfig(
            annual_rate=Decimal("0.04875"),
            balance_from_ledger=True,
            monthly_payment=Decimal("1931.67"),
            extra_principal=Decimal("500.00"),
        )
        assert config.extra_principal == Decimal("500.00")

    def test_stateful_config_requires_monthly_payment(self):
        """Should reject stateful config when monthly_payment is missing."""

        with pytest.raises(ValidationError, match="monthly_payment is required"):
            AmortizationConfig(
                annual_rate=Decimal("0.05"),
                balance_from_ledger=True,
            )

    def test_monthly_payment_must_be_positive(self):
        """Should reject zero or negative monthly_payment."""

        with pytest.raises(ValidationError, match="monthly_payment must be positive"):
            AmortizationConfig(
                annual_rate=Decimal("0.05"),
                balance_from_ledger=True,
                monthly_payment=Decimal("0"),
            )

    def test_static_config_requires_principal(self):
        """Should reject static config when principal is missing."""

        with pytest.raises(ValidationError, match="principal is required"):
            AmortizationConfig(
                annual_rate=Decimal("0.05"),
                term_months=360,
                start_date=date(2024, 1, 1),
            )

    def test_static_config_requires_term_months(self):
        """Should reject static config when term_months is missing."""

        with pytest.raises(ValidationError, match="term_months is required"):
            AmortizationConfig(
                principal=Decimal("300000"),
                annual_rate=Decimal("0.05"),
                start_date=date(2024, 1, 1),
            )

    def test_static_config_requires_start_date(self):
        """Should reject static config when start_date is missing."""

        with pytest.raises(ValidationError, match="start_date is required"):
            AmortizationConfig(
                principal=Decimal("300000"),
                annual_rate=Decimal("0.05"),
                term_months=360,
            )


class TestPostingCurrency:
    """Tests for per-posting currency field."""

    def test_posting_currency_defaults_to_none(self):
        """Posting.currency is None by default (inherits schedule default)."""
        posting = Posting(account="Expenses:Food")
        assert posting.currency is None

    def test_posting_currency_explicit(self):
        """Posting.currency can be set to a specific currency."""
        posting = Posting(
            account="Income:Vacation", amount=Decimal("8"), currency="VACDAY"
        )
        assert posting.currency == "VACDAY"

    def test_posting_currency_stock(self):
        """Posting.currency works with stock tickers."""
        posting = Posting(
            account="Assets:Vesting", amount=Decimal("10"), currency="TSLA"
        )
        assert posting.currency == "TSLA"

    def test_posting_currency_yaml_round_trip(self):
        """Posting.currency is preserved through dict serialization."""
        posting = Posting(account="Income:RSU", amount=Decimal("5"), currency="AAPL")
        data = posting.model_dump()
        assert data["currency"] == "AAPL"
        restored = Posting(**data)
        assert restored.currency == "AAPL"


class TestGlobalConfigDefaultCurrency:
    """Tests for GlobalConfig.default_currency nullable behaviour."""

    def test_default_currency_is_none_by_default(self):
        """GlobalConfig.default_currency defaults to None (auto-detect)."""
        config = GlobalConfig()
        assert config.default_currency is None

    def test_default_currency_can_be_set_explicitly(self):
        """GlobalConfig.default_currency accepts an explicit currency string."""
        config = GlobalConfig(default_currency="EUR")
        assert config.default_currency == "EUR"

    def test_default_currency_none_in_yaml_round_trip(self):
        """None default_currency round-trips through dict."""
        config = GlobalConfig()
        data = config.model_dump()
        assert data["default_currency"] is None
        restored = GlobalConfig(**data)
        assert restored.default_currency is None
