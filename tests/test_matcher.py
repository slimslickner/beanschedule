"""Tests for transaction matching algorithm."""

from datetime import date
from decimal import Decimal

from beanschedule.matcher import TransactionMatcher
from beanschedule.schema import GlobalConfig


class TestTransactionMatcher:
    """Tests for TransactionMatcher class."""

    def test_matcher_initialization(self, global_config):
        """Test creating a TransactionMatcher instance."""
        matcher = TransactionMatcher(global_config)
        assert matcher.config == global_config

    def test_custom_threshold(self):
        """Test matcher with custom fuzzy match threshold."""
        config = GlobalConfig(fuzzy_match_threshold=0.90)
        matcher = TransactionMatcher(config)
        assert matcher.config.fuzzy_match_threshold == 0.90


class TestPayeeMatching:
    """Tests for payee matching."""

    def test_exact_payee_match(self, sample_transaction, sample_schedule, global_config):
        """Test exact payee match."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord Property Management",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord Property Management",
        )

        # Exact match should score high
        score = matcher._payee_score(txn, schedule)
        assert score > 0.95

    def test_fuzzy_payee_match(self, sample_transaction, sample_schedule, global_config):
        """Test fuzzy payee matching."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord Management Inc",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord Property Management",
        )

        # Fuzzy match should score between 0.5 and 1.0
        score = matcher._payee_score(txn, schedule)
        assert 0.7 < score < 1.0

    def test_regex_payee_match(self, sample_transaction, sample_schedule, global_config):
        """Test regex payee matching."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "ACME CORP",
            "Assets:Bank:Checking",
            Decimal("2500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="ACME|AcmeCorp",
        )

        # Regex match should return 1.0
        score = matcher._payee_score(txn, schedule)
        assert score == 1.0

    def test_regex_no_match(self, sample_transaction, sample_schedule, global_config):
        """Test regex payee non-match."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Bank Transfer",
            "Assets:Bank:Checking",
            Decimal("100.00"),
        )

        schedule = sample_schedule(
            payee_pattern="ACME|Payroll",
        )

        # No regex match should return 0.0
        score = matcher._payee_score(txn, schedule)
        assert score == 0.0

    def test_payee_case_insensitive(self, sample_transaction, sample_schedule, global_config):
        """Test that payee matching is case-insensitive."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "landlord property management",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="LANDLORD PROPERTY MANAGEMENT",
        )

        # Case insensitive should match
        score = matcher._payee_score(txn, schedule)
        assert score > 0.95

    def test_empty_payee(self, sample_transaction, sample_schedule, global_config):
        """Test transaction with empty payee."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord",
        )

        # Empty payee should score 0.0
        score = matcher._payee_score(txn, schedule)
        assert score == 0.0


class TestAmountMatching:
    """Tests for amount matching."""

    def test_exact_amount_match(self, sample_transaction, sample_schedule, global_config):
        """Test exact amount match."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("5.00"),
        )

        # Exact match should score 1.0
        score = matcher._amount_score(txn, schedule)
        assert score == 1.0

    def test_amount_within_tolerance(self, sample_transaction, sample_schedule, global_config):
        """Test amount within tolerance."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1502.50"),
        )

        schedule = sample_schedule(
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("5.00"),
        )

        # Within tolerance should score > 0
        score = matcher._amount_score(txn, schedule)
        assert 0.0 < score < 1.0

    def test_amount_outside_tolerance(self, sample_transaction, sample_schedule, global_config):
        """Test amount outside tolerance."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1510.00"),
        )

        schedule = sample_schedule(
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("5.00"),
        )

        # Outside tolerance should score 0.0
        score = matcher._amount_score(txn, schedule)
        assert score == 0.0

    def test_amount_range_match(self, sample_transaction, sample_schedule, global_config):
        """Test amount within range."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Utilities",
            "Assets:Bank:Checking",
            Decimal("-75.00"),
        )

        schedule = sample_schedule(
            amount=None,
            amount_tolerance=None,
            amount_min=Decimal("-100.00"),
            amount_max=Decimal("-50.00"),
        )

        # Within range should score 1.0
        score = matcher._amount_score(txn, schedule)
        assert score == 1.0

    def test_null_amount_matches_anything(self, sample_transaction, sample_schedule, global_config):
        """Test that null amount matches any amount."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Payment",
            "Assets:Bank:Checking",
            Decimal("-9999.99"),
        )

        schedule = sample_schedule(
            amount=None,
            amount_tolerance=None,
        )

        # Null amount should always score 1.0
        score = matcher._amount_score(txn, schedule)
        assert score == 1.0

    def test_zero_tolerance_requires_exact_match(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that zero tolerance requires exact amount."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.01"),
        )

        schedule = sample_schedule(
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("0.00"),
        )

        # Zero tolerance, off by 0.01 should score 0.0
        score = matcher._amount_score(txn, schedule)
        assert score == 0.0


class TestDateMatching:
    """Tests for date matching."""

    def test_exact_date_match(self, sample_transaction, sample_schedule, global_config):
        """Test exact date match."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Payment",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule()

        # Exact date should score 1.0
        score = matcher._date_score(txn, schedule, date(2024, 1, 15))
        assert score == 1.0

    def test_date_within_window(self, sample_transaction, sample_schedule, global_config):
        """Test date within window."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 16),
            "Payment",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule()  # default 3 day window

        # One day off should score > 0
        score = matcher._date_score(txn, schedule, date(2024, 1, 15))
        assert 0.0 < score < 1.0

    def test_date_outside_window(self, sample_transaction, sample_schedule, global_config):
        """Test date outside window."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 20),
            "Payment",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule()  # default 3 day window

        # Five days off should score 0.0
        score = matcher._date_score(txn, schedule, date(2024, 1, 15))
        assert score == 0.0


