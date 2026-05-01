"""Pytest configuration and shared fixtures for beanschedule tests."""

from datetime import date
from decimal import Decimal

import pytest
import yaml
from beancount.core import amount, data

from beanschedule.schema import (
    GlobalConfig,
    MatchCriteria,
    MissingTransactionConfig,
    Posting,
    RecurrenceRule,
    Schedule,
    ScheduleFile,
    TransactionTemplate,
)
from beanschedule.types import FlagType

# ============================================================================
# Transaction and Posting Builders
# ============================================================================


def make_posting(
    account: str,
    amount_value: Decimal | None,
    currency: str = "USD",
    **kwargs,
) -> data.Posting:
    """Create a beancount Posting with amount."""
    posting_amount = (
        amount.Amount(amount_value, currency) if amount_value is not None else None
    )
    return data.Posting(
        account=account,
        units=posting_amount,
        cost=kwargs.get("cost"),
        price=kwargs.get("price"),
        flag=kwargs.get("flag"),
        meta=kwargs.get("meta"),
    )


def _build_meta(**kwargs) -> dict:
    """Build beancount transaction metadata from kwargs."""
    meta = data.new_metadata(kwargs.get("filename", "test"), 0)
    for key, value in kwargs.items():
        if key not in ["filename", "narration", "tags", "links", "flag"]:
            meta[key] = value
    return meta


def make_transaction(
    date_: date,
    payee: str,
    account: str,
    amount_value: Decimal | None,
    currency: str = "USD",
    **kwargs,
) -> data.Transaction:
    """Create a beancount Transaction with a single posting."""
    posting = make_posting(account, amount_value, currency)
    return data.Transaction(
        meta=_build_meta(**kwargs),
        date=date_,
        flag=kwargs.get("flag", "*"),
        payee=payee,
        narration=kwargs.get("narration", "Test transaction"),
        tags=frozenset(kwargs.get("tags", frozenset())),
        links=frozenset(kwargs.get("links", frozenset())),
        postings=[posting],
    )


def make_transaction_with_postings(
    date_: date,
    payee: str,
    postings: list[data.Posting],
    **kwargs,
) -> data.Transaction:
    """Create a beancount Transaction with multiple postings."""
    return data.Transaction(
        meta=_build_meta(**kwargs),
        date=date_,
        flag=kwargs.get("flag", "*"),
        payee=payee,
        narration=kwargs.get("narration", "Test transaction"),
        tags=frozenset(kwargs.get("tags", frozenset())),
        links=frozenset(kwargs.get("links", frozenset())),
        postings=postings,
    )


# ============================================================================
# Schedule and Model Builders
# ============================================================================


def make_match_criteria(
    account: str = "Assets:Bank:Checking",
    payee_pattern: str = "Test Payee",
    amount: Decimal = Decimal("-100.00"),
    amount_tolerance: Decimal = Decimal("5.00"),
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    date_window_days: int = 3,
    **kwargs,
) -> MatchCriteria:
    """Create MatchCriteria with sensible defaults."""
    return MatchCriteria(
        account=account,
        payee_pattern=payee_pattern,
        amount=amount,
        amount_tolerance=amount_tolerance,
        amount_min=amount_min,
        amount_max=amount_max,
        date_window_days=date_window_days,
    )


def make_recurrence_rule(
    rrule: str = "FREQ=MONTHLY;BYMONTHDAY=15",
    start_date: date = date(2024, 1, 1),
    end_date: date | None = None,
    **kwargs,
) -> RecurrenceRule:
    """Create RecurrenceRule with an RRULE string."""
    return RecurrenceRule(
        rrule=rrule,
        start_date=start_date,
        end_date=end_date,
    )


def make_posting_template(
    account: str,
    amount: Decimal | None = None,
    metadata: dict | None = None,
    role: str | None = None,
) -> Posting:
    """Create a transaction posting template."""
    return Posting(
        account=account,
        amount=amount,
        metadata=metadata or {},
        role=role,
    )


def make_transaction_template(
    payee: str | None = None,
    narration: str | None = None,
    tags: list[str] | None = None,
    schedule_id: str = "test-schedule",
    postings: list[Posting] | None = None,
    **kwargs,
) -> TransactionTemplate:
    """Create TransactionTemplate with sensible defaults."""
    if tags is None:
        tags = []

    metadata = kwargs.get("metadata", {})
    if "schedule_id" not in metadata:
        metadata["schedule_id"] = schedule_id

    return TransactionTemplate(
        payee=payee,
        narration=narration,
        tags=tags,
        metadata=metadata,
        postings=postings,
    )


def make_schedule(
    id: str = "test-schedule",
    enabled: bool = True,
    rrule: str = "FREQ=MONTHLY;BYMONTHDAY=15",
    account: str = "Assets:Bank:Checking",
    payee_pattern: str = "Test Payee",
    amount: Decimal = Decimal("-100.00"),
    amount_tolerance: Decimal = Decimal("5.00"),
    start_date: date = date(2024, 1, 1),
    create_placeholder: bool = True,
    **kwargs,
) -> Schedule:
    """Create a complete Schedule object with sensible defaults."""
    match_criteria = make_match_criteria(
        account=account,
        payee_pattern=payee_pattern,
        amount=amount,
        amount_tolerance=amount_tolerance,
    )

    recurrence = make_recurrence_rule(
        rrule=rrule,
        start_date=start_date,
    )

    transaction = make_transaction_template(
        payee=kwargs.get("payee", payee_pattern),
        narration=kwargs.get("narration", "Test transaction"),
        schedule_id=id,
        postings=kwargs.get("postings"),
    )

    missing_txn = MissingTransactionConfig(
        create_placeholder=create_placeholder,
        flag="!",
        narration_prefix="[MISSING]",
    )

    return Schedule(
        id=id,
        enabled=enabled,
        match=match_criteria,
        recurrence=recurrence,
        transaction=transaction,
        missing_transaction=missing_txn,
    )


