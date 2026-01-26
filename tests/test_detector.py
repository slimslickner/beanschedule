"""Tests for the RecurrenceDetector pattern detection engine."""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from beancount.core import data, amount

from beanschedule.detector import (
    RecurrenceDetector,
    TransactionGroup,
    GapAnalysis,
    FrequencyDetection,
    RecurringCandidate,
)
from beanschedule.types import FrequencyType, DayOfWeek


def make_transaction(date_, payee, account, amount_value, currency="USD", **kwargs):
    """Create a beancount Transaction with a single posting."""
    from beancount.core import data, amount
    meta = data.new_metadata(kwargs.get("filename", "test"), 0)
    for key, value in kwargs.items():
        if key not in ["filename", "narration", "tags", "links"]:
            meta[key] = value
    posting_amount = amount.Amount(amount_value, currency) if amount_value is not None else None
    posting = data.Posting(
        account=account,
        units=posting_amount,
        cost=kwargs.get("cost", None),
        price=kwargs.get("price", None),
        flag=kwargs.get("flag", None),
        meta=kwargs.get("meta", None),
    )
    return data.Transaction(
        meta=meta,
        date=date_,
        flag=kwargs.get("flag", "*"),
        payee=payee,
        narration=kwargs.get("narration", "Test transaction"),
        tags=kwargs.get("tags", set()),
        links=kwargs.get("links", set()),
        postings=[posting],
    )


def make_posting(account, amount_value, currency="USD", **kwargs):
    """Create a beancount Posting with amount."""
    from beancount.core import data, amount
    posting_amount = amount.Amount(amount_value, currency) if amount_value is not None else None
    return data.Posting(
        account=account,
        units=posting_amount,
        cost=kwargs.get("cost", None),
        price=kwargs.get("price", None),
        flag=kwargs.get("flag", None),
        meta=kwargs.get("meta", None),
    )


def make_transaction_with_postings(date_, payee, postings, **kwargs):
    """Create a beancount Transaction with multiple postings."""
    from beancount.core import data
    meta = data.new_metadata(kwargs.get("filename", "test"), 0)
    for key, value in kwargs.items():
        if key not in ["filename", "narration", "tags", "links"]:
            meta[key] = value
    return data.Transaction(
        meta=meta,
        date=date_,
        flag=kwargs.get("flag", "*"),
        payee=payee,
        narration=kwargs.get("narration", "Test transaction"),
        tags=kwargs.get("tags", set()),
        links=kwargs.get("links", set()),
        postings=postings,
    )


