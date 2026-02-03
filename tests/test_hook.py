"""Tests for the beangulp schedule_hook integration."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from beancount.core import amount, data

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

    def test_hook_links_transaction_with_existing_schedule_id(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that transactions with pre-existing schedule_id metadata are linked without fuzzy matching."""
        # Create a transaction with existing schedule_id metadata
        meta = data.new_metadata("test.csv", 0)
        meta["schedule_id"] = "rent"
        txn = sample_transaction(
            date(2024, 1, 15),
            "Unknown Payee",  # Different from schedule pattern
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        txn = txn._replace(meta=meta)

        # Create schedule with strict matching criteria that wouldn't match fuzzy
        schedule = sample_schedule(
            id="rent",
            payee_pattern="LANDLORD",  # Strict pattern
            amount=Decimal("-1500.00"),
        )

        extracted_entries = [
            ("checking.csv", [txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        # Transaction should be matched to the rent schedule despite payee mismatch
        matched_txn = result[0][1][0]
        assert matched_txn.meta["schedule_id"] == "rent"
        # Confidence should be 1.0 (perfect) since it used pre-existing schedule_id
        assert matched_txn.meta["schedule_confidence"] == "1.00"

    def test_hook_falls_back_to_fuzzy_when_schedule_id_not_found(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that fuzzy matching is used when pre-existing schedule_id is not in candidates."""
        # Create a transaction with schedule_id that doesn't exist
        meta = data.new_metadata("test.csv", 0)
        meta["schedule_id"] = "nonexistent"
        txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord Corp",  # Slightly different payee for fuzzy matching
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        txn = txn._replace(meta=meta)

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

        # Transaction should fall back to fuzzy matching and match rent schedule
        matched_txn = result[0][1][0]
        assert matched_txn.meta["schedule_id"] == "rent"
        # Confidence should be less than 1.0 (fuzzy match, not perfect)
        confidence = float(matched_txn.meta["schedule_confidence"])
        assert confidence < 1.0


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


class TestLedgerTransactionMatching:
    """Tests for matching transactions already in the ledger."""

    def test_ledger_transaction_with_schedule_id_not_flagged_missing(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that ledger transactions with schedule_id are not flagged as missing."""
        # Create a ledger transaction with schedule_id
        ledger_meta = data.new_metadata("ledger.beancount", 10)
        ledger_meta["schedule_id"] = "rent"
        ledger_txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        ledger_txn = ledger_txn._replace(meta=ledger_meta)

        # Create schedule
        schedule = sample_schedule(
            id="rent",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        # No imported transactions - just the ledger
        extracted_entries = []

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[ledger_txn])

        # Should have no placeholders (transaction is already in ledger)
        assert len(result) == 0

    def test_ledger_transaction_without_schedule_id_allows_placeholder(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that ledger transactions without schedule_id don't prevent missing warnings."""
        # Create a ledger transaction WITHOUT schedule_id
        ledger_txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        # Create schedule
        schedule = sample_schedule(
            id="rent",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        # No imported transactions
        extracted_entries = []

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[ledger_txn])

        # Should still create a placeholder (ledger txn has no schedule_id)
        # Even though there's a transaction in the ledger, without schedule_id we can't confirm it's linked
        assert len(result) > 0
        assert result[0][0] == "<schedules>"
        assert len(result[0][1]) > 0

    def test_ledger_transaction_with_schedule_id_date_within_window(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that ledger transactions match even if date is within the date window."""
        # Create a ledger transaction on Jan 16 instead of Jan 15
        ledger_meta = data.new_metadata("ledger.beancount", 10)
        ledger_meta["schedule_id"] = "rent"
        ledger_txn = sample_transaction(
            date(2024, 1, 16),  # One day off
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        ledger_txn = ledger_txn._replace(meta=ledger_meta)

        # Create schedule with date window
        schedule = sample_schedule(
            id="rent",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )
        # Set date window to 3 days (default from config)

        extracted_entries = []

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[ledger_txn])

        # Should have no placeholders (ledger transaction matches within date window)
        assert len(result) == 0

    def test_ledger_transaction_with_unknown_schedule_id(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that ledger transactions with unknown schedule_id are ignored."""
        # Create a ledger transaction with non-existent schedule_id
        ledger_meta = data.new_metadata("ledger.beancount", 10)
        ledger_meta["schedule_id"] = "unknown_schedule"
        ledger_txn = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        ledger_txn = ledger_txn._replace(meta=ledger_meta)

        # Create a different schedule
        schedule = sample_schedule(
            id="rent",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        extracted_entries = []

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[ledger_txn])

        # Should still create placeholder (unknown schedule_id is ignored)
        assert len(result) > 0
        assert result[0][0] == "<schedules>"

    def test_ledger_and_imported_transactions_both_matched(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test that both ledger and imported transactions prevent missing warnings."""
        # Create a ledger transaction for Jan 15
        ledger_meta = data.new_metadata("ledger.beancount", 10)
        ledger_meta["schedule_id"] = "rent"
        ledger_txn_1 = sample_transaction(
            date(2024, 1, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )
        ledger_txn_1 = ledger_txn_1._replace(meta=ledger_meta)

        # Create an imported transaction for Feb 15
        imported_txn = sample_transaction(
            date(2024, 2, 15),
            "Landlord",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        # Create schedule
        schedule = sample_schedule(
            id="rent",
            payee_pattern="Landlord",
            amount=Decimal("-1500.00"),
        )

        extracted_entries = [
            ("checking.csv", [imported_txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[ledger_txn_1])

        # Should have no placeholders (both transactions matched)
        # Result will have the modified imported transaction
        assert len(result) == 1
        # The imported transaction should be matched
        matched_txn = result[0][1][0]
        assert matched_txn.meta["schedule_id"] == "rent"


class TestAmortizationEnrichment:
    """Tests for amortization integration in the beangulp hook."""

    def test_stateful_amortization_enrichment(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test stateful amortization enrichment using ledger balance."""
        from decimal import Decimal

        from beanschedule.schema import AmortizationConfig
        from beanschedule.types import CompoundingFrequency
        from tests.conftest import make_posting_template

        # Create schedule with stateful amortization (balance_from_ledger: True)
        amort_config = AmortizationConfig(
            annual_rate=Decimal("0.0675"),
            monthly_payment=Decimal("1995.68"),
            balance_from_ledger=True,
            compounding=CompoundingFrequency.MONTHLY,
        )

        # Create posting templates with roles
        postings = [
            make_posting_template("Assets:Bank:Checking", None, role="payment"),
            make_posting_template("Expenses:Housing:Interest", None, role="interest"),
            make_posting_template("Liabilities:Mortgage", None, role="principal"),
        ]

        schedule = sample_schedule(
            id="mortgage",
            payee_pattern="MORTGAGE BANK",
            amount=Decimal("-1995.68"),
            postings=postings,
        )
        schedule.amortization = amort_config

        # Create ledger entry: initial loan disbursement
        loan_init = data.Transaction(
            meta={"filename": "ledger.beancount", "lineno": 1},
            date=date(2024, 1, 1),
            flag="*",  # Cleared flag (P also works, but * is clearer)
            payee="Lender",
            narration="Loan disbursement",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account="Assets:Bank:Checking",
                    units=amount.Amount(Decimal("300000"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                data.Posting(
                    account="Liabilities:Mortgage",
                    units=amount.Amount(Decimal("-300000"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

        # Create imported transaction for first payment (Feb 15, for Feb 1 amortization)
        imported_txn = sample_transaction(
            date(2024, 2, 15),
            "MORTGAGE BANK",
            "Assets:Bank:Checking",
            Decimal("-1995.68"),
        )

        extracted_entries = [
            ("bank.csv", [imported_txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[loan_init])

        # Find the enriched transaction
        enriched_txn = result[0][1][0]

        # Verify amortization metadata is present
        assert "amortization_principal" in enriched_txn.meta
        assert "amortization_interest" in enriched_txn.meta
        assert "amortization_balance_after" in enriched_txn.meta
        assert "amortization_linked_date" in enriched_txn.meta

        # Verify the split is reasonable (stateful mode, second month)
        principal = Decimal(enriched_txn.meta["amortization_principal"])
        interest = Decimal(enriched_txn.meta["amortization_interest"])

        # Second payment should have slightly less interest than first
        assert principal > Decimal("0")
        assert interest > Decimal("1600")  # Still mostly interest
        total = principal + interest
        assert total == Decimal("1995.68")  # Should equal monthly payment

    def test_amortization_with_escrow(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Test amortization with explicit escrow postings."""
        from decimal import Decimal

        from beanschedule.schema import AmortizationConfig
        from beanschedule.types import CompoundingFrequency
        from tests.conftest import make_posting_template

        amort_config = AmortizationConfig(
            annual_rate=Decimal("0.0675"),
            monthly_payment=Decimal("1995.68"),
            balance_from_ledger=True,
            compounding=CompoundingFrequency.MONTHLY,
        )

        # Postings including escrow with explicit amount
        postings = [
            make_posting_template("Assets:Bank:Checking", None, role="payment"),
            make_posting_template("Expenses:Housing:Interest", None, role="interest"),
            make_posting_template("Liabilities:Mortgage", None, role="principal"),
            make_posting_template("Expenses:Housing:Insurance", Decimal("150"), role="escrow"),
        ]

        schedule = sample_schedule(
            id="mortgage",
            payee_pattern="MORTGAGE BANK",
            amount=Decimal("-2145.68"),
            postings=postings,
        )
        schedule.amortization = amort_config

        # Create ledger entry: initial loan
        loan_init = data.Transaction(
            meta={"filename": "ledger.beancount", "lineno": 1},
            date=date(2024, 1, 1),
            flag="*",
            payee="Lender",
            narration="Loan disbursement",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account="Assets:Bank:Checking",
                    units=amount.Amount(Decimal("300000"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                data.Posting(
                    account="Liabilities:Mortgage",
                    units=amount.Amount(Decimal("-300000"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

        imported_txn = sample_transaction(
            date(2024, 2, 15),
            "MORTGAGE BANK",
            "Assets:Bank:Checking",
            Decimal("-2145.68"),
        )

        extracted_entries = [
            ("bank.csv", [imported_txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries, existing_entries=[loan_init])

        enriched_txn = result[0][1][0]

        # Verify escrow posting has explicit amount
        escrow_posting = next(
            (p for p in enriched_txn.postings if p.account == "Expenses:Housing:Insurance"),
            None,
        )
        assert escrow_posting is not None
        assert escrow_posting.units.number == Decimal("150")

        # Verify P/I postings still have computed amounts
        interest_posting = next(p for p in enriched_txn.postings if p.account == "Expenses:Housing:Interest")
        principal_posting = next(p for p in enriched_txn.postings if p.account == "Liabilities:Mortgage")

        assert interest_posting.units.number > Decimal("0")
        assert principal_posting.units.number > Decimal("0")

    def test_no_amortization_unchanged(
        self, sample_transaction, sample_schedule, global_config
    ):
        """Regression test: non-amortization schedules are unchanged."""
        # Create regular schedule without amortization
        schedule = sample_schedule(
            id="rent",
            payee_pattern="LANDLORD",
            amount=Decimal("-1500.00"),
            postings=None,  # No postings, simple enrichment
        )

        imported_txn = sample_transaction(
            date(2024, 1, 15),
            "LANDLORD",
            "Assets:Bank:Checking",
            Decimal("-1500.00"),
        )

        extracted_entries = [
            ("bank.csv", [imported_txn], "Assets:Bank:Checking", None),
        ]

        schedule_file = ScheduleFile(schedules=[schedule], config=global_config)

        with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
            result = schedule_hook(extracted_entries)

        enriched_txn = result[0][1][0]

        # Should NOT have amortization metadata
        assert "amortization_principal" not in enriched_txn.meta
        assert "amortization_interest" not in enriched_txn.meta
        assert "amortization_balance_after" not in enriched_txn.meta

        # Should have standard schedule metadata
        assert enriched_txn.meta["schedule_id"] == "rent"
        assert "schedule_matched_date" in enriched_txn.meta
        assert "schedule_confidence" in enriched_txn.meta