def make_global_config(
    fuzzy_match_threshold: float = 0.80,
    default_date_window_days: int = 3,
    default_amount_tolerance_percent: float = 0.02,
    placeholder_flag: FlagType = "!",
    forecast_months: int = 0,
    min_forecast_date: date | None = None,
    include_past_dates: bool = False,
    **kwargs,
) -> GlobalConfig:
    """Create GlobalConfig with defaults or custom values.

    Note: forecast_months defaults to 0 in tests to avoid generating extra placeholders
    based on the forecast extension. Use forecast_months > 0 to test forecasting behavior.
    """
    return GlobalConfig(
        fuzzy_match_threshold=fuzzy_match_threshold,
        default_date_window_days=default_date_window_days,
        default_amount_tolerance_percent=default_amount_tolerance_percent,
        placeholder_flag=placeholder_flag,
        forecast_months=forecast_months,
        min_forecast_date=min_forecast_date,
        include_past_dates=include_past_dates,
    )


def make_schedule_file(
    schedules: list[Schedule] | None = None,
    config: GlobalConfig | None = None,
) -> ScheduleFile:
    """Create a ScheduleFile with schedules and config."""
    if schedules is None:
        schedules = []
    if config is None:
        config = make_global_config()

    return ScheduleFile(
        version="1.0",
        schedules=schedules,
        config=config,
    )


# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture
def sample_transaction():
    """Fixture providing a transaction builder function."""
    return make_transaction


@pytest.fixture
def sample_schedule():
    """Fixture providing a schedule builder function."""
    return make_schedule


@pytest.fixture
def global_config():
    """Fixture providing default GlobalConfig."""
    return make_global_config()


@pytest.fixture
def global_config_with_past_dates():
    """Fixture providing GlobalConfig with include_past_dates=True."""
    return make_global_config(include_past_dates=True)


@pytest.fixture
def temp_schedule_dir(tmp_path):
    """Fixture providing a temporary directory with test schedule files."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()

    # Create _config.yaml
    config = {
        "fuzzy_match_threshold": 0.80,
        "default_date_window_days": 3,
        "default_amount_tolerance_percent": 0.02,
        "placeholder_flag": "!",
        "forecast_months": 0,
        "min_forecast_date": None,
        "include_past_dates": False,
    }
    with open(schedules_dir / "_config.yaml", "w") as f:
        yaml.dump(config, f)

    return schedules_dir


@pytest.fixture
def temp_schedule_file(tmp_path):
    """Fixture providing a temporary schedule YAML file."""
    schedule_file = tmp_path / "schedules.yaml"
    return schedule_file


@pytest.fixture
def sample_schedule_dict(tmp_path):
    """Fixture providing a sample schedule as a dictionary."""
    return {
        "id": "test-schedule",
        "enabled": True,
        "match": {
            "account": "Assets:Bank:Checking",
            "payee_pattern": "Test Payee",
            "amount": -100.00,
            "amount_tolerance": 5.00,
            "amount_min": None,
            "amount_max": None,
            "date_window_days": 3,
        },
        "recurrence": {
            "rrule": "FREQ=MONTHLY;BYMONTHDAY=15",
            "start_date": "2024-01-01",
            "end_date": None,
        },
        "transaction": {
            "payee": "Test Payee",
            "narration": "Test transaction",
            "tags": [],
            "metadata": {
                "schedule_id": "test-schedule",
            },
            "postings": None,
        },
        "missing_transaction": {
            "create_placeholder": True,
            "flag": "!",
            "narration_prefix": "[MISSING]",
        },
    }


# ============================================================================
# Helper Assertion Functions
# ============================================================================


def assert_transaction_enriched(txn: data.Transaction, expected_schedule_id: str):
    """Assert that a transaction has been enriched with schedule metadata."""
    assert "schedule_id" in txn.meta, "Missing schedule_id in metadata"
    assert txn.meta["schedule_id"] == expected_schedule_id
    assert "schedule_matched_date" in txn.meta, (
        "Missing schedule_matched_date in metadata"
    )
    assert "schedule_confidence" in txn.meta, "Missing schedule_confidence in metadata"


def assert_transaction_is_placeholder(txn: data.Transaction):
    """Assert that a transaction is a placeholder (created for missing transaction)."""
    assert txn.flag == "!", "Placeholder should have ! flag"
    assert txn.meta.get("schedule_placeholder") == "true"
    assert "schedule_id" in txn.meta
    assert "schedule_expected_date" in txn.meta


def assert_posting_amounts(txn: data.Transaction, expected_amounts: dict[str, Decimal]):
    """Assert that transaction postings match expected amounts."""
    posting_amounts = {p.account: p.units.number for p in txn.postings if p.units}
    for account, expected_amount in expected_amounts.items():
        assert account in posting_amounts, f"Missing posting for account {account}"
        assert posting_amounts[account] == expected_amount, (
            f"Amount mismatch for {account}: expected {expected_amount}, got {posting_amounts[account]}"
        )