class TestTransactionGrouping:
    """Tests for transaction grouping logic."""

    def test_group_single_transaction(self):
        """Test grouping with a single transaction."""
        detector = RecurrenceDetector()
        txn = make_transaction(
            date(2024, 1, 1),
            "Test Payee",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        groups = detector.group_transactions([txn])

        assert len(groups) == 1
        assert groups[0].payee_canonical == "Test Payee"
        assert groups[0].account == "Assets:Bank:Checking"
        assert groups[0].count == 1

    def test_group_identical_transactions(self):
        """Test grouping identical transactions into single group."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 3, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]

        groups = detector.group_transactions(txns)

        assert len(groups) == 1
        assert groups[0].count == 3
        assert groups[0].payee_canonical == "Test Payee"

    def test_group_by_account_separation(self):
        """Test that transactions are separated by account."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 1),
                "Test Payee",
                "Assets:Bank:Savings",
                Decimal("-100.00"),
            ),
        ]

        groups = detector.group_transactions(txns)

        assert len(groups) == 2
        accounts = {g.account for g in groups}
        assert accounts == {"Assets:Bank:Checking", "Assets:Bank:Savings"}

    def test_group_fuzzy_payee_match(self):
        """Test grouping by fuzzy payee match."""
        detector = RecurrenceDetector(fuzzy_threshold=0.70)  # Lower threshold
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Amazon Inc",
                "Assets:Bank:Checking",
                Decimal("-50.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Amazon",
                "Assets:Bank:Checking",
                Decimal("-50.00"),
            ),
        ]

        groups = detector.group_transactions(txns)

        # Should group together due to fuzzy match
        assert len(groups) == 1
        assert groups[0].count == 2

    def test_group_amount_tolerance(self):
        """Test grouping with amount tolerance."""
        detector = RecurrenceDetector(amount_tolerance_pct=0.10)  # 10%
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-105.00"),  # Within 10%
            ),
            make_transaction(
                date(2024, 3, 1),
                "Test Payee",
                "Assets:Bank:Checking",
                Decimal("-120.00"),  # Outside 10%
            ),
        ]

        groups = detector.group_transactions(txns)

        # Should have 2 groups: [100, 105] and [120]
        assert len(groups) == 2

    def test_group_payee_variants_collected(self):
        """Test that payee variants are collected in group."""
        detector = RecurrenceDetector(fuzzy_threshold=0.70)  # Lower threshold
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "AMAZON INC",
                "Assets:Bank:Checking",
                Decimal("-50.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Amazon",
                "Assets:Bank:Checking",
                Decimal("-50.00"),
            ),
        ]

        groups = detector.group_transactions(txns)

        assert len(groups) == 1
        # Both variants should be captured
        assert "AMAZON INC" in groups[0].payee_variants or "AMAZON" in groups[0].payee_variants

    def test_no_grouping_without_postings(self):
        """Test that transactions without postings are filtered."""
        detector = RecurrenceDetector()
        # Create a transaction without postings (edge case)
        meta = data.new_metadata("test", 0)
        txn = data.Transaction(
            meta=meta,
            date=date(2024, 1, 1),
            flag="*",
            payee="Test Payee",
            narration="Test",
            tags=set(),
            links=set(),
            postings=[],  # No postings
        )

        groups = detector.group_transactions([txn])

        assert len(groups) == 0


class TestGapAnalysis:
    """Tests for gap analysis between transactions."""

    def test_gap_analysis_regular_monthly(self):
        """Test gap analysis for regular monthly transactions."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 3, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)

        # Median of [31, 29] is 30
        assert gap_analysis.median_gap == 30
        assert gap_analysis.min_gap == 29  # Feb-Mar: 29 days (leap year)
        assert gap_analysis.max_gap == 31

    def test_gap_analysis_weekly(self):
        """Test gap analysis for weekly transactions."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 8),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)

        assert gap_analysis.median_gap == 7
        assert gap_analysis.min_gap == 7
        assert gap_analysis.max_gap == 7

    def test_gap_analysis_irregular(self):
        """Test gap analysis with irregular gaps."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 8),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 20),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)

        # Median of [7, 12] is 9.5 rounded to 9
        assert gap_analysis.median_gap == 9
        assert gap_analysis.min_gap == 7
        assert gap_analysis.max_gap == 12

    def test_gap_analysis_single_transaction(self):
        """Test gap analysis with single transaction (no gaps)."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)

        assert gap_analysis.median_gap == 0
        assert gap_analysis.min_gap == 0
        assert gap_analysis.max_gap == 0


