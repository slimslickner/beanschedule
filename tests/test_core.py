"""Core computation, parsing, diagnostics and matching tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from beancount.parser import parser

from beanschedule.core import (
    Amortization,
    Rule,
    amortization_splits,
    assign,
    compute,
    ledger_balance,
    resolve_nominal,
    walk_balance,
)

D = Decimal

BASE = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Expenses:X
2020-01-01 open Equity:Opening
2025-12-31 * "Opening"
  Assets:Bank      1000.00 USD
  Equity:Opening  -1000.00 USD
"""


def _codes(result) -> list[str]:
    return [diagnostic.code for diagnostic in result.diagnostics]


def _rule(  # noqa: PLR0913 - a test helper mirroring the rule's fields
    *,
    end: date | None = None,
    match_payee: str | None = None,
    match_amount: Decimal | None = None,
    amount_mode: str = "any",
    amount_tolerance: Decimal | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    window_before: int = 3,
    window_after: int = 3,
    amortization: Amortization | None = None,
) -> Rule:
    return Rule(
        id="rent",
        declared=date(2026, 1, 1),
        rrule="FREQ=MONTHLY;BYMONTHDAY=1",
        start=date(2026, 1, 1),
        end=end,
        match_account="Assets:Bank",
        match_payee=match_payee,
        match_amount=match_amount,
        amount_mode=amount_mode,
        amount_tolerance=amount_tolerance,
        amount_min=amount_min,
        amount_max=amount_max,
        window_before=window_before,
        window_after=window_after,
        amortization=amortization,
    )


def _txn(text: str):
    entries, _errors, _options = parser.parse_string(text)
    return entries[0]


# --- Fixture ledgers -----------------------------------------------------------


def test_basic_posts_and_next(load_result) -> None:
    result = load_result("basic.bean", today=date(2026, 2, 1))
    assert result.diagnostics == ()
    report = result.report("paycheck")
    assert report is not None
    assert report.next == date(2026, 2, 15)
    assert report.overdue == ()
    january = report.occurrence(date(2026, 1, 15))
    assert january is not None
    assert january.resolved
    assert january.posted is not None


def test_overdue_and_outcomes(load_result) -> None:
    result = load_result("stale.bean", today=date(2026, 4, 15))
    assert "W001" in _codes(result)
    report = result.report("rent")
    assert report is not None
    assert report.overdue == (date(2026, 1, 1), date(2026, 4, 1))
    assert report.next == date(2026, 1, 1)
    assert report.occurrence(date(2026, 2, 1)).skipped
    assert report.occurrence(date(2026, 3, 1)).moved_to == date(2026, 3, 20)


def test_no_today_skips_overdue(load_result) -> None:
    result = load_result("stale.bean")
    assert "W001" not in _codes(result)
    assert result.report("rent").overdue == ()


# --- Diagnostics ---------------------------------------------------------------


def test_missing_metadata(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n  start: 2026-01-01\n'
    )
    assert set(_codes(result)) == {"E001"}
    assert len(result.rules) == 0


def test_invalid_rrule(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "EVERY DAY"\n  start: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n'
    )
    assert _codes(result) == ["E002"]


def test_duplicate_id(compute_string) -> None:
    rule = (
        'custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n  start: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n'
    )
    result = compute_string(BASE + "2026-01-01 " + rule + "2026-02-01 " + rule)
    assert "E003" in _codes(result)
    assert len(result.rules) == 1


def test_unknown_skip(compute_string) -> None:
    result = compute_string(BASE + '2026-01-01 custom "schedule" "skip" "nope"')
    assert _codes(result) == ["E004"]


def test_skip_off_sequence(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"\n  start: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n'
        + '2026-01-02 custom "schedule" "skip" "rent"'
    )
    assert "E005" in _codes(result)


def test_outside_window_skip(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"\n  start: 2026-01-01\n'
        "  end: 2026-03-01\n"
        '  match-account: "Assets:Bank"\n'
        + '2026-06-01 custom "schedule" "skip" "rent"'
    )
    assert "W002" in _codes(result)


def test_bad_amount_mode(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n  start: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n  amount-mode: "fuzzy"\n'
    )
    assert "E006" in _codes(result)


def test_far_future_date_does_not_overflow(compute_string) -> None:
    result = compute_string(
        BASE + '9999-12-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n  start: 9999-12-01\n'
        '  match-account: "Assets:Bank"\n'
    )
    assert result.rule("rent") is not None


