"""Core computation, parsing, diagnostics and matching tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from beancount.core import data as bc_data
from beancount.core.amount import Amount
from beancount.parser import parser

from beanschedule.core import (
    Amortization,
    Rule,
    amortization_splits,
    assign,
    compute,
    is_schedule,
    ledger_balance,
    parse_schedule,
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


def _schedule(
    body: str,
    day: str = "2026-01-01",
    rrule: str = "FREQ=MONTHLY;BYMONTHDAY=1",
) -> str:
    return (
        BASE + f'{day} * "Landlord" "Rent"\n  id: "rent"\n  rrule: "{rrule}"\n' + body
    )


# --- Fixture ledgers -----------------------------------------------------------


def test_basic_posts_and_next(load_result) -> None:
    result = load_result("basic.bean", today=date(2026, 2, 1))
    assert result.diagnostics == ()
    report = result.report("paycheck")
    assert report is not None
    assert report.next == date(2026, 2, 15)
    assert report.overdue == ()
    assert [txn.date for txn in report.history] == [date(2026, 1, 16)]


def test_overdue_and_next(load_result) -> None:
    result = load_result("stale.bean", today=date(2026, 4, 15))
    assert "W001" in _codes(result)
    report = result.report("rent")
    assert report is not None
    assert report.next == date(2026, 1, 1)
    assert report.overdue == (
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
    )


def test_no_today_skips_overdue(load_result) -> None:
    result = load_result("stale.bean")
    assert "W001" not in _codes(result)
    assert result.report("rent").overdue == ()


# --- Diagnostics ---------------------------------------------------------------


def test_missing_id() -> None:
    txn = _txn('2026-01-01 * "Landlord" "Rent"\n  rrule: "FREQ=MONTHLY"\n')
    diagnostics: list = []
    assert parse_schedule(txn, diagnostics) is None
    assert [diagnostic.code for diagnostic in diagnostics] == ["E001"]


def test_missing_rrule(compute_string) -> None:
    result = compute_string(BASE + '2026-01-01 * "Landlord" "Rent"\n  id: "rent"\n')
    assert "E001" in _codes(result)


def test_no_balance_sheet_posting(compute_string) -> None:
    result = compute_string(
        BASE + '2026-01-01 * "Nobody" "Thing"\n'
        '  id: "x"\n  rrule: "FREQ=MONTHLY"\n'
        "  Expenses:X  1.00 USD\n"
        "  Equity:Opening  -1.00 USD\n"
    )
    assert "E001" in _codes(result)


def test_invalid_rrule(compute_string) -> None:
    result = compute_string(_schedule("", rrule="EVERY DAY"))
    assert _codes(result) == ["E002"]


def test_duplicate_id(compute_string) -> None:
    rule = (
        '2026-01-01 * "Landlord" "Rent"\n'
        '  id: "rent"\n  rrule: "FREQ=MONTHLY"\n'
        "  Assets:Bank  -1.00 USD\n  Expenses:X  1.00 USD\n"
    )
    result = compute_string(BASE + rule + rule)
    assert "E003" in _codes(result)
    assert len(result.rules) == 1


def test_end_before_start(compute_string) -> None:
    result = compute_string(_schedule("  end: 2025-12-01\n"))
    assert "E009" in _codes(result)


def test_currency_mismatch(compute_string) -> None:
    result = compute_string(
        _schedule("  Assets:Bank  -100.00 EUR\n  Expenses:X  100.00 EUR\n")
    )
    assert "E008" in _codes(result)


def test_far_future_date_does_not_overflow(compute_string) -> None:
    result = compute_string(
        BASE + '9999-12-01 * "Landlord" "Rent"\n'
        '  id: "rent"\n  rrule: "FREQ=MONTHLY"\n'
        "  Assets:Bank  -1.00 USD\n  Expenses:X  1.00 USD\n"
    )
    assert result.rule("rent") is not None


def test_far_future_directive_does_not_inflate_the_horizon(compute_string) -> None:
    result = compute_string(
        BASE
        + '9998-01-01 custom "note" "a far-future directive"\n'
        + '2013-01-15 * "Landlord" "Rent"\n'
        '  id: "rent"\n  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  Assets:Bank  -1.00 USD\n  Expenses:X  1.00 USD\n"
    )
    report = result.report("rent")
    assert report is not None
    assert len(report.occurrences) < 1000


# --- Parsing -------------------------------------------------------------------


def test_default_match_account_from_balance_sheet() -> None:
    txn = _txn(
        '2026-01-15 * "Acme" "Paycheck"\n'
        '  id: "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  Assets:Bank   -1000.00 USD\n"
        "  Expenses:Tax   1000.00 USD\n"
    )
    assert is_schedule(txn)
    rule = parse_schedule(txn, [])
    assert rule is not None
    assert rule.match_account == "Assets:Bank"
    assert rule.match_amount == D("-1000.00")
    assert rule.amount_mode == "exact"
    assert [spec.account for spec in rule.postings] == ["Expenses:Tax"]


def test_amount_tolerance_selects_approx() -> None:
    txn = _txn(
        '2026-01-15 * "Acme" "Paycheck"\n'
        '  id: "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        "  amount-tolerance: 7.50\n"
        "  Assets:Bank   -1000.00 USD\n"
        "  Expenses:Tax   1000.00 USD\n"
    )
    rule = parse_schedule(txn, [])
    assert rule is not None
    assert rule.amount_mode == "approx"
    assert rule.amount_tolerance == D("7.50")


def test_non_schedule_transaction_is_not_a_schedule() -> None:
    txn = _txn(
        '2026-01-15 * "Acme" "Paycheck"\n'
        "  Assets:Bank   -1000.00 USD\n"
        "  Expenses:Tax   1000.00 USD\n"
    )
    assert not is_schedule(txn)


def test_parse_schedule_captures_tags_links_and_metadata() -> None:
    txn = _txn(
        '2026-01-15 * "Acme" "Paycheck" #salary ^payroll-2026\n'
        '  id: "paycheck"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"\n'
        '  category: "income"\n'
        "  Assets:Bank   -1000.00 USD\n"
        "  Expenses:Tax   1000.00 USD\n"
    )
    rule = parse_schedule(txn, [])
    assert rule is not None
    assert rule.tags == frozenset({"salary"})
    assert rule.links == frozenset({"payroll-2026"})
    assert dict(rule.metadata) == {"category": "income"}


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


def test_malformed_amortization_missing_principal(compute_string) -> None:
    result = compute_string(
        _schedule(
            '  method: "static"\n  rate: 0.05\n  term: 12\n'
            "  Assets:Bank  -100.00 USD\n"
            "  Expenses:X    100.00 USD\n"
            '    schedule-leg: "interest"\n'
        )
    )
    assert "E012" in _codes(result)


def test_malformed_amortization_missing_rate(compute_string) -> None:
    result = compute_string(
        _schedule(
            '  method: "static"\n  term: 12\n'
            "  Assets:Bank  -100.00 USD\n"
            "  Expenses:X    100.00 USD\n"
            '    schedule-leg: "principal"\n'
        )
    )
    assert "E001" in _codes(result)


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


def test_walk_balance_subtracts_escrow_from_payment() -> None:
    # The matched posting is the whole cash payment; escrow is split off it.
    rule = _rule(
        match_amount=D("-1200.00"),
        amount_mode="exact",
        amortization=Amortization(
            method="balance-from-ledger",
            rate=D("0.06"),
            escrow=D("200.00"),
            principal_account="Liabilities:Loan",
        ),
    )
    split = walk_balance(
        rule, D("10000.00"), date(2025, 12, 31), [date(2026, 1, 1)], D("200.00")
    )[date(2026, 1, 1)]
    assert split.interest == D("50.00")
    assert split.principal == D("950.00")
    assert split.escrow == D("200.00")
    assert split.total == D("1200.00")
    assert split.balance_after == D("9050.00")


def _amortized(text: str) -> list[str]:
    entries, _errors, options = parser.parse_string(text)
    return _codes(compute(entries, options, today=date(2026, 1, 1)))


_AMORT_HEAD = (
    'option "operating_currency" "USD"\n'
    "2020-01-01 open Assets:Bank\n"
    "2020-01-01 open Liabilities:Loan\n"
    "2020-01-01 open Expenses:X\n"
    '2026-01-01 * "Chase" "Loan"\n'
    '  id: "loan"\n'
    '  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"\n'
    '  method: "static"\n'
    "  rate: 0.06\n"
    "  term: 12\n"
)


def test_amortized_schedule_without_a_match_amount_warns() -> None:
    codes = _amortized(
        _AMORT_HEAD
        + "  Assets:Bank\n"
        + "  Liabilities:Loan  1000.00 USD\n"
        + '    schedule-leg: "principal"\n'
        + "  Expenses:X         200.00 USD\n"
        + '    schedule-leg: "interest"\n'
    )
    assert "E015" in codes


def test_amortized_schedule_without_interest_leg_warns() -> None:
    codes = _amortized(
        _AMORT_HEAD
        + "  Assets:Bank  -1200.00 USD\n"
        + "  Liabilities:Loan  1000.00 USD\n"
        + '    schedule-leg: "principal"\n'
        + "  Expenses:X         200.00 USD\n"
    )
    assert "W002" in codes


def test_amortized_schedule_with_escrow_metadata_but_no_leg_warns() -> None:
    codes = _amortized(
        _AMORT_HEAD
        + "  escrow: 200.00\n"
        + "  Assets:Bank  -1200.00 USD\n"
        + "  Liabilities:Loan  1000.00 USD\n"
        + '    schedule-leg: "principal"\n'
        + "  Expenses:X         200.00 USD\n"
        + '    schedule-leg: "interest"\n'
    )
    assert "W003" in codes


def test_amount_tolerance_without_a_match_amount_warns() -> None:
    codes = _amortized(
        'option "operating_currency" "USD"\n'
        "2020-01-01 open Assets:Bank\n"
        "2020-01-01 open Expenses:X\n"
        '2026-01-01 * "Landlord" "Rent"\n'
        '  id: "rent"\n'
        '  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"\n'
        "  amount-tolerance: 5.00\n"
        "  Assets:Bank\n"
        "  Expenses:X  1.00 USD\n"
    )
    assert "W004" in codes


# --- Declared postings ---------------------------------------------------------


def _posting(account: str, number: str | None = None):
    units = None if number is None else Amount(D(number), "USD")
    return bc_data.Posting(account, units, None, None, None, None)


def _schedule_txn(postings, *, day: date = date(2026, 1, 15)):
    meta = {
        "filename": "<test>",
        "lineno": 1,
        "id": "paycheck",
        "rrule": "FREQ=MONTHLY",
    }
    return bc_data.Transaction(
        meta, day, "*", "Acme", "Pay", frozenset(), frozenset(), postings
    )


def _compute_schedules(txn):
    return compute([txn], {"operating_currency": "USD"}, schedules=[txn])


def test_valid_posting_split() -> None:
    txn = _schedule_txn(
        [
            _posting("Assets:Bank", "-3000.00"),
            _posting("Expenses:Taxes", "600.00"),
            _posting("Expenses:Savings", "2400.00"),
        ]
    )
    result = _compute_schedules(txn)
    assert result.diagnostics == ()
    rule = result.rule("paycheck")
    assert rule is not None
    assert rule.accounts == ("Expenses:Taxes", "Expenses:Savings")


def test_posting_sum_mismatch() -> None:
    txn = _schedule_txn(
        [
            _posting("Assets:Bank", "-3000.00"),
            _posting("Expenses:Taxes", "500.00"),
        ]
    )
    assert "E011" in _codes(_compute_schedules(txn))


def test_multiple_amountless_postings() -> None:
    txn = _schedule_txn(
        [
            _posting("Assets:Bank", "-3000.00"),
            _posting("Expenses:Taxes"),
            _posting("Expenses:Savings"),
        ]
    )
    assert "E014" in _codes(_compute_schedules(txn))