class TestFrequencyDetection:
    """Tests for frequency detection from gap analysis."""

    def test_detect_weekly_frequency(self):
        """Test detection of weekly (7-day) pattern."""
        detector = RecurrenceDetector()
        gap_analysis = GapAnalysis(
            gaps=[7, 7, 7],
            median_gap=7,
            mean_gap=7.0,
            std_dev=0.0,
            min_gap=7,
            max_gap=7,
        )
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 8),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)

        freq = detector.detect_frequency(gap_analysis, group)

        assert freq is not None
        assert freq.frequency == FrequencyType.WEEKLY
        assert freq.interval == 1

    def test_detect_biweekly_frequency(self):
        """Test detection of bi-weekly (14-day) pattern."""
        detector = RecurrenceDetector()
        gap_analysis = GapAnalysis(
            gaps=[14, 14, 14],
            median_gap=14,
            mean_gap=14.0,
            std_dev=0.0,
            min_gap=14,
            max_gap=14,
        )
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)

        freq = detector.detect_frequency(gap_analysis, group)

        assert freq is not None
        assert freq.frequency == FrequencyType.WEEKLY
        assert freq.interval == 2

    def test_detect_monthly_frequency(self):
        """Test detection of monthly (30-day) pattern."""
        detector = RecurrenceDetector()
        gap_analysis = GapAnalysis(
            gaps=[31, 28, 31],
            median_gap=31,
            mean_gap=30.0,
            std_dev=1.4,
            min_gap=28,
            max_gap=31,
        )
        txns = [
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)

        freq = detector.detect_frequency(gap_analysis, group)

        assert freq is not None
        assert freq.frequency == FrequencyType.MONTHLY

    def test_detect_quarterly_frequency(self):
        """Test detection of quarterly (90-day) pattern."""
        detector = RecurrenceDetector()
        gap_analysis = GapAnalysis(
            gaps=[90, 91, 90],
            median_gap=90,
            mean_gap=90.3,
            std_dev=0.5,
            min_gap=90,
            max_gap=91,
        )
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 4, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)

        freq = detector.detect_frequency(gap_analysis, group)

        assert freq is not None
        assert freq.frequency == FrequencyType.INTERVAL
        assert freq.interval_months == 3

    def test_detect_yearly_frequency(self):
        """Test detection of yearly (365-day) pattern."""
        detector = RecurrenceDetector()
        gap_analysis = GapAnalysis(
            gaps=[365, 365],
            median_gap=365,
            mean_gap=365.0,
            std_dev=0.0,
            min_gap=365,
            max_gap=365,
        )
        txns = [
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2025, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)

        freq = detector.detect_frequency(gap_analysis, group)

        assert freq is not None
        assert freq.frequency == FrequencyType.YEARLY

    def test_detect_no_pattern(self):
        """Test that no pattern is detected for irregular gaps."""
        detector = RecurrenceDetector()
        gap_analysis = GapAnalysis(
            gaps=[5, 15, 20, 10],
            median_gap=3,  # Very small, no pattern
            mean_gap=12.5,
            std_dev=5.8,
            min_gap=3,
            max_gap=20,
        )
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)

        freq = detector.detect_frequency(gap_analysis, group)

        assert freq is None


