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
        Match payee against regex pattern.

        Returns:
            1.0 if matches, 0.0 if not
        """
        try:
            normalized_payee = payee.upper().strip()
            normalized_pattern = pattern.upper().strip()

            if re.search(normalized_pattern, normalized_payee):
                return 1.0
            return 0.0
        except re.error as e:
            logger.warning("Invalid regex pattern '%s': %s", pattern, e)
            return 0.0

    def _fuzzy_match(self, payee: str, pattern: str) -> float:
        """
        Fuzzy match payee against pattern using sequence similarity.

        Returns:
            Similarity ratio from 0.0 to 1.0
        """
        normalized_payee = payee.upper().strip()
        normalized_pattern = pattern.upper().strip()

        return SequenceMatcher(None, normalized_payee, normalized_pattern).ratio()

    def _amount_score(self, transaction: data.Transaction, schedule: Schedule) -> float:
        """
        Calculate amount matching score.

        Supports:
        - Exact amount with tolerance
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

        # Check if using exact amount with tolerance
        if match_criteria.amount is None:
            # No amount criteria
            return 1.0

        expected_amount = match_criteria.amount
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

    def _date_score(
        self,
        transaction: data.Transaction,
        schedule: Schedule,
        expected_date: date,
    ) -> float:
        """
        Calculate date proximity score.

        Returns:
            Score from 0.0 to 1.0 (linear decay from exact to window boundary)
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
