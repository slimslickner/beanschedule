"""Tests for pending transaction support."""

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from beancount.core import amount as bc_amount
from beancount.core import data

from beanschedule.schema import Posting
from beanschedule.pending import (
    PendingTransaction,
    enrich_from_pending,
    find_pending_file,
    is_pending_marker,
    load_pending_transactions,
    match_pending_transaction,
    remove_pending_transactions,
)


class TestPendingTransaction:
    """Test PendingTransaction model."""

    def test_create_valid(self):
        """Test creating valid pending transaction."""
        pending = PendingTransaction(
            date=date(2026, 2, 20),
            account="Assets:Checking",
            amount=Decimal("-89.99"),
            payee="Amazon",
            narration="Wireless headphones",
            postings=[
                Posting(
                    account="Assets:Checking",
                    amount=Decimal("-89.99"),
                ),
                Posting(
                    account="Expenses:Electronics:Audio",
                    amount=Decimal("85.00"),
                    narration="Bose QuietComfort 45",
                ),
                Posting(
                    account="Expenses:Shopping:Shipping",
                    amount=Decimal("4.99"),
                ),
            ],
        )

        assert pending.date == date(2026, 2, 20)
        assert pending.account == "Assets:Checking"
        assert pending.amount == Decimal("-89.99")
        assert pending.payee == "Amazon"
        assert len(pending.postings) == 3


class TestIsPendingMarker:
    """Test is_pending_marker function."""

    def test_pending_tag_is_pending(self):
        """Test #pending tag marks as pending."""
        txn = data.Transaction(
            meta={"lineno": 1},
            date=date(2026, 2, 20),
            flag="!",
            payee="Test",
            narration="Test",
            tags=frozenset(["pending"]),
            links=frozenset(),
            postings=[],
        )
        assert is_pending_marker(txn)

    def test_normal_transaction_not_pending(self):
        """Test normal transaction is not marked as pending."""
        txn = data.Transaction(
            meta={"lineno": 1},
            date=date(2026, 2, 20),
            flag="*",
            payee="Test",
            narration="Test",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )
        assert not is_pending_marker(txn)

    def test_different_tag_not_pending(self):
        """Test other tags don't mark as pending."""
        txn = data.Transaction(
            meta={"lineno": 1},
            date=date(2026, 2, 20),
            flag="*",
            payee="Test",
            narration="Test",
            tags=frozenset(["other-tag"]),
            links=frozenset(),
            postings=[],
        )
        assert not is_pending_marker(txn)


class TestLoadPendingTransactions:
    """Test loading pending transactions from file."""

    def test_load_valid_file(self):
        """Test loading valid pending transactions file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".beancount", delete=False) as f:
            f.write("""
2026-02-20 ! "Amazon" "Wireless headphones"
  #pending
  Assets:Checking  -89.99 USD
  Expenses:Electronics:Audio  85.00 USD
    narration: "Bose QuietComfort 45"
  Expenses:Shopping:Shipping  4.99 USD

2026-02-22 ! "Whole Foods" "Groceries"
  #pending
  Assets:Checking  -127.45 USD
  Expenses:Food:Groceries  127.45 USD
""")
            f.flush()
            file_path = Path(f.name)

        try:
            pending = load_pending_transactions(file_path)
            assert len(pending) == 2
            assert pending[0].payee == "Amazon"
            assert pending[0].amount == Decimal("-89.99")
            assert len(pending[0].postings) == 3
            assert pending[1].payee == "Whole Foods"
        finally:
            file_path.unlink()

    def test_load_nonexistent_file(self):
        """Test loading nonexistent file returns empty list."""
        pending = load_pending_transactions(Path("/nonexistent/file.beancount"))
        assert pending == []

    def test_load_file_with_non_pending(self):
        """Test loading file ignores non-pending transactions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".beancount", delete=False) as f:
            f.write("""
2026-02-20 * "Normal transaction"
  Assets:Checking  -50.00 USD
  Expenses:Food

2026-02-20 ! "Amazon" "Pending transaction"
  #pending
  Assets:Checking  -89.99 USD
  Expenses:Electronics  89.99 USD
""")
            f.flush()
            file_path = Path(f.name)

        try:
            pending = load_pending_transactions(file_path)
            assert len(pending) == 1
            assert pending[0].payee == "Amazon"
        finally:
            file_path.unlink()