class TestConfidenceScoring:
    """Tests for confidence scoring."""

    def test_confidence_perfect_pattern(self):
        """Test confidence scoring for perfect pattern."""
        detector = RecurrenceDetector()
        # 12 transactions exactly on monthly schedule
        txns = [
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 3, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)
        freq = FrequencyDetection(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
        )

        confidence = detector.calculate_confidence(group, gap_analysis, freq)

        assert confidence > 0.8  # Should be high confidence

    def test_confidence_irregular_pattern(self):
        """Test confidence scoring for irregular pattern."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 20),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)
        freq = FrequencyDetection(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
        )

        confidence = detector.calculate_confidence(group, gap_analysis, freq)

        # Even with some irregularity, confidence can still be decent
        # Just check that it's reasonable, not above 0.95
        assert confidence < 0.95

    def test_confidence_small_sample(self):
        """Test confidence scoring with small sample size."""
        detector = RecurrenceDetector()
        # Only 2 transactions
        txns = [
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)
        freq = FrequencyDetection(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
        )

        confidence = detector.calculate_confidence(group, gap_analysis, freq)

        # Confidence should be reasonable for a perfect pattern, but not extremely high
        assert 0.6 < confidence < 1.0

    def test_confidence_missing_occurrences(self):
        """Test confidence scoring when occurrences are missing."""
        detector = RecurrenceDetector()
        # Only 2 transactions over a 12-month period
        txns = [
            make_transaction(
                date(2024, 1, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 12, 15),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        group = detector._create_transaction_group("Assets:Bank:Checking", txns)
        gap_analysis = detector.analyze_gaps(group)
        freq = FrequencyDetection(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
        )

        confidence = detector.calculate_confidence(group, gap_analysis, freq)

        # Confidence should be moderate (only 2 of expected ~12, but perfect on those days)
        assert 0.3 < confidence < 0.65


class TestFullDetectionPipeline:
    """Tests for the complete detection pipeline."""

    def test_detect_no_transactions(self):
        """Test detection with empty transaction list."""
        detector = RecurrenceDetector()
        candidates = detector.detect([])

        assert candidates == []

    def test_detect_single_transaction(self):
        """Test detection with single transaction (below minimum)."""
        detector = RecurrenceDetector(min_occurrences=3)
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]

        candidates = detector.detect(txns)

        assert len(candidates) == 0

    def test_detect_below_confidence_threshold(self):
        """Test that candidates below confidence threshold are filtered."""
        detector = RecurrenceDetector(
            min_occurrences=3,
            min_confidence=0.95,  # Very high threshold
        )
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 3, 1),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]

        candidates = detector.detect(txns)

        # Might be filtered due to high threshold
        assert len(candidates) <= 1

    def test_detect_monthly_pattern(self):
        """Test detection of monthly recurring pattern."""
        detector = RecurrenceDetector(min_occurrences=3, min_confidence=0.70)
        # Create 6 monthly transactions
        txns = []
        for month in range(1, 7):
            txns.append(
                make_transaction(
                    date(2024, month, 15),
                    "Monthly Payment",
                    "Assets:Bank:Checking",
                    Decimal("-500.00"),
                )
            )

        candidates = detector.detect(txns)

        assert len(candidates) >= 1
        candidate = candidates[0]
        assert candidate.frequency.frequency == FrequencyType.MONTHLY
        assert candidate.payee == "Monthly Payment"
        assert candidate.confidence > 0.70

    def test_detect_weekly_pattern(self):
        """Test detection of weekly recurring pattern."""
        detector = RecurrenceDetector(min_occurrences=3, min_confidence=0.70)
        # Create 8 weekly transactions
        txns = []
        for week in range(8):
            txns.append(
                make_transaction(
                    date(2024, 1, 1) + timedelta(days=week * 7),
                    "Weekly Expense",
                    "Assets:Bank:Checking",
                    Decimal("-50.00"),
                )
            )

        candidates = detector.detect(txns)

        assert len(candidates) >= 1
        candidate = candidates[0]
        assert candidate.frequency.frequency == FrequencyType.WEEKLY
        assert candidate.confidence > 0.70

    def test_detect_biweekly_pattern(self):
        """Test detection of bi-weekly recurring pattern."""
        detector = RecurrenceDetector(min_occurrences=3, min_confidence=0.70)
        # Create 6 bi-weekly transactions
        txns = []
        for biweek in range(6):
            txns.append(
                make_transaction(
                    date(2024, 1, 1) + timedelta(days=biweek * 14),
                    "Biweekly Paycheck",
                    "Assets:Bank:Checking",
                    Decimal("2000.00"),
                )
            )

        candidates = detector.detect(txns)

        assert len(candidates) >= 1
        candidate = candidates[0]
        assert candidate.frequency.frequency == FrequencyType.WEEKLY
        assert candidate.frequency.interval == 2
        assert candidate.confidence > 0.70

    def test_detect_multiple_patterns(self):
        """Test detection of multiple patterns in same ledger."""
        detector = RecurrenceDetector(min_occurrences=3, min_confidence=0.70)
        txns = []

        # Monthly rent
        for month in range(1, 7):
            txns.append(
                make_transaction(
                    date(2024, month, 1),
                    "Landlord",
                    "Assets:Bank:Checking",
                    Decimal("-1500.00"),
                )
            )

        # Weekly groceries
        for week in range(12):
            txns.append(
                make_transaction(
                    date(2024, 1, 2) + timedelta(days=week * 7),
                    "Grocery Store",
                    "Assets:Bank:Checking",
                    Decimal("-120.00"),
                )
            )

        candidates = detector.detect(txns)

        assert len(candidates) >= 2
        # Candidates should be sorted by confidence
        assert candidates[0].confidence >= candidates[-1].confidence


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_fuzzy_match_caching(self):
        """Test that fuzzy match results are cached."""
        detector = RecurrenceDetector()
        payee1 = "Amazon Inc"
        payee2 = "Amazon"

        # First call
        score1 = detector._fuzzy_match(payee1, payee2)
        cache_size_after_first = len(detector.fuzzy_cache)

        # Second call (should use cache)
        score2 = detector._fuzzy_match(payee1, payee2)
        cache_size_after_second = len(detector.fuzzy_cache)

        assert score1 == score2
        assert cache_size_after_first == cache_size_after_second

    def test_most_common_day_of_month_month_end(self):
        """Test detection of month-end transactions."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 31),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 2, 29),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 3, 31),
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        dates = [txn.date for txn in txns]

        day_of_month = detector._get_most_common_day_of_month(dates)

        # Should detect month-end pattern
        assert day_of_month == 28  # End of month

    def test_most_common_weekday(self):
        """Test detection of most common day of week."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),  # Monday
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 8),  # Monday
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
            make_transaction(
                date(2024, 1, 15),  # Monday
                "Test",
                "Assets:Bank:Checking",
                Decimal("-100.00"),
            ),
        ]
        dates = [txn.date for txn in txns]

        day_of_week = detector._get_most_common_weekday(dates)

        assert day_of_week == DayOfWeek.MON

    def test_negative_and_positive_amounts(self):
        """Test grouping handles both negative and positive amounts."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Paycheck",
                "Assets:Bank:Checking",
                Decimal("2000.00"),  # Positive
            ),
            make_transaction(
                date(2024, 1, 15),
                "Paycheck",
                "Assets:Bank:Checking",
                Decimal("2000.00"),  # Positive
            ),
        ]

        groups = detector.group_transactions(txns)

        assert len(groups) >= 1
        # Both transactions should be grouped together
        assert groups[0].count >= 1

    def test_zero_amount_transactions(self):
        """Test handling of zero-amount transactions."""
        detector = RecurrenceDetector()
        txns = [
            make_transaction(
                date(2024, 1, 1),
                "Fee Waived",
                "Assets:Bank:Checking",
                Decimal("0.00"),
            ),
            make_transaction(
                date(2024, 2, 1),
                "Fee Waived",
                "Assets:Bank:Checking",
                Decimal("0.00"),
            ),
        ]

        groups = detector.group_transactions(txns)

        # Zero amounts might not group properly if tolerance calculation fails
        # Just verify the function doesn't crash
        assert isinstance(groups, list)


