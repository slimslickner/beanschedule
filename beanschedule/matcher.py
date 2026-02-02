"""Transaction matching algorithm for scheduled transactions."""

import logging
import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from beancount.core import data

from .schema import GlobalConfig, Schedule

logger = logging.getLogger(__name__)


class TransactionMatcher:
    """Matches imported transactions to scheduled transactions."""

    def __init__(self, config: GlobalConfig):
        """
        Initialize matcher with global config.

        Args:
            config: Global configuration with matching thresholds
        """
        self.config = config
        # Cache for compiled regex patterns (pattern -> compiled regex)
        self.compiled_patterns: dict[str, re.Pattern] = {}
        # Cache for fuzzy match results ((payee, pattern) -> score)
        self.fuzzy_cache: dict[tuple[str, str], float] = {}

    def calculate_match_score(
        self,
        transaction: data.Transaction,
        schedule: Schedule,
        expected_date: date,
    ) -> float:
        """
        Calculate match confidence score (0.0 - 1.0).

        Weighted scoring:
        - Account match: Required (fail if mismatch)
        - Payee similarity: 40% (fuzzy or regex match)
        - Amount match: 40% (within tolerance)
        - Date proximity: 20% (within window)

        Args:
            transaction: Imported transaction to match
            schedule: Schedule to match against
            expected_date: Expected occurrence date from recurrence

        Returns:
            Match score from 0.0 to 1.0 (0.0 if required criteria fail)
        """
        # Required: Account must match exactly
        if not self._account_matches(transaction, schedule):
            return 0.0

        # Calculate component scores
        payee_score = self._payee_score(transaction, schedule)
        amount_score = self._amount_score(transaction, schedule)
        date_score = self._date_score(transaction, schedule, expected_date)

        # Weighted combination
        total_score = (payee_score * 0.4) + (amount_score * 0.4) + (date_score * 0.2)

        logger.debug(
            "Match score for %s vs %s: %.2f (payee=%.2f, amount=%.2f, date=%.2f)",
            transaction.payee,
            schedule.id,
            total_score,
            payee_score,
            amount_score,
            date_score,
        )

        return total_score

    def _account_matches(self, transaction: data.Transaction, schedule: Schedule) -> bool:
        """Check if transaction account matches schedule account exactly."""
        if not transaction.postings:
            return False

        # Get main account from first posting
        main_account = transaction.postings[0].account

        return main_account == schedule.match.account

    def _payee_score(self, transaction: data.Transaction, schedule: Schedule) -> float:
        """
        Calculate payee similarity score.

        Uses regex matching if pattern looks like regex,
        otherwise uses fuzzy string matching.

        Returns:
            Score from 0.0 to 1.0
        """
        if not transaction.payee:
            return 0.0

        pattern = schedule.match.payee_pattern

        # Check if pattern looks like regex (contains special chars)
        if self._is_regex_pattern(pattern):
            return self._regex_match(transaction.payee, pattern)
        return self._fuzzy_match(transaction.payee, pattern)

    def _is_regex_pattern(self, pattern: str) -> bool:
        """Detect if pattern is likely a regex."""
        regex_indicators = ["|", ".*", ".+", "\\", "[", "]", "(", ")", "^", "$"]
        return any(indicator in pattern for indicator in regex_indicators)

    def _regex_match(self, payee: str, pattern: str) -> float:
        """
        Match payee against regex pattern using cached compiled patterns.

        Patterns are compiled and cached on first use for better performance.
        Comparison is case-insensitive.

        Args:
            payee: Transaction payee string to match.
            pattern: Regex pattern to match against (case-insensitive).

        Returns:
            1.0 if pattern matches payee, 0.0 otherwise.
        """
        try:
            normalized_payee = payee.upper().strip()
            normalized_pattern = pattern.upper().strip()

            # Get or compile and cache the pattern
            if normalized_pattern not in self.compiled_patterns:
                self.compiled_patterns[normalized_pattern] = re.compile(
                    normalized_pattern,
                    re.IGNORECASE,
                )

            compiled = self.compiled_patterns[normalized_pattern]
            if compiled.search(normalized_payee):
                return 1.0
            return 0.0
        except re.error as e:
            logger.warning("Invalid regex pattern '%s': %s", pattern, e)
            return 0.0

    def _fuzzy_match(self, payee: str, pattern: str) -> float:
        """
        Fuzzy match payee against pattern using sequence similarity with caching.

        Uses SequenceMatcher to calculate string similarity. Results are cached
        by (payee, pattern) tuple to avoid redundant calculations.

        Args:
            payee: Transaction payee string to match.
            pattern: Fuzzy pattern to match against.

        Returns:
            Similarity ratio from 0.0 to 1.0 (cached for performance).
        """
        normalized_payee = payee.upper().strip()
        normalized_pattern = pattern.upper().strip()

        # Check cache first
        cache_key = (normalized_payee, normalized_pattern)
        if cache_key in self.fuzzy_cache:
            return self.fuzzy_cache[cache_key]

        # Calculate and cache the result
        score = SequenceMatcher(None, normalized_payee, normalized_pattern).ratio()
        self.fuzzy_cache[cache_key] = score
        return score

    def _amount_score(self, transaction: data.Transaction, schedule: Schedule) -> float:
        """
        Calculate amount matching score.

        Supports:
        - Exact amount with tolerance (derived from posting for matched account)
        - Amount range (min/max)

        Returns:
            Score from 0.0 to 1.0 (linear decay from exact to tolerance boundary)
        """
        if not transaction.postings:
            return 0.0

        # Get amount from first posting
        txn_amount = transaction.postings[0].units.number

        match_criteria = schedule.match

        # Check if using amount range
        if match_criteria.amount_min is not None and match_criteria.amount_max is not None:
            if match_criteria.amount_min <= txn_amount <= match_criteria.amount_max:
                return 1.0
            return 0.0

        # Derive expected amount from schedule's posting for the matched account
        expected_amount = self._get_expected_amount_from_postings(schedule)

        if expected_amount is None:
            # No amount criteria - match any amount
            return 1.0

        tolerance = match_criteria.amount_tolerance

        if tolerance is None:
            # Use default percentage tolerance
            tolerance = abs(expected_amount) * Decimal(
                str(self.config.default_amount_tolerance_percent),
            )

        diff = abs(txn_amount - expected_amount)

        if diff > tolerance:
            return 0.0

        if tolerance == 0:
            return 1.0

        # Linear interpolation: 1.0 at exact match, 0.0 at tolerance boundary
        score = 1.0 - float(diff / tolerance)
        return max(0.0, min(1.0, score))

    def _get_expected_amount_from_postings(self, schedule: Schedule) -> Optional[Decimal]:
        """
        Get expected amount from schedule postings by finding the posting
        that matches the schedule's match account.

        Args:
            schedule: Schedule with transaction postings

        Returns:
            Expected amount from matched account posting, or None if not found
        """
        if not schedule.transaction.postings:
            return None

        # Find the posting for the matched account
        for posting in schedule.transaction.postings:
            if posting.account == schedule.match.account:
                if posting.amount is not None:
                    return Decimal(str(posting.amount))
                return None

        # If matched account not found in postings, no amount criteria
        return None

    def _date_score(
        self,
        transaction: data.Transaction,
        schedule: Schedule,
        expected_date: date,
    ) -> float:
        """
        Calculate date proximity score based on difference from expected date.

        Uses linear interpolation within the configured date window. Transactions
        matching the expected date exactly score 1.0, declining linearly to 0.0
        at the window boundary.

        Args:
            transaction: Transaction with date to evaluate.
            schedule: Schedule defining the date_window_days tolerance.
            expected_date: Expected occurrence date from recurrence rule.

        Returns:
            Score from 0.0 to 1.0 (1.0 at exact match, 0.0 outside window).
        """
        txn_date = transaction.date
        window_days = schedule.match.date_window_days or self.config.default_date_window_days

        diff_days = abs((txn_date - expected_date).days)

        if diff_days > window_days:
            return 0.0

        if window_days == 0:
            return 1.0

        # Linear interpolation: 1.0 at exact match, 0.0 at window boundary
        score = 1.0 - (diff_days / window_days)
        return max(0.0, min(1.0, score))

    def find_best_match(
        self,
        transaction: data.Transaction,
        candidates: list[tuple[Schedule, date]],
    ) -> Optional[tuple[Schedule, date, float]]:
        """
        Find best matching schedule for transaction.

        Args:
            transaction: Imported transaction
            candidates: List of (schedule, expected_date) tuples to consider

        Returns:
            Tuple of (schedule, expected_date, score) for best match,
            or None if no match above threshold
        """
        best_match = None
        best_score = 0.0

        for schedule, expected_date in candidates:
            score = self.calculate_match_score(transaction, schedule, expected_date)

            if score > best_score and score >= self.config.fuzzy_match_threshold:
                best_score = score
                best_match = (schedule, expected_date, score)

        return best_match
