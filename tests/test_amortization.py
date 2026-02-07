"""Tests for amortization calculations."""

from datetime import date
from decimal import Decimal

import pytest

from beanschedule.amortization import AmortizationSchedule, PaymentSplit


class TestAmortizationSchedule:
    """Tests for AmortizationSchedule class."""

    def test_create_basic_schedule(self):
        """Should create amortization schedule with basic parameters."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        assert schedule.principal == Decimal("100000")
        assert schedule.annual_rate == Decimal("0.06")
        assert schedule.monthly_rate == Decimal("0.06") / Decimal("12")
        assert schedule.term_months == 360
        assert schedule.payment > 0

    def test_calculate_monthly_payment(self):
        """Should calculate correct monthly payment for known loan."""
        # Example: $300k at 6.75% for 30 years
        # Expected payment: ~$1,945.09
        schedule = AmortizationSchedule(
            principal=Decimal("300000"),
            annual_rate=Decimal("0.0675"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        # Payment should be around $1,945
        assert Decimal("1944") < schedule.payment < Decimal("1946")

    def test_first_payment_split(self):
        """Should correctly split first payment into principal and interest."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        split = schedule.get_payment_split(1)

        # First payment interest = principal * monthly rate
        expected_interest = Decimal("100000") * (Decimal("0.06") / Decimal("12"))
        assert abs(split.interest - expected_interest) < Decimal("0.01")

        # Principal = payment - interest
        expected_principal = schedule.payment - split.interest
        assert abs(split.principal - expected_principal) < Decimal("0.01")

        # Total payment matches fixed payment
        assert split.total_payment == schedule.payment

        # Remaining balance = principal - principal paid
        assert split.remaining_balance == Decimal("100000") - split.principal

    def test_payment_split_progression(self):
        """Should show principal increasing and interest decreasing over time."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        split_1 = schedule.get_payment_split(1)
        split_100 = schedule.get_payment_split(100)
        split_200 = schedule.get_payment_split(200)

        # Interest should decrease over time
        assert split_1.interest > split_100.interest
        assert split_100.interest > split_200.interest

        # Principal should increase over time
        assert split_1.principal < split_100.principal
        assert split_100.principal < split_200.principal

    def test_last_payment(self):
        """Should pay off remaining balance in final payment."""
        schedule = AmortizationSchedule(
            principal=Decimal("10000"),
            annual_rate=Decimal("0.06"),
            term_months=12,  # 1 year
            start_date=date(2024, 1, 1),
        )

        final_split = schedule.get_payment_split(12)

        # Final payment should result in zero balance
        assert final_split.remaining_balance == Decimal("0")

        # Final payment may be different from regular payment due to rounding
        assert final_split.total_payment > 0

    def test_total_interest_calculation(self):
        """Should calculate total interest over life of loan."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        total_interest = schedule.get_total_interest()

        # Total interest should be substantial for 30-year loan
        assert total_interest > Decimal("100000")  # More than the principal

        # Total payments = principal + interest
        total_payments = schedule.payment * Decimal("360")
        # Last payment may be different, so allow for some variance
        assert abs(total_payments - (Decimal("100000") + total_interest)) < Decimal("100")

    def test_zero_interest_rate(self):
        """Should handle zero interest rate (interest-free loan)."""
        schedule = AmortizationSchedule(
            principal=Decimal("12000"),
            annual_rate=Decimal("0"),
            term_months=12,
            start_date=date(2024, 1, 1),
        )

        # Payment should be simple division
        expected_payment = Decimal("12000") / Decimal("12")
        assert schedule.payment == expected_payment

        # Each payment should be all principal, no interest
        split = schedule.get_payment_split(1)
        assert split.interest == Decimal("0")
        assert split.principal == expected_payment

    def test_extra_principal_payment(self):
        """Should handle extra principal payments correctly."""
        # Regular schedule
        regular = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        # Schedule with extra principal
        with_extra = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
            extra_principal=Decimal("100"),
        )

        regular_split_10 = regular.get_payment_split(10)
        extra_split_10 = with_extra.get_payment_split(10)

        # Extra principal should result in lower balance
        assert extra_split_10.remaining_balance < regular_split_10.remaining_balance

        # Extra principal payment should be included in total
        assert extra_split_10.total_payment == regular.payment + Decimal("100")

    def test_get_payment_number_for_date(self):
        """Should calculate payment number from date."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        # First payment
        assert schedule.get_payment_number_for_date(date(2024, 1, 1)) == 1

        # Second payment
        assert schedule.get_payment_number_for_date(date(2024, 2, 1)) == 2

        # Payment one year later
        assert schedule.get_payment_number_for_date(date(2025, 1, 1)) == 13

        # Date before start should return None
        assert schedule.get_payment_number_for_date(date(2023, 12, 1)) is None

        # Date after loan term should return None
        assert schedule.get_payment_number_for_date(date(2054, 2, 1)) is None

    def test_generate_full_schedule(self):
        """Should generate complete amortization schedule."""
        schedule = AmortizationSchedule(
            principal=Decimal("10000"),
            annual_rate=Decimal("0.06"),
            term_months=12,
            start_date=date(2024, 1, 1),
        )

        full_schedule = schedule.generate_full_schedule()

        # Should have one payment for each month
        assert len(full_schedule) == 12

        # All should be PaymentSplit objects
        assert all(isinstance(split, PaymentSplit) for split in full_schedule)

        # Last payment should have zero balance
        assert full_schedule[-1].remaining_balance == Decimal("0")

        # Payment numbers should be sequential
        for i, split in enumerate(full_schedule, start=1):
            assert split.payment_number == i


class TestAmortizationEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_payment_number_negative(self):
        """Should raise error for negative payment number."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        with pytest.raises(ValueError, match="must be >= 1"):
            schedule.get_payment_split(0)

    def test_invalid_payment_number_exceeds_term(self):
        """Should raise error for payment number beyond term."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        with pytest.raises(ValueError, match="exceeds term"):
            schedule.get_payment_split(361)

    def test_small_principal(self):
        """Should handle small principal amounts."""
        schedule = AmortizationSchedule(
            principal=Decimal("100"),
            annual_rate=Decimal("0.06"),
            term_months=12,
            start_date=date(2024, 1, 1),
        )

        split = schedule.get_payment_split(1)
        assert split.principal > 0
        assert split.interest > 0

    def test_large_principal(self):
        """Should handle large principal amounts."""
        schedule = AmortizationSchedule(
            principal=Decimal("10000000"),  # $10M
            annual_rate=Decimal("0.06"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        split = schedule.get_payment_split(1)
        assert split.principal > 0
        assert split.interest > 0
        assert split.total_payment > 0

    def test_high_interest_rate(self):
        """Should handle high interest rates."""
        schedule = AmortizationSchedule(
            principal=Decimal("100000"),
            annual_rate=Decimal("0.20"),  # 20% APR
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        split = schedule.get_payment_split(1)

        # At high interest, most of first payment is interest
        assert split.interest > split.principal

    def test_short_term_loan(self):
        """Should handle very short term loans."""
        schedule = AmortizationSchedule(
            principal=Decimal("1200"),
            annual_rate=Decimal("0.06"),
            term_months=3,  # 3 months
            start_date=date(2024, 1, 1),
        )

        full_schedule = schedule.generate_full_schedule()
        assert len(full_schedule) == 3
        assert full_schedule[-1].remaining_balance == Decimal("0")


class TestAmortizationRealWorld:
    """Tests with real-world loan scenarios."""

    def test_typical_mortgage(self):
        """Should match typical 30-year mortgage calculation."""
        # $400k house, 20% down = $320k loan at 7% for 30 years
        schedule = AmortizationSchedule(
            principal=Decimal("320000"),
            annual_rate=Decimal("0.07"),
            term_months=360,
            start_date=date(2024, 1, 1),
        )

        # Monthly payment should be around $2,129
        assert Decimal("2125") < schedule.payment < Decimal("2135")

        # First payment: mostly interest
        first = schedule.get_payment_split(1)
        assert first.interest > first.principal

        # Mid-point: still more interest, but more balanced than first payment
        mid = schedule.get_payment_split(180)
        # At halfway point, ratio should be more balanced than first payment
        first_ratio = first.interest / first.principal
        mid_ratio = mid.interest / mid.principal
        assert mid_ratio < first_ratio  # Ratio is improving

        # Last payment: mostly principal
        last = schedule.get_payment_split(360)
        assert last.principal > last.interest
        assert last.remaining_balance == Decimal("0")

    def test_auto_loan(self):
        """Should match typical 5-year auto loan."""
        # $30k car loan at 5% for 60 months
        schedule = AmortizationSchedule(
            principal=Decimal("30000"),
            annual_rate=Decimal("0.05"),
            term_months=60,
            start_date=date(2024, 1, 1),
        )

        # Monthly payment should be around $566
        assert Decimal("565") < schedule.payment < Decimal("568")

        # Total interest should be reasonable
        total_interest = schedule.get_total_interest()
        assert Decimal("3500") < total_interest < Decimal("4000")

    def test_student_loan(self):
        """Should match typical 10-year student loan."""
        # $50k at 6.5% for 10 years
        schedule = AmortizationSchedule(
            principal=Decimal("50000"),
            annual_rate=Decimal("0.065"),
            term_months=120,
            start_date=date(2024, 1, 1),
        )

        # Monthly payment should be around $568
        assert Decimal("565") < schedule.payment < Decimal("570")

        # Check that paying extra principal helps
        with_extra = AmortizationSchedule(
            principal=Decimal("50000"),
            annual_rate=Decimal("0.065"),
            term_months=120,
            start_date=date(2024, 1, 1),
            extra_principal=Decimal("50"),
        )

        # Total interest should be lower with extra payments
        regular_interest = schedule.get_total_interest()
        extra_interest = with_extra.get_total_interest()

        # With extra principal, should pay less interest overall
        # Note: This is approximate since the loan doesn't actually pay off early in our model
        assert extra_interest <= regular_interest
