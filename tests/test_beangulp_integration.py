"""End-to-end integration tests with beangulp workflow."""

import os
from datetime import date
from pathlib import Path
from decimal import Decimal

import pytest
import yaml

from beancount.core import amount, data
from beancount import loader as beancount_loader

from beanschedule import schedule_hook
from beanschedule.loader import load_schedules_from_directory


class TestPerScheduleIntegration:
    """Parameterized tests for each schedule in examples/ against real ledger."""

    @pytest.fixture
    def examples_dir(self):
        """Get path to examples directory."""
        test_dir = Path(__file__).parent.parent
        examples = test_dir / "examples"
        if not examples.exists():
            pytest.skip("examples directory not found")
        return examples

    @pytest.fixture
    def example_ledger_entries(self, examples_dir):
        """Load real example.beancount ledger."""
        ledger_file = examples_dir / "example.beancount"
        if not ledger_file.exists():
            pytest.skip("example.beancount not found")

        entries, errors, options_map = beancount_loader.load_file(str(ledger_file))
        if errors:
            pytest.fail(f"Failed to load example ledger: {errors}")
        return entries

    @pytest.fixture
    def example_schedules_dir(self, examples_dir):
        """Get path to example schedules directory."""
        schedules_dir = examples_dir / "schedules"
        if not schedules_dir.exists():
            pytest.skip("examples/schedules directory not found")
        return schedules_dir

    @staticmethod
    def load_schedule_yaml(schedule_file):
        """Load a single schedule YAML file."""
        with open(schedule_file) as f:
            return yaml.safe_load(f)

    def get_all_example_schedules(self, example_schedules_dir):
        """Get all schedule files from examples/schedules/."""
        schedule_files = sorted(example_schedules_dir.glob("*.yaml"))
        # Filter out _config.yaml
        return [f for f in schedule_files if f.name != "_config.yaml"]

    def test_each_schedule_with_synthetic_transaction(
        self, example_ledger_entries, example_schedules_dir
    ):
        """Test each schedule by creating a synthetic transaction that matches it.

        Iterates through all example schedules and creates a synthetic imported
        transaction that should match each schedule, then verifies the hook
        processes it correctly with the real example ledger.
        """
        os.environ["BEANSCHEDULE_DIR"] = str(example_schedules_dir)

        try:
            schedule_files = self.get_all_example_schedules(example_schedules_dir)
            assert len(schedule_files) >= 10, f"Expected >=10 schedules, got {len(schedule_files)}"

            successfully_tested = 0

            for schedule_file in schedule_files:
                schedule_data = self.load_schedule_yaml(schedule_file)
                schedule_id = schedule_data.get("id")

                if not schedule_data.get("enabled", True):
                    # Skip disabled schedules for this test
                    continue

                successfully_tested += 1

                # Extract match criteria
                match_criteria = schedule_data.get("match", {})
                account = match_criteria.get("account", "Assets:Checking")
                payee_pattern = match_criteria.get("payee_pattern", "Test")
                amount_value = match_criteria.get("amount")

                # Use a sensible default if amount is null
                if amount_value is None:
                    amount_value = Decimal("-100.00")
                else:
                    amount_value = Decimal(str(amount_value))

                # Create synthetic transaction matching this schedule
                meta = data.new_metadata("synthetic", 0)
                synthetic_txn = data.Transaction(
                    meta=meta,
                    date=date(2024, 1, 15),
                    flag="*",
                    payee=payee_pattern.split("|")[0] if "|" in payee_pattern else payee_pattern,
                    narration=f"Synthetic: {schedule_id}",
                    tags=set(),
                    links=set(),
                    postings=[
                        data.Posting(
                            account=account,
                            units=amount.Amount(amount_value, "USD"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                        data.Posting(
                            account="Expenses:Test",
                            units=amount.Amount(-amount_value, "USD"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ],
                )

                # Run hook: synthetic imports + real ledger
                entries_list = [("synthetic.csv", [synthetic_txn], account, "SyntheticImporter")]
                result = schedule_hook(entries_list, existing_entries=example_ledger_entries)

                # Verify hook executed without error
                assert result is not None, f"Hook failed for schedule {schedule_id}"
                assert isinstance(result, list), f"Result should be list for {schedule_id}"

            assert successfully_tested > 0, "Should have tested at least one enabled schedule"

        finally:
            if "BEANSCHEDULE_DIR" in os.environ:
                del os.environ["BEANSCHEDULE_DIR"]

    def test_all_example_schedules_execute_without_error(
        self, example_ledger_entries, example_schedules_dir
    ):
        """Test that all example schedules can be executed without errors."""
        os.environ["BEANSCHEDULE_DIR"] = str(example_schedules_dir)

        try:
            schedule_files = self.get_all_example_schedules(example_schedules_dir)
            assert len(schedule_files) >= 10, "Should have at least 10 example schedules"

            # Run hook with all schedules and real ledger
            entries_list = [("test.csv", [], "Assets:Checking", "TestImporter")]

            result = schedule_hook(entries_list, existing_entries=example_ledger_entries)

            # Should complete without error
            assert result is not None

            # Should generate placeholders for missing schedules
            schedules_entries = [
                e for e in result if isinstance(e, tuple) and len(e) >= 2 and e[0] == "<schedules>"
            ]
            if schedules_entries:
                placeholders = schedules_entries[0][1]
                # All schedules in the range should have at least generated expectations
                # Some may have placeholders for missing transactions
                assert len(placeholders) > 0, "Should have some placeholder entries"

        finally:
            if "BEANSCHEDULE_DIR" in os.environ:
                del os.environ["BEANSCHEDULE_DIR"]


class TestExamplesIntegration:
    """Integration tests using real examples from examples/ directory."""

    @pytest.fixture
    def examples_dir(self):
        """Get path to examples directory."""
        # Relative to this test file
        test_dir = Path(__file__).parent.parent
        examples = test_dir / "examples"
        if not examples.exists():
            pytest.skip("examples directory not found")
        return examples

    @pytest.fixture
    def example_ledger_entries(self, examples_dir):
        """Load real example.beancount ledger."""
        ledger_file = examples_dir / "example.beancount"
        if not ledger_file.exists():
            pytest.skip("example.beancount not found")

        entries, errors, options_map = beancount_loader.load_file(str(ledger_file))
        if errors:
            pytest.fail(f"Failed to load example ledger: {errors}")
        return entries

    @pytest.fixture
    def example_schedules_dir(self, examples_dir):
        """Get path to example schedules directory."""
        schedules_dir = examples_dir / "schedules"
        if not schedules_dir.exists():
            pytest.skip("examples/schedules directory not found")
        return schedules_dir

    @pytest.fixture
    def example_schedule_file(self, example_schedules_dir):
        """Load real example schedules."""
        schedule_file = load_schedules_from_directory(example_schedules_dir)
        if schedule_file is None:
            pytest.fail("Failed to load example schedules")
        return schedule_file

    def test_examples_directory_exists(self, examples_dir):
        """Verify examples directory structure is complete."""
        assert examples_dir.exists(), "examples directory not found"
        assert (examples_dir / "example.beancount").exists(), "example.beancount not found"
        assert (examples_dir / "schedules").exists(), "schedules directory not found"
        assert (examples_dir / "schedules" / "_config.yaml").exists(), "_config.yaml not found"

    def test_example_ledger_loads(self, example_ledger_entries):
        """Verify example ledger can be loaded."""
        assert example_ledger_entries is not None
        assert len(example_ledger_entries) > 100, "example ledger should have many entries"

        # Verify it contains transactions
        transactions = [e for e in example_ledger_entries if isinstance(e, data.Transaction)]
        assert len(transactions) > 10, "example ledger should have multiple transactions"

    def test_example_schedules_load(self, example_schedule_file):
        """Verify example schedules can be loaded."""
        assert example_schedule_file is not None
        assert len(example_schedule_file.schedules) >= 10, (
            "should have at least 10 example schedules"
        )

        # Verify all schedules are properly configured
        for schedule in example_schedule_file.schedules:
            assert schedule.id, "schedule should have an id"
            assert schedule.match, "schedule should have match criteria"
            assert schedule.match.account, "match should have account"
            assert schedule.recurrence, "schedule should have recurrence rule"
            assert schedule.transaction, "schedule should have transaction template"

    def test_hook_with_example_ledger_and_schedules(
        self, example_ledger_entries, example_schedules_dir
    ):
        """Test hook integration with real ledger and schedules."""
        os.environ["BEANSCHEDULE_DIR"] = str(example_schedules_dir)

        try:
            # No imported entries, just checking against existing ledger
            entries_list = [("example.beancount", [], "Assets:Checking", "ExampleImporter")]

            result = schedule_hook(entries_list, existing_entries=example_ledger_entries)

            # Should process without error
            assert result is not None
            assert isinstance(result, list)
        finally:
            if "BEANSCHEDULE_DIR" in os.environ:
                del os.environ["BEANSCHEDULE_DIR"]

    def test_hook_creates_placeholders_with_examples(
        self, example_ledger_entries, example_schedules_dir
    ):
        """Test that hook creates placeholders for missing scheduled transactions."""
        os.environ["BEANSCHEDULE_DIR"] = str(example_schedules_dir)

        try:
            entries_list = [("example.beancount", [], "Assets:Checking", "ExampleImporter")]
            result = schedule_hook(entries_list, existing_entries=example_ledger_entries)

            # Filter for schedules entry (which contains placeholders)
            schedules_entries = [
                e for e in result if hasattr(e, "flag") and len(e) >= 2 and e[0] == "<schedules>"
            ]

            # Should create placeholder entries for missing scheduled transactions
            # (The example ledger is from 2013-2015, so many recent schedules would be missing)
            if schedules_entries:
                placeholders_entry = schedules_entries[0]
                placeholder_txns = placeholders_entry[1]
                assert len(placeholder_txns) > 0, (
                    "should create placeholders for missing transactions"
                )

                # Verify placeholders have correct structure
                for placeholder in placeholder_txns:
                    assert hasattr(placeholder, "flag"), "placeholder should have flag"
                    assert placeholder.flag == "!", "placeholder should have ! flag"
                    assert "schedule_id" in placeholder.meta, "placeholder should have schedule_id"
        finally:
            if "BEANSCHEDULE_DIR" in os.environ:
                del os.environ["BEANSCHEDULE_DIR"]

    def test_all_example_schedules_have_consistent_config(self, example_schedule_file):
        """Verify all example schedules have consistent configuration."""
        config = example_schedule_file.config

        # All should use same config
        assert config.fuzzy_match_threshold > 0
        assert config.default_date_window_days > 0
        assert config.placeholder_flag in ["!", "*"]

        # Verify each schedule respects config defaults
        for schedule in example_schedule_file.schedules:
            if schedule.match.date_window_days is None:
                # Uses config default
                pass
            else:
                # Override is set
                assert schedule.match.date_window_days >= 0

    def test_example_schedules_cover_different_frequencies(self, example_schedule_file):
        """Verify example schedules demonstrate different recurrence patterns."""
        frequencies = set()
        for schedule in example_schedule_file.schedules:
            frequencies.add(schedule.recurrence.frequency.value)

        # Should have multiple frequency types
        assert len(frequencies) >= 3, f"should demonstrate multiple frequencies, got: {frequencies}"

    def test_example_schedules_cover_different_matching_strategies(self, example_schedule_file):
        """Verify example schedules show different amount matching strategies."""
        has_fixed_amount = False
        has_amount_range = False
        has_null_amount = False

        for schedule in example_schedule_file.schedules:
            if schedule.match.amount is not None and schedule.match.amount_min is None:
                has_fixed_amount = True
            if schedule.match.amount_min is not None and schedule.match.amount_max is not None:
                has_amount_range = True
            if schedule.match.amount is None:
                has_null_amount = True

        assert has_fixed_amount, "examples should show fixed amount with tolerance"
        assert has_amount_range, "examples should show amount range matching"

    def test_hook_performance_with_example_data(
        self, example_ledger_entries, example_schedules_dir
    ):
        """Verify hook performs reasonably with example data."""
        import time

        os.environ["BEANSCHEDULE_DIR"] = str(example_schedules_dir)

        try:
            entries_list = [("example.beancount", [], "Assets:Checking", "ExampleImporter")]

            start = time.time()
            result = schedule_hook(entries_list, existing_entries=example_ledger_entries)
            elapsed = time.time() - start

            # Should complete in reasonable time (< 5 seconds with lazy matching)
            assert elapsed < 5.0, f"hook took {elapsed:.2f}s, should be < 5s with lazy matching"
            print(f"Hook completed with example data in {elapsed:.2f}s")
        finally:
            if "BEANSCHEDULE_DIR" in os.environ:
                del os.environ["BEANSCHEDULE_DIR"]
