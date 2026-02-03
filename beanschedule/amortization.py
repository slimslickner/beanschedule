"""Amortization calculations for loan payments.

Supports calculating principal and interest splits for loan payments
using standard amortization formulas.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import NamedTuple

logger = logging.getLogger(__name__)


class PaymentSplit(NamedTuple):
    """Principal and interest components of a payment."""

    principal: Decimal
    interest: Decimal
    total_payment: Decimal
    remaining_balance: Decimal
    payment_number: int


class AmortizationSchedule:
    """Calculate amortization schedule for a loan.

    Uses standard loan amortization formula to calculate monthly payments
    and split them into principal and interest components.

    Example:
        >>> schedule = AmortizationSchedule(
        ...     principal=Decimal("300000"),
        ...     annual_rate=Decimal("0.0675"),
        ...     term_months=360,
        ...     start_date=date(2024, 1, 1)
        ... )
        >>> split = schedule.get_payment_split(payment_number=1)
        >>> print(f"Principal: {split.principal}, Interest: {split.interest}")
    """

    def __init__(
        self,
        principal: Decimal,
        annual_rate: Decimal,
        term_months: int,
        start_date: date,
        extra_principal: Decimal | None = None,
    ):
        """Initialize amortization schedule.

        Args:
            principal: Initial loan amount
            annual_rate: Annual interest rate (e.g., 0.0675 for 6.75%)
            term_months: Loan term in months
            start_date: First payment date
            extra_principal: Optional extra principal payment per period
        """
        self.principal = principal
        self.annual_rate = annual_rate
        self.monthly_rate = annual_rate / Decimal("12")
        self.term_months = term_months
        self.start_date = start_date
        self.extra_principal = extra_principal or Decimal("0")

        # Calculate fixed payment amount using PMT formula
        self.payment = self._calculate_payment()

        logger.debug(
            "Amortization schedule created: principal=%s, rate=%s, term=%d months, payment=%s",
            principal,
            annual_rate,
            term_months,
            self.payment,
        )

    def _calculate_payment(self) -> Decimal:
        """Calculate fixed monthly payment using PMT formula.

        Formula: PMT = P * [r(1+r)^n] / [(1+r)^n - 1]
        Where:
            P = principal
            r = monthly interest rate
            n = number of payments
        """
        if self.monthly_rate == 0:
            # No interest - simple division
            return self.principal / Decimal(self.term_months)

        r = self.monthly_rate
        n = Decimal(self.term_months)

        # Calculate (1 + r)^n
        factor = (Decimal("1") + r) ** n

        # PMT = P * [r * factor] / [factor - 1]
        payment = self.principal * (r * factor) / (factor - Decimal("1"))

        # Round to 2 decimal places (cents)
        return payment.quantize(Decimal("0.01"))

    def get_payment_split(self, payment_number: int) -> PaymentSplit:
        """Get principal/interest split for a specific payment.

        Args:
            payment_number: Payment number (1-indexed, 1 = first payment)

        Returns:
            PaymentSplit with principal, interest, and remaining balance

        Raises:
            ValueError: If payment_number is invalid
        """
        if payment_number < 1:
            raise ValueError("Payment number must be >= 1")

        if payment_number > self.term_months:
            raise ValueError(
                f"Payment number {payment_number} exceeds term of {self.term_months} months"
            )

        # Calculate remaining balance before this payment
        balance_before = self._remaining_balance(payment_number - 1)

        # Interest = balance * monthly rate
        interest = (balance_before * self.monthly_rate).quantize(Decimal("0.01"))

        # Handle last payment - may be different due to rounding
        if payment_number == self.term_months:
            # Final payment pays off remaining balance
            total_payment = balance_before + interest
            principal = balance_before
            remaining_balance = Decimal("0")
        else:
            # Regular payment
            total_payment = self.payment
            principal = total_payment - interest

            # Add extra principal if configured
            if self.extra_principal > 0:
                principal += self.extra_principal
                total_payment += self.extra_principal

            # Calculate remaining balance after this payment
            remaining_balance = balance_before - principal

        return PaymentSplit(
            principal=principal,
            interest=interest,
            total_payment=total_payment,
            remaining_balance=remaining_balance,
            payment_number=payment_number,
        )

    def _remaining_balance(self, payments_made: int) -> Decimal:
        """Calculate remaining balance after N payments.

        Args:
            payments_made: Number of payments already made (0 = no payments yet)

        Returns:
            Remaining loan balance
        """
        if payments_made == 0:
            return self.principal

        if payments_made >= self.term_months:
            return Decimal("0")

        # Calculate balance using amortization formula
        # Balance = P * [(1+r)^n - (1+r)^p] / [(1+r)^n - 1]
        # Where:
        #   P = principal
        #   r = monthly rate
        #   n = total payments
        #   p = payments made

        r = self.monthly_rate
        n = Decimal(self.term_months)
        p = Decimal(payments_made)

        if r == 0:
            # No interest - simple subtraction
            per_payment = self.principal / n
            return self.principal - (per_payment * p)

        factor_n = (Decimal("1") + r) ** n
        factor_p = (Decimal("1") + r) ** p

        balance = self.principal * (factor_n - factor_p) / (factor_n - Decimal("1"))

        # If using extra principal, need to calculate iteratively
        if self.extra_principal > 0:
            balance = self._calculate_balance_with_extra_principal(payments_made)

        return balance.quantize(Decimal("0.01"))

    def _calculate_balance_with_extra_principal(self, payments_made: int) -> Decimal:
        """Calculate balance when extra principal payments are made.

        This requires iterative calculation since extra payments change
        the amortization schedule.

        Args:
            payments_made: Number of payments already made

        Returns:
            Remaining balance after extra principal payments
        """
        balance = self.principal

        for payment_num in range(1, payments_made + 1):
            # Interest on current balance
            interest = (balance * self.monthly_rate).quantize(Decimal("0.01"))

            # Principal = regular payment - interest + extra
            principal = self.payment - interest + self.extra_principal

            # Update balance
            balance = balance - principal

            # Don't go negative
            if balance < 0:
                balance = Decimal("0")
                break

        return balance

    def generate_full_schedule(self) -> list[PaymentSplit]:
        """Generate complete amortization schedule for all payments.

        Returns:
            List of PaymentSplit for each payment from 1 to term_months
        """
        return [self.get_payment_split(i) for i in range(1, self.term_months + 1)]

    def get_total_interest(self) -> Decimal:
        """Calculate total interest paid over life of loan.

        Returns:
            Total interest amount
        """
        schedule = self.generate_full_schedule()
        return sum((split.interest for split in schedule), Decimal("0"))

    def get_payment_number_for_date(self, payment_date: date) -> int | None:
        """Calculate payment number for a given date.

        Assumes monthly payments on the same day of month as start_date.

        Args:
            payment_date: Date of payment

        Returns:
            Payment number (1-indexed), or None if date is before start
        """
        if payment_date < self.start_date:
            return None

        # Calculate months elapsed
        months_elapsed = (
            (payment_date.year - self.start_date.year) * 12
            + payment_date.month
            - self.start_date.month
        )

        # Payment number is months elapsed + 1 (1-indexed)
        payment_number = months_elapsed + 1

        # Check if beyond loan term
        if payment_number > self.term_months:
            return None

        return payment_number


def compute_stateful_splits(
    monthly_payment: Decimal,
    annual_rate: Decimal,
    compounding: str,
    starting_balance: Decimal,
    starting_date: date,
    occurrence_dates: list[date],
    extra_principal: Decimal = Decimal("0"),
) -> dict[date, PaymentSplit]:
    """Compute P/I splits by walking forward from a known ledger balance.

    Used in stateful (balance_from_ledger) mode.  The caller supplies the
    current liability-account balance and the date it was observed; this
    function iterates through each upcoming payment date in order, applying
    interest according to the chosen compounding frequency and subtracting
    principal from the running balance.

    For DAILY compounding the interest for each period is proportional to
    the actual number of calendar days since the previous payment (or since
    ``starting_date`` for the first payment).  For MONTHLY compounding it is
    always ``balance × rate / 12``.

    The loop stops early once the balance reaches zero (loan paid off).

    Args:
        monthly_payment: Fixed P&I payment amount (from loan statement).
        annual_rate: Annual interest rate (e.g. Decimal("0.04875")).
        compounding: ``"MONTHLY"`` or ``"DAILY"``.
        starting_balance: Remaining principal at ``starting_date`` (positive).
        starting_date: Date of the most recent cleared posting to the
            liability account.  Interest for the first forecast payment accrues
            from this date.
        occurrence_dates: Expected payment dates to compute splits for.
            Typically the forecast-window occurrences generated by the
            recurrence engine.  Need not be sorted.
        extra_principal: Additional principal applied on top of the standard
            P&I payment each period.

    Returns:
        Dict mapping each payment date to its ``PaymentSplit``.  Dates beyond
        loan payoff are absent from the dict.
    """
    monthly_rate = annual_rate / Decimal("12")
    daily_rate = annual_rate / Decimal("365")

    sorted_dates = sorted(occurrence_dates)
    balance = starting_balance
    previous_date = starting_date
    splits: dict[date, PaymentSplit] = {}

    for payment_date in sorted_dates:
        if balance <= Decimal("0"):
            break

        # ── interest ──────────────────────────────────────────────────
        if compounding == "DAILY":
            days = max((payment_date - previous_date).days, 0)
            interest = (balance * daily_rate * Decimal(days)).quantize(Decimal("0.01"))
        else:  # MONTHLY
            interest = (balance * monthly_rate).quantize(Decimal("0.01"))

        # ── principal ─────────────────────────────────────────────────
        total_available = monthly_payment + extra_principal

        if interest >= total_available:
            # Negative amortization: payment does not cover interest.
            # Unpaid interest is capitalised onto the balance.
            principal = total_available - interest  # negative
            balance = (balance - principal).quantize(Decimal("0.01"))
            total_payment = total_available
            logger.warning(
                "Negative amortization on %s: interest %s exceeds payment %s",
                payment_date,
                interest,
                total_available,
            )
        else:
            principal = total_available - interest
            if principal >= balance:
                # Final payment — pay off remaining balance exactly
                principal = balance
                total_payment = balance + interest
                balance = Decimal("0")
            else:
                total_payment = total_available
                balance = (balance - principal).quantize(Decimal("0.01"))

        splits[payment_date] = PaymentSplit(
            principal=principal,
            interest=interest,
            total_payment=total_payment,
            remaining_balance=balance,
            payment_number=0,  # not meaningful in stateful mode
        )

        previous_date = payment_date

    return splits
