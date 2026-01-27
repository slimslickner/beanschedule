"""Recurring transaction pattern detection engine.

Analyzes ledger transactions to discover recurring patterns and generate
schedule templates with confidence scoring.
"""

import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from beancount.core import data

from .types import DayOfWeek, FrequencyType

logger = logging.getLogger(__name__)


@dataclass
class TransactionGroup:
    """A group of similar transactions (same account, payee, amount range)."""

    account: str
    """Exact account match."""

    payee_canonical: str
    """Canonical/most common payee name."""

    payee_variants: list[str] = field(default_factory=list)
    """All payee variants found in group."""

    amount_min: Decimal = field(default=None)
    """Minimum amount in group."""

    amount_max: Decimal = field(default=None)
    """Maximum amount in group."""

    amount_avg: Decimal = field(default=None)
    """Average amount in group."""

    transactions: list[data.Transaction] = field(default_factory=list)
    """Sorted list of transactions in group."""

    dates: list[date] = field(default_factory=list)
    """Sorted dates of transactions."""

    @property
    def count(self) -> int:
        """Number of transactions in group."""
        return len(self.transactions)


@dataclass
class GapAnalysis:
    """Analysis of gaps between transaction dates."""

    gaps: list[int] = field(default_factory=list)
    """Days between consecutive transactions."""

    median_gap: int = 0
    """Median gap in days."""

    mean_gap: float = 0.0
    """Mean gap in days."""

    std_dev: float = 0.0
    """Standard deviation of gaps."""

    min_gap: int = 0
    """Minimum gap in days."""

    max_gap: int = 0
    """Maximum gap in days."""

    @property
    def regularity_penalty(self) -> float:
        """Calculate regularity penalty (0.0-1.0) based on gap variance.

        Higher deviation from expected = lower score.
        Uses coefficient of variation: std_dev / mean_gap
        """
        if self.mean_gap == 0:
            return 0.0
        cv = self.std_dev / self.mean_gap
        # Convert CV to penalty: cv of 0.1 → 0.95, cv of 0.5 → 0.5
        return max(0.0, 1.0 - cv)


@dataclass
class FrequencyDetection:
    """Detected recurrence frequency and parameters."""

    frequency: FrequencyType
    """Detected frequency type."""

    day_of_month: Optional[int] = None
    """Day of month for MONTHLY/YEARLY."""

    month: Optional[int] = None
    """Month for YEARLY."""

    day_of_week: Optional[DayOfWeek] = None
    """Day of week for WEEKLY."""

    interval: int = 1
    """Interval for WEEKLY (e.g., 2 for biweekly)."""

    interval_months: Optional[int] = None
    """Month interval for INTERVAL frequency."""

    confidence_penalty: float = 0.0
    """Penalty for frequency detection certainty (0.0-1.0)."""

    def formatted_name(self) -> str:
        """Return human-readable frequency name."""
        if self.frequency == FrequencyType.WEEKLY:
            if self.interval == 1:
                return "Weekly"
            elif self.interval == 2:
                return "Bi-weekly"
            elif self.interval == 4:
                return "Monthly (weekly pattern)"
            return f"Every {self.interval} weeks"
        elif self.frequency == FrequencyType.MONTHLY:
            return "Monthly"
        elif self.frequency == FrequencyType.BIMONTHLY:
            return "Bi-monthly"
        elif self.frequency == FrequencyType.INTERVAL:
            if self.interval_months == 3:
                return "Quarterly"
            elif self.interval_months == 6:
                return "Semi-annually"
            return f"Every {self.interval_months} months"
        elif self.frequency == FrequencyType.YEARLY:
            return "Yearly"
        return self.frequency.value


@dataclass
class RecurringCandidate:
    """A detected recurring transaction pattern ready to be scheduled."""

    schedule_id: str
    """Unique schedule identifier."""

    payee: str
    """Detected payee name."""

    payee_pattern: str
    """Regex or fuzzy pattern for payee matching."""

    account: str
    """Account for transactions."""

    amount: Decimal
    """Typical transaction amount."""

    amount_tolerance: Decimal
    """Amount tolerance (±)."""

    frequency: FrequencyDetection
    """Detected frequency."""

    confidence: float
    """Overall confidence score (0.0-1.0)."""

    transaction_count: int = 0
    """Number of transactions in group."""

    first_date: date = None
    """Earliest transaction date."""

    last_date: date = None
    """Latest transaction date."""

    expected_occurrences: int = 0
    """Expected occurrences between first and last date."""


