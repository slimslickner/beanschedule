"""Tests for skip marker transaction support."""

from datetime import date
from decimal import Decimal

from beancount.core import amount, data

from beanschedule.constants import META_SCHEDULE_ID, META_SCHEDULE_SKIPPED
from beanschedule.hook import _is_skip_marker, schedule_hook
from beanschedule.schema import ScheduleFile
from tests.conftest import make_posting, make_transaction, make_transaction_with_postings


class TestSkipMarkerDetection:
    """Tests for identifying skip marker transactions."""

    def test_skip_marker_with_flag_S(self):
        """Transaction with flag 'S' is recognized as skip marker."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            None,
            flag="S",
        )
        assert _is_skip_marker(txn) is True

    def test_skip_marker_with_skipped_tag(self):
        """Transaction with #skipped tag is recognized as skip marker."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            None,
            tags={"skipped"},  # Beancount stores tags without the # symbol
        )
        assert _is_skip_marker(txn) is True

    def test_skip_marker_with_schedule_skipped_metadata(self):
        """Transaction with schedule_skipped metadata is recognized as skip marker."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            None,
            **{META_SCHEDULE_SKIPPED: "true"}
        )
        assert _is_skip_marker(txn) is True

    def test_skip_marker_with_schedule_skipped_and_reason(self):
        """Transaction with schedule_skipped metadata and reason value."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            None,
            **{META_SCHEDULE_SKIPPED: "$0 balance"}
        )
        assert _is_skip_marker(txn) is True

    def test_normal_transaction_not_skip_marker(self):
        """Regular transaction without skip indicators is not a skip marker."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            Decimal("-100.00"),
        )
        assert _is_skip_marker(txn) is False

    def test_transaction_with_other_flag_not_skip_marker(self):
        """Transaction with other flags (*, !) is not a skip marker."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            Decimal("-100.00"),
            flag="*",
        )
        assert _is_skip_marker(txn) is False

    def test_transaction_with_other_tags_not_skip_marker(self):
        """Transaction with other tags but not #skipped is not a skip marker."""
        txn = make_transaction(
            date(2026, 2, 15),
            "Test Payee",
            "Assets:Checking",
            Decimal("-100.00"),
            tags={"#expenses", "#food"},
        )
        assert _is_skip_marker(txn) is False


class TestSkipMarkerPreventsPlaceholder:
    """Tests for skip markers preventing placeholder creation."""

    def test_skip_marker_prevents_missing_placeholder(
        self, sample_schedule, sample_transaction, global_config
    ):
        """Skip marker transaction prevents placeholder creation for that occurrence."""
        schedule = sample_schedule(
            schedule_id="rent-payment",
            payee="Landlord",
        )
        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        # Two occurrences: Feb 1 and Mar 1
        # We'll create a skip marker for Feb 1
        skip_marker = make_transaction(
            date(2026, 2, 1),
            "Landlord",
            "Assets:Checking",
            None,
            flag="S",
            narration="[SKIPPED] Testing",
            **{
                META_SCHEDULE_ID: "rent-payment",
                META_SCHEDULE_SKIPPED: "Testing",
            }
        )

        # Mar 1 transaction is missing - should get placeholder
        # But Feb 1 skip marker should prevent placeholder

        extracted_entries = [
            ("test.csv", [skip_marker], "Assets:Checking", None),
        ]

        from unittest.mock import patch
        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[])

        # Skip marker should be included in results
        assert len(result) > 0
        assert result[0][1][0] == skip_marker

    def test_skip_marker_with_schedule_id_metadata(
        self, sample_schedule, global_config
    ):
        """Skip marker with explicit schedule_id metadata is recognized."""
        schedule = sample_schedule(schedule_id="test-schedule")
        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        skip_marker = make_transaction(
            date(2026, 2, 15),
            schedule.transaction.payee,
            schedule.match.account,
            None,
            **{META_SCHEDULE_ID: "test-schedule", META_SCHEDULE_SKIPPED: "true"}
        )

        extracted_entries = [
            ("test.csv", [skip_marker], schedule.match.account, None),
        ]

        from unittest.mock import patch
        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[])

        # Transaction should be preserved in output
        assert len(result) > 0

    def test_multiple_skip_markers_same_schedule(self):
        """Multiple skip markers for different occurrences of same schedule."""
        # Create skip markers with different indicators
        skip1 = make_transaction(
            date(2026, 2, 1),
            "Test Payee",
            "Assets:Checking",
            None,
            flag="S",
        )

        skip2 = make_transaction(
            date(2026, 2, 8),
            "Test Payee",
            "Assets:Checking",
            None,
            **{META_SCHEDULE_SKIPPED: "Traveling"}
        )

        # Both should be recognized as skip markers
        assert _is_skip_marker(skip1) is True
        assert _is_skip_marker(skip2) is True


class TestSkipMarkerLogging:
    """Tests for skip marker detection and logging in the lazy matching function."""

    def test_is_skip_marker_function(self):
        """Test the _is_skip_marker() function detects skip markers correctly."""
        # Flag 'S'
        txn_with_flag = make_transaction(
            date(2026, 2, 1),
            "Test",
            "Assets:Checking",
            None,
            flag="S",
        )
        assert _is_skip_marker(txn_with_flag) is True

        # Metadata
        txn_with_meta = make_transaction(
            date(2026, 2, 1),
            "Test",
            "Assets:Checking",
            None,
            **{META_SCHEDULE_SKIPPED: "$0 balance"}
        )
        assert _is_skip_marker(txn_with_meta) is True

        # Tag (Beancount stores tags without the # symbol)
        txn_with_tag = make_transaction(
            date(2026, 2, 1),
            "Test",
            "Assets:Checking",
            None,
            tags={"skipped"},
        )
        assert _is_skip_marker(txn_with_tag) is True

        # Normal transaction
        txn_normal = make_transaction(
            date(2026, 2, 1),
            "Test",
            "Assets:Checking",
            Decimal("-100.00"),
        )
        assert _is_skip_marker(txn_normal) is False