def test_far_future_directive_does_not_inflate_the_horizon(compute_string) -> None:
    result = compute_string(
        BASE
        + '9998-01-01 custom "note" "a far-future directive"\n'
        + '2013-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n  start: 2013-01-15\n'
        '  match-account: "Assets:Bank"\n  amount-mode: "any"\n'
    )
    report = result.report("rent")
    assert report is not None
    # The horizon is a fixed span from the reference date, not the ledger's max
    # date, so a far-future directive cannot expand the series (it was ~95,000
    # occurrences per rule before).
    assert len(report.occurrences) < 1000


def test_end_before_start(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n  start: 2026-05-01\n  end: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n'
    )
    assert "E009" in _codes(result)


def test_currency_mismatch(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "rent"\n'
        '  rrule: "FREQ=MONTHLY"\n  start: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n  match-amount: 100.00 EUR\n'
    )
    assert "E008" in _codes(result)


def test_malformed_amortization(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "loan"\n'
        '  rrule: "FREQ=MONTHLY"\n  start: 2026-01-01\n'
        '  match-account: "Assets:Bank"\n  method: "static"\n  rate: 0.05\n'
    )
    assert "E001" in _codes(result)


# --- Matching ------------------------------------------------------------------


def test_assign_on_time() -> None:
    txn = _txn(
        '2026-02-03 * "Rent"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    links = assign(_rule(), [date(2026, 1, 1), date(2026, 2, 1)], [txn])
    assert [link.nominal for link in links] == [date(2026, 2, 1)]


def test_assign_beyond_half_gap_consumes_later() -> None:
    txn = _txn(
        '2026-02-20 * "Rent"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    links = assign(
        _rule(window_before=20, window_after=20),
        [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)],
        [txn],
    )
    assert [link.nominal for link in links] == [date(2026, 3, 1)]