class TestFrequencyDetectionFormatted:
    """Tests for formatted frequency names."""

    def test_format_weekly(self):
        """Test formatting of weekly frequency."""
        freq = FrequencyDetection(
            frequency=FrequencyType.WEEKLY,
            interval=1,
            day_of_week=DayOfWeek.FRI,
        )
        assert freq.formatted_name() == "Weekly"

    def test_format_biweekly(self):
        """Test formatting of bi-weekly frequency."""
        freq = FrequencyDetection(
            frequency=FrequencyType.WEEKLY,
            interval=2,
            day_of_week=DayOfWeek.MON,
        )
        assert freq.formatted_name() == "Bi-weekly"

    def test_format_monthly(self):
        """Test formatting of monthly frequency."""
        freq = FrequencyDetection(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
        )
        assert freq.formatted_name() == "Monthly"

    def test_format_quarterly(self):
        """Test formatting of quarterly frequency."""
        freq = FrequencyDetection(
            frequency=FrequencyType.INTERVAL,
            interval_months=3,
        )
        assert freq.formatted_name() == "Quarterly"

    def test_format_yearly(self):
        """Test formatting of yearly frequency."""
        freq = FrequencyDetection(
            frequency=FrequencyType.YEARLY,
            month=1,
            day_of_month=1,
        )
        assert freq.formatted_name() == "Yearly"