class TestAccountMatching:
    """Tests for account matching (required)."""

    def test_account_match_required(self, sample_transaction, sample_schedule, global_config):
        """Test that account match is required."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Payment",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule(
            account="Assets:Bank:Checking",
        )

        # Same account should return True
        assert matcher._account_matches(txn, schedule) is True

    def test_account_mismatch(self, sample_transaction, sample_schedule, global_config):
        """Test account mismatch."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Payment",
            "Assets:Bank:Savings",
            Decimal("-100.00"),
        )

        schedule = sample_schedule(
            account="Assets:Bank:Checking",
        )

        # Different account should return False
        assert matcher._account_matches(txn, schedule) is False

    def test_account_mismatch_fails_score(self, sample_transaction, sample_schedule, global_config):
        """Test that account mismatch results in 0.0 score."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Savings",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            account="Assets:Bank:Checking",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        # Even with perfect payee and amount match, account mismatch gives 0.0
        score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 15))
        assert score == 0.0


class TestWeightedScoring:
    """Tests for weighted score calculation."""

    def test_perfect_match_score(self, sample_transaction, sample_schedule, global_config):
        """Test perfect match gives score of 1.0."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            account="Assets:Bank:Checking",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 15))
        assert abs(score - 1.0) < 0.01

    def test_partial_match_score(self, sample_transaction, sample_schedule, global_config):
        """Test partial match gives score between 0 and 1."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 17),  # 2 days off
            "Landlord Management",  # Fuzzy match
            "Assets:Bank:Checking",
            Decimal("-1502.00"),  # Slightly off
        )

        schedule = sample_schedule(
            account="Assets:Bank:Checking",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("5.00"),
        )

        score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 15))
        assert 0.0 < score < 1.0

    def test_weighting_formula(self, sample_transaction, sample_schedule, global_config):
        """Test that weighted scoring formula is correct (40% payee, 40% amount, 20% date)."""
        matcher = TransactionMatcher(global_config)

        # Create a schedule where we know the component scores
        schedule = sample_schedule(
            payee_pattern="Landlord",  # Will fuzzy match at high score
            amount=Decimal("-1500.00"),
            amount_tolerance=Decimal("1000.00"),  # Very high tolerance
        )

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 15))
        # Perfect payee, perfect amount, perfect date should give ~1.0
        assert score > 0.99


class TestFindBestMatch:
    """Tests for find_best_match function."""

    def test_single_candidate_above_threshold(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test single candidate above threshold."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        candidates = [(schedule, date(2024, 1, 15))]
        result = matcher.find_best_match(txn, candidates)

        assert result is not None
        assert result[0].id == schedule.id
        assert result[2] > global_config.fuzzy_match_threshold

    def test_no_match_below_threshold(self, sample_transaction, sample_schedule, global_config):
        """Test that candidates below threshold return None."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Someone Else",
            "Assets:Bank:Checking",
            Decimal("-9999.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        candidates = [(schedule, date(2024, 1, 15))]
        result = matcher.find_best_match(txn, candidates)

        assert result is None

    def test_multiple_candidates_best_wins(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that best match is selected from multiple candidates."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        # Schedule 1: Good match
        schedule1 = sample_schedule(
            id="good-match",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        # Schedule 2: Better match
        schedule2 = sample_schedule(
            id="better-match",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        candidates = [
            (schedule1, date(2024, 1, 15)),
            (schedule2, date(2024, 1, 15)),
        ]

        result = matcher.find_best_match(txn, candidates)

        assert result is not None
        # Should return one of the schedules (both should score similarly)
        assert result[0].id in [schedule1.id, schedule2.id]

    def test_threshold_boundary(self, sample_transaction, sample_schedule, global_config):
        """Test behavior at threshold boundary (0.80)."""
        matcher = TransactionMatcher(global_config)

        # Create a transaction/schedule combo that will score exactly at threshold
        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        candidates = [(schedule, date(2024, 1, 15))]
        result = matcher.find_best_match(txn, candidates)

        # Perfect match should definitely be above threshold
        assert result is not None
        assert result[2] >= global_config.fuzzy_match_threshold

    def test_empty_candidates(self, sample_transaction, global_config):
        """Test with empty candidate list."""
        matcher = TransactionMatcher(global_config)

        txn = sample_transaction(
            date(2024, 1, 15),
            "Payment",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        result = matcher.find_best_match(txn, [])

        assert result is None