def test_assign_respects_window() -> None:
    txn = _txn(
        '2026-02-20 * "Rent"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    links = assign(_rule(window_before=1, window_after=1), [date(2026, 2, 1)], [txn])
    assert links == ()


def test_assign_payee_gate() -> None:
    txn = _txn(
        '2026-02-03 * "Someone"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    rule = _rule(match_payee="LANDLORD")
    assert assign(rule, [date(2026, 2, 1)], [txn]) == ()


def test_assign_amount_modes() -> None:
    txn = _txn(
        '2026-02-03 * "Rent"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    exact = _rule(match_amount=D("-1000.00"), amount_mode="exact")
    assert assign(exact, [date(2026, 2, 1)], [txn])
    approx = _rule(
        match_amount=D("-1000.00"),
        amount_mode="approx",
        amount_tolerance=D("5.00"),
    )
    assert assign(approx, [date(2026, 2, 1)], [txn])
    ranged = _rule(amount_mode="range", amount_min=D("-1100"), amount_max=D("-900"))
    assert assign(ranged, [date(2026, 2, 1)], [txn])
    miss = _rule(match_amount=D("-500.00"), amount_mode="exact")
    assert assign(miss, [date(2026, 2, 1)], [txn]) == ()


def test_assign_each_transaction_once() -> None:
    first = _txn(
        '2026-01-02 * "Rent"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    second = _txn(
        '2026-02-02 * "Rent"\n  Assets:Bank  -1000.00 USD\n  Expenses:X  1000.00 USD\n'
    )
    links = assign(_rule(), [date(2026, 1, 1), date(2026, 2, 1)], [first, second])
    assert [link.transaction.date for link in links] == [
        date(2026, 1, 2),
        date(2026, 2, 2),
    ]


def test_resolve_nominal_nearest() -> None:
    assert resolve_nominal(_rule(), date(2026, 3, 30)) == date(2026, 4, 1)


def test_resolve_nominal_outside_series() -> None:
    rule = _rule(end=date(2026, 3, 1))
    assert resolve_nominal(rule, date(2026, 9, 1)) is None


# --- Amortization --------------------------------------------------------------


def test_static_amortization(load_ledger) -> None:
    entries, _options = load_ledger("amortized.bean")
    result = compute(entries, {"operating_currency": "USD"})
    rule = result.rule("loan")
    assert rule is not None
    splits = amortization_splits(
        rule, rule.nominal_dates(until=date(2026, 3, 1)), entries
    )
    first = splits[date(2026, 1, 1)]
    assert first.principal > 0
    assert first.interest > 0
    assert first.total == first.principal + first.interest


def test_static_amortization_of_a_subset(load_ledger) -> None:
    entries, _options = load_ledger("amortized.bean")
    result = compute(entries, {"operating_currency": "USD"})
    rule = result.rule("loan")
    assert rule is not None
    nominals = rule.nominal_dates(until=date(2026, 6, 1))
    subset = [nominals[2], nominals[4]]
    splits = amortization_splits(rule, subset, entries)
    assert splits[subset[0]].payment_number == 3
    assert splits[subset[1]].payment_number == 5


def test_ledger_balance_and_walk() -> None:
    ledger = """option "operating_currency" "USD"
2020-01-01 open Assets:Bank
2020-01-01 open Liabilities:Loan
2025-12-31 * "Loan"
  Assets:Bank       10000.00 USD
  Liabilities:Loan -10000.00 USD
"""
    entries, _errors, _options = parser.parse_string(ledger)
    observed = ledger_balance(entries, "Liabilities:Loan")
    assert observed is not None
    balance, observed_date = observed
    assert balance == D("10000.00")
    assert observed_date == date(2025, 12, 31)
    rule = _rule(
        match_amount=D("-1000.00"),
        amount_mode="exact",
        amortization=Amortization(
            method="balance-from-ledger",
            rate=D("0.06"),
            principal_account="Liabilities:Loan",
        ),
    )
    split = walk_balance(rule, balance, observed_date, [date(2026, 1, 1)])
    assert split[date(2026, 1, 1)].interest == D("50.00")
    assert split[date(2026, 1, 1)].balance_after == D("9050.00")


def test_ledger_balance_untracked() -> None:
    entries, _errors, _options = parser.parse_string(
        'option "operating_currency" "USD"\n'
    )
    assert ledger_balance(entries, "Liabilities:None") is None


# --- Declared postings ---------------------------------------------------------


def _paycheck_rule(*postings: str) -> str:
    return (
        BASE + '2026-01-01 custom "schedule" "new" "paycheck"\n'
        '  rrule: "FREQ=MONTHLY"\n'
        "  start: 2026-01-01\n"
        '  match-account: "Assets:Bank"\n'
        "  match-amount: -3000.00\n"
        '  amount-mode: "exact"\n' + "".join(postings)
    )


def test_valid_posting_split(compute_string) -> None:
    result = compute_string(
        _paycheck_rule(
            '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Taxes"\n'
            "  amount: 600.00\n"
            "  contribution-year: 2026\n",
            '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Savings"\n'
            "  amount: 2400.00\n",
        )
    )
    assert result.diagnostics == ()
    rule = result.rule("paycheck")
    assert rule is not None
    assert rule.accounts == ("Expenses:Taxes", "Expenses:Savings")
    assert rule.postings[0].as_dict() == {"contribution-year": Decimal(2026)}


def test_orphan_posting(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "posting" "ghost" "Expenses:X"\n'
        "  amount: 1.00\n"
    )
    assert _codes(result) == ["E010"]


def test_posting_to_matched_account(compute_string) -> None:
    result = compute_string(
        _paycheck_rule(
            '2026-01-01 custom "schedule" "posting" "paycheck" "Assets:Bank"\n'
            "  amount: 3000.00\n"
        )
    )
    assert "E013" in _codes(result)


def test_posting_sum_mismatch(compute_string) -> None:
    result = compute_string(
        _paycheck_rule(
            '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Taxes"\n'
            "  amount: 500.00\n",
            '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Savings"\n'
            "  amount: 2400.00\n",
        )
    )
    assert "E011" in _codes(result)


def test_multiple_amountless_postings(compute_string) -> None:
    result = compute_string(
        _paycheck_rule(
            '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Taxes"\n',
            '2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Savings"\n',
        )
    )
    assert "E014" in _codes(result)


def test_amortization_with_postings(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 custom "schedule" "new" "loan"\n'
        '  rrule: "FREQ=MONTHLY"\n'
        "  start: 2026-01-01\n"
        '  match-account: "Assets:Bank"\n'
        "  match-amount: -1000.00\n"
        '  amount-mode: "exact"\n'
        '  method: "static"\n'
        "  rate: 0.05\n"
        "  term: 12\n"
        + '2026-01-01 custom "schedule" "posting" "loan" "Expenses:Interest"\n'
        "  amount: 1000.00\n"
    )
    assert "E012" in _codes(result)
