"""Tests for the beangulp schedule_hook integration."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from beancount.core import data

from beanschedule.hook import schedule_hook
from beanschedule.schema import ScheduleFile


class TestScheduleHook:
    """Tests for the main schedule_hook function."""

    def test_hook_with_no_schedules(self, sample_transaction, global_config):
        """Test hook returns unchanged entries when no schedules found."""
        txn = sample_transaction(
            date(2024, 1, 15),
            "Test",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        extracted_entries = [
            ("test.csv", [txn], "Assets:Bank:Checking", None),
        ]

        # Mock schedule loader to return None
        with patch("beanschedule.hook.load_schedules_file", return_value=None):
            result = schedule_hook(extracted_entries)

        # Should return unchanged
        assert result == extracted_entries

    def test_hook_with_no_enabled_schedules(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test hook returns unchanged entries when no enabled schedules."""
        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        # Create disabled schedule
        schedule = sample_schedule(enabled=False)

        extracted_entries = [
            ("test.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should return unchanged (no enabled schedules)
        assert result == extracted_entries

    def test_hook_with_empty_entries_list(self, global_config, sample_schedule):
        """Test hook with empty entries list."""
        schedule = sample_schedule()
        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        extracted_entries = []

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should return empty list
        assert result == []

    def test_hook_with_non_transaction_entries(self, global_config, sample_schedule):
        """Test hook ignores non-transaction entries."""
        schedule = sample_schedule()
        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        # Create a non-transaction entry (e.g., Open directive)
        open_entry = data.Open(
            meta=data.new_metadata("test", 0),
            date=date(2024, 1, 1),
            account="Assets:Bank:Checking",
            currencies=["USD"],
            booking=None,
        )

        extracted_entries = [
            ("test.csv", [open_entry], "Assets:Bank:Checking", None),
        ]

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should return with Open directive unchanged
        assert len(result) == 1
        assert result[0][1][0] == open_entry


class TestHookEntryFormats:
    """Tests for different beangulp entry formats."""

    def test_hook_with_4_tuple_format(self, sample_transaction, sample_schedule, global_config):
        """Test hook with 4-tuple format: (filepath, entries, account, importer)."""
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

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", MagicMock()),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should have original entry (4-tuple format maintained)
        assert len(result) == 1
        assert len(result[0]) == 4


class TestTransactionMatching:
    """Tests for transaction matching in the hook."""

    def test_hook_matches_single_transaction(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test hook matches a single transaction."""
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

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # First entry should have matched transaction with metadata
        matched_txn = result[0][1][0]
        assert "schedule_id" in matched_txn.meta
        assert matched_txn.meta["schedule_id"] == schedule.id
        assert "schedule_matched_date" in matched_txn.meta
        assert "schedule_confidence" in matched_txn.meta

    def test_hook_no_match_keeps_original(self, sample_transaction, sample_schedule, global_config):
        """Test hook keeps original transaction when no match."""
        txn = sample_transaction(
            date(2024, 1, 15),
            "Unknown Payee",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule(
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Transaction should be unchanged
        unmatched_txn = result[0][1][0]
        assert "schedule_id" not in unmatched_txn.meta


class TestTransactionEnrichment:
    """Tests for transaction enrichment with schedule metadata."""

    def test_enrichment_adds_metadata(self, sample_transaction, sample_schedule, global_config):
        """Test that enrichment adds schedule metadata."""
        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            id="rent",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        matched_txn = result[0][1][0]
        assert matched_txn.meta["schedule_id"] == "rent"
        assert "schedule_matched_date" in matched_txn.meta
        assert matched_txn.meta["schedule_matched_date"] == "2024-01-15"

    def test_enrichment_merges_tags(self, sample_transaction, sample_schedule, global_config):
        """Test that enrichment merges tags."""
        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        txn = txn._replace(tags={"original"})

        schedule = sample_schedule(
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )
        # Add tags to schedule
        schedule.transaction.tags = ["schedule-tag"]

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        matched_txn = result[0][1][0]
        # Should have both tags
        assert "original" in matched_txn.tags
        assert "schedule-tag" in matched_txn.tags

    def test_enrichment_overrides_payee(self, sample_transaction, sample_schedule, global_config):
        """Test that enrichment can override payee."""
        txn = sample_transaction(
            date(2024, 1, 15),
            "LANDLORD ABBREV",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        schedule = sample_schedule(
            payee_pattern="LANDLORD",
            amount=Decimal("-1500.00"),
        )
        schedule.transaction.payee = "Full Landlord Name"

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        matched_txn = result[0][1][0]
        assert matched_txn.payee == "Full Landlord Name"

    def test_enrichment_overrides_narration(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that enrichment can override narration."""
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
        schedule.transaction.narration = "Monthly Rent Payment"

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        matched_txn = result[0][1][0]
        assert matched_txn.narration == "Monthly Rent Payment"


class TestPlaceholderCreation:
    """Tests for creating placeholders for missing transactions."""

    def test_placeholder_created_for_missing_transaction(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that placeholders are created for missing scheduled transactions."""
        # Transaction on Jan 20, but schedule expects Jan 15
        txn = sample_transaction(
            date(2024, 1, 20),
            "Other",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule(
            day_of_month=15,
            payee_pattern="Landlord",
        )
        schedule.match.payee_pattern = "Landlord"  # Won't match "Other"
        schedule.missing_transaction.create_placeholder = True

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should have original entry + schedules entry with placeholder
        assert len(result) == 2
        placeholders = result[1][1]
        assert len(placeholders) > 0

        placeholder = placeholders[0]
        assert placeholder.flag == "!"
        assert placeholder.meta.get("schedule_placeholder") == "true"

    def test_placeholder_skipped_when_disabled(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that placeholders are not created when disabled."""
        txn = sample_transaction(
            date(2024, 1, 20),
            "Other",
            "Assets:Bank:Checking",
            Decimal("-100.00"),
        )

        schedule = sample_schedule(
            day_of_month=15,
            create_placeholder=False,  # Disable placeholder creation
        )

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should have only original entry, no schedules entry
        assert len(result) == 1


class TestMultipleFiles:
    """Tests for processing multiple imported files."""

    def test_hook_processes_multiple_files(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test hook processes multiple imported files."""
        txn1 = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        txn2 = sample_transaction(
            date(2024, 1, 20),
            "Utilities",
            "Assets:Bank:Savings",
            Decimal("-100.00"),
        )

        schedule1 = sample_schedule(
            id="rent",
            account="Assets:Bank:Checking",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        extracted_entries = [
            ("checking.csv", [txn1], "Assets:Bank:Checking", None),
            ("savings.csv", [txn2], "Assets:Bank:Savings", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule1], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Should have original 2 files
        assert len(result) == 2
        # First file should have matched transaction
        assert "schedule_id" in result[0][1][0].meta
        # Second file should be unchanged (different account, no matching schedule)
        assert "schedule_id" not in result[1][1][0].meta


class TestPostingReplacement:
    """Tests for replacing postings with schedule template."""

    def test_posting_replacement_with_schedule(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that postings are replaced from schedule template."""
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

        # Add postings to schedule template
        from beanschedule.schema import Posting

        schedule.transaction.postings = [
            Posting(account="Assets:Bank:Checking", amount=None, narration=None),
            Posting(account="Expenses:Housing:Rent", amount=None, narration=None),
        ]

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        matched_txn = result[0][1][0]
        # Should have the schedule's postings
        assert len(matched_txn.postings) == 2
        assert matched_txn.postings[0].account == "Assets:Bank:Checking"
        assert matched_txn.postings[1].account == "Expenses:Housing:Rent"
        # First posting should have the imported amount
        assert matched_txn.postings[0].units.number == Decimal("-1500.00")