class TestMatchPendingTransaction:
    """Test pending transaction matching."""

    def _make_pending(
        self,
        date=date(2026, 2, 20),
        account="Assets:Checking",
        amount=Decimal("-89.99"),
    ):
        """Helper to create pending transaction."""
        return PendingTransaction(
            date=date,
            account=account,
            amount=amount,
            payee="Test Payee",
            narration="Test",
            postings=[],
        )

    def _make_txn(
        self,
        date=date(2026, 2, 20),
        account="Assets:Checking",
        amount=Decimal("-89.99"),
    ):
        """Helper to create imported transaction."""
        return data.Transaction(
            meta={"lineno": 1},
            date=date,
            flag="*",
            payee="Test Payee",
            narration="Test",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account=account,
                    units=bc_amount.Amount(amount, "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

    def test_exact_match(self):
        """Test exact match on account + amount + date."""
        pending = self._make_pending()
        txn = self._make_txn()

        result = match_pending_transaction(txn, [pending])

        assert result == pending

    def test_no_match_different_account(self):
        """Test no match when account differs."""
        pending = self._make_pending(account="Assets:Checking")
        txn = self._make_txn(account="Assets:Savings")

        result = match_pending_transaction(txn, [pending])

        assert result is None

    def test_no_match_different_amount(self):
        """Test no match when amount differs."""
        pending = self._make_pending(amount=Decimal("-89.99"))
        txn = self._make_txn(amount=Decimal("-90.00"))

        result = match_pending_transaction(txn, [pending])

        assert result is None

    def test_no_match_outside_window(self):
        """Test no match when date outside 4-day window."""
        pending = self._make_pending(date=date(2026, 2, 20))
        txn = self._make_txn(date=date(2026, 2, 25))  # 5 days diff

        result = match_pending_transaction(txn, [pending])

        assert result is None

    def test_match_within_window(self):
        """Test match when date within 4-day window."""
        pending = self._make_pending(date=date(2026, 2, 20))
        txn = self._make_txn(date=date(2026, 2, 22))  # 2 days diff

        result = match_pending_transaction(txn, [pending])

        assert result == pending

    def test_match_at_window_edge(self):
        """Test match at 4-day window boundary."""
        pending = self._make_pending(date=date(2026, 2, 20))
        txn_future = self._make_txn(date=date(2026, 2, 24))  # Exactly 4 days later
        txn_past = self._make_txn(date=date(2026, 2, 16))  # Exactly 4 days earlier

        assert match_pending_transaction(txn_future, [pending]) == pending
        assert match_pending_transaction(txn_past, [pending]) == pending

    def test_match_multiple_candidates_returns_first(self):
        """Test matching against multiple pending transactions."""
        pending1 = self._make_pending(amount=Decimal("-100.00"))
        pending2 = self._make_pending(amount=Decimal("-89.99"))
        pending3 = self._make_pending(amount=Decimal("-50.00"))

        txn = self._make_txn(amount=Decimal("-89.99"))

        result = match_pending_transaction(txn, [pending1, pending2, pending3])

        assert result == pending2

    def test_no_match_empty_list(self):
        """Test no match against empty pending list."""
        txn = self._make_txn()

        result = match_pending_transaction(txn, [])

        assert result is None

    def test_no_match_transaction_no_postings(self):
        """Test no match for transaction without postings."""
        pending = self._make_pending()
        txn = data.Transaction(
            meta={"lineno": 1},
            date=date(2026, 2, 20),
            flag="*",
            payee="Test",
            narration="Test",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        result = match_pending_transaction(txn, [pending])

        assert result is None


class TestEnrichFromPending:
    """Test enriching transaction with pending template."""

    def test_apply_pending_postings(self):
        """Test applying pending postings to transaction."""
        pending = PendingTransaction(
            date=date(2026, 2, 20),
            account="Assets:Checking",
            amount=Decimal("-89.99"),
            payee="Amazon",
            narration="Headphones",
            postings=[
                Posting(
                    account="Assets:Checking",
                    amount=Decimal("-89.99"),
                ),
                Posting(
                    account="Expenses:Electronics:Audio",
                    amount=Decimal("85.00"),
                    narration="Bose QuietComfort 45",
                ),
                Posting(
                    account="Expenses:Shopping:Shipping",
                    amount=Decimal("4.99"),
                    narration="Shipping",
                ),
            ],
        )

        txn = data.Transaction(
            meta={"lineno": 1},
            date=date(2026, 2, 22),
            flag="*",
            payee="AMAZON.COM CHARGE",
            narration="Unknown purchase",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account="Assets:Checking",
                    units=bc_amount.Amount(Decimal("-89.99"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

        enriched = enrich_from_pending(txn, pending)

        assert enriched.payee == "Amazon"
        assert enriched.narration == "Headphones"
        assert len(enriched.postings) == 3
        assert enriched.postings[1].account == "Expenses:Electronics:Audio"
        assert enriched.postings[1].units.number == Decimal("85.00")
        assert enriched.postings[1].meta["narration"] == "Bose QuietComfort 45"
        assert enriched.meta["matched_pending"] == "true"

    def test_posting_narrations_preserved(self):
        """Test posting narrations are preserved."""
        pending = PendingTransaction(
            date=date(2026, 2, 20),
            account="Assets:Checking",
            amount=Decimal("-127.45"),
            payee="Store",
            narration="Purchase",
            postings=[
                Posting(account="Assets:Checking", amount=Decimal("-127.45")),
                Posting(
                    account="Expenses:Food:Groceries",
                    amount=Decimal("100.00"),
                    narration="Food items",
                ),
                Posting(
                    account="Expenses:Supplies",
                    amount=Decimal("27.45"),
                    narration="Household supplies",
                ),
            ],
        )

        txn = data.Transaction(
            meta={"lineno": 1},
            date=date(2026, 2, 20),
            flag="*",
            payee="STORE",
            narration="Purchase",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account="Assets:Checking",
                    units=bc_amount.Amount(Decimal("-127.45"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

        enriched = enrich_from_pending(txn, pending)

        assert enriched.postings[1].meta["narration"] == "Food items"
        assert enriched.postings[2].meta["narration"] == "Household supplies"


class TestRemovePendingTransactions:
    """Test removing pending transactions from file."""

    def test_remove_single_transaction(self):
        """Test removing a single pending transaction."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".beancount", delete=False) as f:
            f.write("""
2026-02-20 ! "Amazon" "Headphones"
  #pending
  Assets:Checking  -89.99 USD
  Expenses:Electronics  89.99 USD

2026-02-22 ! "Store" "Groceries"
  #pending
  Assets:Checking  -50.00 USD
  Expenses:Food  50.00 USD
""")
            f.flush()
            file_path = Path(f.name)

        try:
            # Verify both transactions exist
            pending = load_pending_transactions(file_path)
            assert len(pending) == 2

            # Create matching transaction to remove
            remove_txn = data.Transaction(
                meta={"lineno": 1},
                date=date(2026, 2, 20),
                flag="!",
                payee="Amazon",
                narration="Headphones",
                tags=frozenset(),
                links=frozenset(),
                postings=[
                    data.Posting(
                        account="Assets:Checking",
                        units=bc_amount.Amount(Decimal("-89.99"), "USD"),
                        cost=None,
                        price=None,
                        flag=None,
                        meta=None,
                    ),
                ],
            )

            # Remove first one
            remove_pending_transactions(file_path, [remove_txn])

            # Verify only second remains
            pending = load_pending_transactions(file_path)
            assert len(pending) == 1
            assert pending[0].payee == "Store"
        finally:
            file_path.unlink()

    def test_remove_multiple_transactions(self):
        """Test removing multiple pending transactions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".beancount", delete=False) as f:
            f.write("""
2026-02-20 ! "Amazon" "Item 1"
  #pending
  Assets:Checking  -10.00 USD
  Expenses:Test  10.00 USD

2026-02-20 ! "Store" "Item 2"
  #pending
  Assets:Checking  -20.00 USD
  Expenses:Test  20.00 USD

2026-02-20 ! "Shop" "Item 3"
  #pending
  Assets:Checking  -30.00 USD
  Expenses:Test  30.00 USD
""")
            f.flush()
            file_path = Path(f.name)

        try:
            # Create matching transactions to remove
            remove_txns = [
                data.Transaction(
                    meta={"lineno": 1},
                    date=date(2026, 2, 20),
                    flag="!",
                    payee="Amazon",
                    narration="Item 1",
                    tags=frozenset(),
                    links=frozenset(),
                    postings=[
                        data.Posting(
                            account="Assets:Checking",
                            units=bc_amount.Amount(Decimal("-10.00"), "USD"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ],
                ),
                data.Transaction(
                    meta={"lineno": 1},
                    date=date(2026, 2, 20),
                    flag="!",
                    payee="Shop",
                    narration="Item 3",
                    tags=frozenset(),
                    links=frozenset(),
                    postings=[
                        data.Posting(
                            account="Assets:Checking",
                            units=bc_amount.Amount(Decimal("-30.00"), "USD"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ],
                ),
            ]

            remove_pending_transactions(file_path, remove_txns)

            pending = load_pending_transactions(file_path)
            assert len(pending) == 1
            assert pending[0].payee == "Store"
        finally:
            file_path.unlink()

    def test_remove_nonexistent_transaction(self):
        """Test removing nonexistent transaction doesn't error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".beancount", delete=False) as f:
            f.write("""
2026-02-20 ! "Amazon" "Headphones"
  #pending
  Assets:Checking  -89.99 USD
  Expenses:Electronics  89.99 USD
""")
            f.flush()
            file_path = Path(f.name)

        try:
            # Create non-matching transaction
            remove_txn = data.Transaction(
                meta={"lineno": 1},
                date=date(2026, 2, 20),
                flag="!",
                payee="Other",
                narration="Other",
                tags=frozenset(),
                links=frozenset(),
                postings=[
                    data.Posting(
                        account="Assets:Checking",
                        units=bc_amount.Amount(Decimal("-50.00"), "USD"),
                        cost=None,
                        price=None,
                        flag=None,
                        meta=None,
                    ),
                ],
            )

            # Should not error
            remove_pending_transactions(file_path, [remove_txn])

            # Original transaction should still exist
            pending = load_pending_transactions(file_path)
            assert len(pending) == 1
        finally:
            file_path.unlink()


class TestFindPendingFile:
    """Test finding pending file."""

    def test_find_in_current_directory(self, tmp_path, monkeypatch):
        """Test finding pending.beancount in current directory."""
        # Create pending file
        pending_file = tmp_path / "pending.beancount"
        pending_file.write_text("")

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        found = find_pending_file()

        assert found is not None
        assert found.name == "pending.beancount"
        assert found.resolve() == pending_file.resolve()

    def test_find_via_env_variable(self, tmp_path, monkeypatch):
        """Test finding pending file via environment variable."""
        pending_file = tmp_path / "my-pending.beancount"
        pending_file.write_text("")

        monkeypatch.setenv("BEANSCHEDULE_PENDING", str(pending_file))

        found = find_pending_file()

        assert found == pending_file

    def test_not_found_returns_none(self, tmp_path, monkeypatch):
        """Test returns None when file not found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("BEANSCHEDULE_PENDING", raising=False)

        found = find_pending_file()

        assert found is None