class RecurrenceDetector:
    """Main detection engine for recurring transaction patterns."""

    def __init__(
        self,
        fuzzy_threshold: float = 0.85,
        amount_tolerance_pct: float = 0.05,
        min_occurrences: int = 3,
        min_confidence: float = 0.60,
    ):
        """Initialize detector with configurable thresholds.

        Args:
            fuzzy_threshold: Payee fuzzy match threshold (0.0-1.0).
            amount_tolerance_pct: Amount variance tolerance as percentage.
            min_occurrences: Minimum transactions to consider a pattern.
            min_confidence: Minimum confidence to include in results.
        """
        self.fuzzy_threshold = fuzzy_threshold
        self.amount_tolerance_pct = amount_tolerance_pct
        self.min_occurrences = min_occurrences
        self.min_confidence = min_confidence
        # Cache for fuzzy match results
        self.fuzzy_cache: dict[tuple[str, str], float] = {}

    def detect(self, transactions: list[data.Transaction]) -> list[RecurringCandidate]:
        """Main detection pipeline.

        Args:
            transactions: List of Beancount transactions to analyze.

        Returns:
            List of RecurringCandidate objects sorted by confidence (highest first).
        """
        if not transactions:
            return []

        # Filter to only Transaction entries and those with postings
        valid_txns = [
            t
            for t in transactions
            if isinstance(t, data.Transaction) and t.postings and t.payee
        ]

        if not valid_txns:
            return []

        # Phase 1: Group similar transactions
        groups = self.group_transactions(valid_txns)
        logger.info("Grouped %d transactions into %d groups", len(valid_txns), len(groups))

        if not groups:
            return []

        # Phase 2: Analyze each group
        candidates: list[RecurringCandidate] = []
        for group in groups:
            # Skip groups below minimum occurrences
            if group.count < self.min_occurrences:
                logger.debug(
                    "Skipping group '%s' in %s: only %d occurrences (min: %d)",
                    group.payee_canonical,
                    group.account,
                    group.count,
                    self.min_occurrences,
                )
                continue

            # Phase 3: Analyze date gaps
            gap_analysis = self.analyze_gaps(group)

            # Phase 4: Detect frequency
            freq_detection = self.detect_frequency(gap_analysis, group)
            if freq_detection is None:
                logger.debug(
                    "Could not detect frequency for '%s' in %s",
                    group.payee_canonical,
                    group.account,
                )
                continue

            # Phase 5: Calculate confidence
            confidence = self.calculate_confidence(group, gap_analysis, freq_detection)

            # Phase 6: Filter by confidence threshold
            if confidence < self.min_confidence:
                logger.debug(
                    "Skipping '%s' in %s: confidence %.2f < %.2f",
                    group.payee_canonical,
                    group.account,
                    confidence,
                    self.min_confidence,
                )
                continue

            # Create candidate
            candidate = self._create_candidate(group, freq_detection, confidence)
            candidates.append(candidate)

        # Sort by confidence (highest first)
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        logger.info("Detected %d recurring patterns", len(candidates))

        return candidates

    def group_transactions(self, transactions: list[data.Transaction]) -> list[TransactionGroup]:
        """Group transactions by account, payee (fuzzy), and amount (tolerance).

        Hierarchical grouping:
        1. Exact account match
        2. Fuzzy payee match (threshold 0.85)
        3. Amount within tolerance (default ±5%)

        Args:
            transactions: List of transactions to group.

        Returns:
            List of TransactionGroup objects.
        """
        # First level: group by account
        by_account: dict[str, list[data.Transaction]] = defaultdict(list)
        for txn in transactions:
            if txn.postings:
                account = txn.postings[0].account
                by_account[account].append(txn)

        groups: list[TransactionGroup] = []

        # Second level: within each account, group by fuzzy payee match
        for account, txns_in_account in by_account.items():
            payee_groups: list[list[data.Transaction]] = []

            for txn in txns_in_account:
                # Find payee group with fuzzy match
                placed = False
                for payee_group in payee_groups:
                    canonical_payee = payee_group[0].payee
                    score = self._fuzzy_match(txn.payee, canonical_payee)
                    if score >= self.fuzzy_threshold:
                        payee_group.append(txn)
                        placed = True
                        break

                if not placed:
                    payee_groups.append([txn])

            # Third level: within each payee group, group by amount tolerance
            for payee_group in payee_groups:
                amount_groups: list[list[data.Transaction]] = []

                for txn in payee_group:
                    # Extract amount from first posting (ignoring currency)
                    if not txn.postings[0].units:
                        continue
                    txn_amount = abs(txn.postings[0].units.number)

                    # Find amount group with tolerance match
                    placed = False
                    for amount_group in amount_groups:
                        group_amount = abs(amount_group[0].postings[0].units.number)
                        tolerance = group_amount * Decimal(str(self.amount_tolerance_pct))

                        if group_amount - tolerance <= txn_amount <= group_amount + tolerance:
                            amount_group.append(txn)
                            placed = True
                            break

                    if not placed:
                        amount_groups.append([txn])

                # Create TransactionGroup objects
                for amount_group in amount_groups:
                    if not amount_group:
                        continue

                    group = self._create_transaction_group(account, amount_group)
                    groups.append(group)

        return groups

    def _create_transaction_group(
        self, account: str, transactions: list[data.Transaction]
    ) -> TransactionGroup:
        """Create a TransactionGroup from transactions.

        Args:
            account: Account for the group.
            transactions: Transactions in the group.

        Returns:
            Populated TransactionGroup object.
        """
        # Sort by date
        sorted_txns = sorted(transactions, key=lambda t: t.date)

        # Collect payee variants and find most common
        payees = [t.payee for t in sorted_txns if t.payee]
        payee_canonical = max(set(payees), key=payees.count) if payees else "Unknown"
        payee_variants = sorted(list(set(payees)))

        # Calculate amount statistics
        amounts = [
            abs(t.postings[0].units.number)
            for t in sorted_txns
            if t.postings and t.postings[0].units
        ]
        amount_min = min(amounts) if amounts else None
        amount_max = max(amounts) if amounts else None
        amount_avg = sum(amounts) / len(amounts) if amounts else None

        # Extract dates
        dates = [t.date for t in sorted_txns]

        return TransactionGroup(
            account=account,
            payee_canonical=payee_canonical,
            payee_variants=payee_variants,
            amount_min=amount_min,
            amount_max=amount_max,
            amount_avg=amount_avg,
            transactions=sorted_txns,
            dates=dates,
        )

    def analyze_gaps(self, group: TransactionGroup) -> GapAnalysis:
        """Analyze gaps between transaction dates.

        Calculates median, mean, std dev of days between consecutive
        transactions in the group.

        Args:
            group: TransactionGroup to analyze.

        Returns:
            GapAnalysis with gap statistics.
        """
        if len(group.dates) < 2:
            return GapAnalysis()

        gaps: list[int] = []
        for i in range(1, len(group.dates)):
            gap_days = (group.dates[i] - group.dates[i - 1]).days
            if gap_days > 0:  # Ignore same-day duplicates
                gaps.append(gap_days)

        if not gaps:
            return GapAnalysis()

        median = statistics.median(gaps)
        mean = statistics.mean(gaps)
        std_dev = statistics.stdev(gaps) if len(gaps) > 1 else 0.0

        return GapAnalysis(
            gaps=gaps,
            median_gap=int(median),
            mean_gap=mean,
            std_dev=std_dev,
            min_gap=min(gaps),
            max_gap=max(gaps),
        )

    def detect_frequency(
        self, gap_analysis: GapAnalysis, group: TransactionGroup
    ) -> Optional[FrequencyDetection]:
        """Detect recurrence frequency from gap analysis.

        Maps median gap to frequency type:
        - 7±1 days → WEEKLY (interval=1)
        - 14±2 days → WEEKLY (interval=2)
        - 28-32 days → MONTHLY
        - 88-92 days → INTERVAL (interval_months=3, quarterly)
        - 360-370 days → YEARLY

        Args:
            gap_analysis: GapAnalysis from analyze_gaps().
            group: TransactionGroup for day-of-month/week context.

        Returns:
            FrequencyDetection if pattern detected, None otherwise.
        """
        if gap_analysis.median_gap == 0:
            return None

        median_gap = gap_analysis.median_gap
        confidence_penalty = 0.0

        # Try to match to known frequencies
        # Weekly (7 days)
        if 6 <= median_gap <= 8:
            day_of_week = self._get_most_common_weekday(group.dates)
            return FrequencyDetection(
                frequency=FrequencyType.WEEKLY,
                day_of_week=day_of_week,
                interval=1,
                confidence_penalty=confidence_penalty,
            )

        # Bi-weekly (14 days)
        if 12 <= median_gap <= 16:
            day_of_week = self._get_most_common_weekday(group.dates)
            return FrequencyDetection(
                frequency=FrequencyType.WEEKLY,
                day_of_week=day_of_week,
                interval=2,
                confidence_penalty=confidence_penalty,
            )

        # Monthly (28-32 days)
        if 25 <= median_gap <= 35:
            day_of_month = self._get_most_common_day_of_month(group.dates)
            return FrequencyDetection(
                frequency=FrequencyType.MONTHLY,
                day_of_month=day_of_month,
                confidence_penalty=confidence_penalty,
            )

        # Quarterly (88-92 days, ~3 months)
        if 85 <= median_gap <= 95:
            day_of_month = self._get_most_common_day_of_month(group.dates)
            return FrequencyDetection(
                frequency=FrequencyType.INTERVAL,
                day_of_month=day_of_month,
                interval_months=3,
                confidence_penalty=confidence_penalty,
            )

        # Yearly (360-370 days)
        if 355 <= median_gap <= 375:
            month, day = self._get_most_common_month_day(group.dates)
            return FrequencyDetection(
                frequency=FrequencyType.YEARLY,
                month=month,
                day_of_month=day,
                confidence_penalty=confidence_penalty,
            )

        return None

    def calculate_confidence(
        self,
        group: TransactionGroup,
        gap_analysis: GapAnalysis,
        frequency: FrequencyDetection,
    ) -> float:
        """Calculate confidence score for a detected pattern.

        Scoring:
        - Coverage (50%): actual_count / expected_count
        - Regularity (30%): inverse of gap variance
        - Sample size (20%): more transactions = higher confidence

        Args:
            group: TransactionGroup being scored.
            gap_analysis: GapAnalysis for regularity.
            frequency: FrequencyDetection with penalty.

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        # Coverage: how many expected occurrences actually exist
        expected_occurrences = self._estimate_expected_occurrences(
            frequency, group.dates[0], group.dates[-1]
        )
        if expected_occurrences == 0:
            expected_occurrences = 1  # Avoid division by zero

        coverage_score = min(1.0, group.count / expected_occurrences)

        # Regularity: gap consistency
        regularity_score = gap_analysis.regularity_penalty

        # Sample size: penalize small sample sizes
        # 3 = 0.8, 5 = 0.9, 10+ = 1.0
        sample_size_score = min(1.0, 0.7 + (group.count / 15.0))

        # Weighted combination
        confidence = (
            (coverage_score * 0.5) + (regularity_score * 0.3) + (sample_size_score * 0.2)
        )

        # Apply frequency detection penalty
        confidence *= 1.0 - frequency.confidence_penalty

        return max(0.0, min(1.0, confidence))

    def _fuzzy_match(self, payee1: str, payee2: str) -> float:
        """Fuzzy match two payees using SequenceMatcher.

        Args:
            payee1: First payee string.
            payee2: Second payee string.

        Returns:
            Similarity score from 0.0 to 1.0.
        """
        normalized1 = payee1.upper().strip()
        normalized2 = payee2.upper().strip()

        cache_key = (normalized1, normalized2)
        if cache_key in self.fuzzy_cache:
            return self.fuzzy_cache[cache_key]

        score = SequenceMatcher(None, normalized1, normalized2).ratio()
        self.fuzzy_cache[cache_key] = score
        return score

    def _get_most_common_day_of_month(self, dates: list[date]) -> int:
        """Get the most common day of month from dates."""
        if not dates:
            return 1
        days = [d.day for d in dates]
        counter = Counter(days)
        # Handle month-end dates (28, 29, 30, 31)
        month_end_days = counter.get(28, 0) + counter.get(29, 0) + counter.get(30, 0) + counter.get(31, 0)
        if month_end_days > len(dates) // 2:
            return 28  # End of month
        return max(counter, key=counter.get) if counter else 1

    def _get_most_common_weekday(self, dates: list[date]) -> DayOfWeek:
        """Get the most common day of week from dates."""
        if not dates:
            return DayOfWeek.MON

        weekdays = [
            [
                DayOfWeek.MON,
                DayOfWeek.TUE,
                DayOfWeek.WED,
                DayOfWeek.THU,
                DayOfWeek.FRI,
                DayOfWeek.SAT,
                DayOfWeek.SUN,
            ][d.weekday()]
            for d in dates
        ]
        counter = Counter(weekdays)
        return max(counter, key=counter.get)

    def _get_most_common_month_day(self, dates: list[date]) -> tuple[int, int]:
        """Get the most common month and day from dates."""
        if not dates:
            return (1, 1)
        months = [d.month for d in dates]
        days = [d.day for d in dates]
        month_counter = Counter(months)
        day_counter = Counter(days)
        return (
            max(month_counter, key=month_counter.get),
            max(day_counter, key=day_counter.get),
        )

    def _estimate_expected_occurrences(
        self, frequency: FrequencyDetection, start_date: date, end_date: date
    ) -> int:
        """Estimate expected occurrences of a frequency between dates.

        Args:
            frequency: FrequencyDetection with frequency type.
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            Estimated number of occurrences.
        """
        days_between = (end_date - start_date).days
        if days_between <= 0:
            return 1

        if frequency.frequency == FrequencyType.WEEKLY:
            return (days_between // 7) // frequency.interval + 1

        if frequency.frequency == FrequencyType.MONTHLY:
            months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
            return months + 1

        if frequency.frequency == FrequencyType.INTERVAL:
            if frequency.interval_months:
                months = (end_date.year - start_date.year) * 12 + (
                    end_date.month - start_date.month
                )
                return (months // frequency.interval_months) + 1

        if frequency.frequency == FrequencyType.YEARLY:
            return (end_date.year - start_date.year) + 1

        return 1

    def _create_candidate(
        self,
        group: TransactionGroup,
        frequency: FrequencyDetection,
        confidence: float,
    ) -> RecurringCandidate:
        """Create a RecurringCandidate from group and frequency.

        Args:
            group: TransactionGroup.
            frequency: FrequencyDetection.
            confidence: Calculated confidence score.

        Returns:
            RecurringCandidate object.
        """
        # Generate schedule ID from payee + frequency for better naming
        from .cli import slugify

        payee_slug = slugify(group.payee_canonical)
        freq_name = frequency.formatted_name().lower().replace(" ", "-")

        # Create descriptive schedule ID: payee-frequency
        # e.g., "edison-power-monthly", "chase-slate-quarterly"
        schedule_id = f"{payee_slug}-{freq_name}"

        # Avoid excessive length (truncate if needed)
        if len(schedule_id) > 50:
            schedule_id = payee_slug

        # Create payee pattern (for now, use canonical payee)
        # In future, could generate regex from variants
        payee_pattern = group.payee_canonical

        # Amount tolerance
        amount_tolerance = group.amount_avg * Decimal(str(self.amount_tolerance_pct))

        expected_occ = self._estimate_expected_occurrences(
            frequency, group.dates[0], group.dates[-1]
        )

        return RecurringCandidate(
            schedule_id=schedule_id,
            payee=group.payee_canonical,
            payee_pattern=payee_pattern,
            account=group.account,
            amount=group.amount_avg,
            amount_tolerance=amount_tolerance,
            frequency=frequency,
            confidence=confidence,
            transaction_count=group.count,
            first_date=group.dates[0],
            last_date=group.dates[-1],
            expected_occurrences=expected_occ,
        )
