# PYTHONARGCOMPLETE_OK
"""The ``beanschedule`` command line interface.

A thin ``argparse`` front end over :mod:`beanschedule.core` and
:mod:`beanschedule.reconcile`. The read-only commands — ``check``, ``report``,
``list``, ``upcoming``, ``amortize`` and ``detect`` — never touch the ledger.
``reconcile`` matches imported transactions to schedules and, with ``--write``,
tags the matches and advances the frontiers. ``skip``, ``move``, ``create`` and
``edit`` change a schedule. ``docs`` renders the generated documentation and
gates it with ``--check``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import argcomplete
from beancount import loader
from beancount.parser import parser

from beanschedule import (
    __version__,
    actions,
    detector,
    migrate,
    migrate_ledger,
    reconcile,
    recurrence,
    schema,
    writer,
)
from beanschedule.core import compute
from beanschedule.pending import (
    PendingTransaction,
    load_pending_transactions,
    remove_pending_transactions,
)
from beanschedule.report import build_view, format_money, operating_currency

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from beancount.core.data import Directive

    from beanschedule.report import ScheduleView, ScheduleViewResult, UpcomingLine

__all__ = ["build_parser", "cli_markdown", "main", "render_docs"]

_GENERATED_FILES = ("cli.md", "schema.md", "errors.md")

_DEFAULT_SCHEDULES_FILE = "schedules.bean"
_DEFAULT_PENDING_FILE = "pending.bean"

#: The occurrence table's leading text columns are left-aligned; the amount is
#: right-aligned.
_OCCURRENCE_HEADERS = ("Nominal", "Status", "Effective", "Amount", "Payee")
_OCCURRENCE_TEXT_COLUMNS = 3

#: The schedule list's leading text columns.
_LIST_HEADERS = ("Schedule", "Next", "Overdue", "Due", "Account")
_LIST_TEXT_COLUMNS = 1

#: The upcoming ledger's leading text columns.
_UPCOMING_HEADERS = ("Date", "Status", "Schedule", "Amount", "Payee / narration")
_UPCOMING_TEXT_COLUMNS = 3

#: The amortization table's leading text columns.
_AMORTIZATION_HEADERS = (
    "#",
    "Date",
    "Payment",
    "Principal",
    "Interest",
    "Escrow",
    "Total",
    "Balance",
)
_AMORTIZATION_TEXT_COLUMNS = 2


# --- Rendering -----------------------------------------------------------------


def _format_table(
    headers: tuple[str, ...], rows: Sequence[tuple[str, ...]], text_columns: int
) -> str:
    """Render an aligned plain-text table.

    The first ``text_columns`` columns are left-aligned and the rest are
    right-aligned, so figures line up and text reads naturally.

    Args:
        headers: The column headings.
        rows: The rows, each with one cell per heading.
        text_columns: How many leading columns are text.

    Returns:
        The rendered table, without a trailing newline.
    """
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [
            max(width, len(cell)) for width, cell in zip(widths, row, strict=True)
        ]
    rules = "  ".join("-" * width for width in widths)

    def render(cells: Sequence[str]) -> str:
        return "  ".join(
            cell.ljust(widths[index])
            if index < text_columns
            else cell.rjust(widths[index])
            for index, cell in enumerate(cells)
        )

    return "\n".join([render(headers), rules, *(render(row) for row in rows)])


def _indent(text: str, prefix: str) -> str:
    """Indent every line of a block.

    Args:
        text: The block.
        prefix: The prefix to add to each line.

    Returns:
        The indented block.
    """
    return "\n".join(f"{prefix}{line}" for line in text.split("\n"))


def _money(value: object) -> str | None:
    """Format an optional money amount for JSON.

    Args:
        value: A decimal, or ``None``.

    Returns:
        The amount as a string, or ``None``.
    """
    return None if value is None else f"{value:.2f}"


def _report_json(view: ScheduleViewResult) -> list[dict[str, object]]:
    """Render the report view as JSON-serialisable data.

    Args:
        view: The report view.

    Returns:
        One mapping per schedule.
    """
    return [
        {
            "id": schedule.id,
            "account": schedule.rule.match_account,
            "payee": schedule.rule.payee,
            "next": schedule.next.isoformat() if schedule.next else None,
            "overdue": [day.isoformat() for day in schedule.overdue],
            "lines": [
                {
                    "nominal": line.nominal.isoformat(),
                    "effective": line.effective.isoformat(),
                    "status": "due" if line.due else line.status,
                    "due": line.due,
                    "amount": _money(line.amount),
                    "payee": line.payee,
                    "narration": line.narration,
                }
                for line in (*schedule.resolved, *schedule.upcoming)
            ],
        }
        for schedule in view.schedules
    ]


def _list_json(view: ScheduleViewResult) -> list[dict[str, object]]:
    """Render the schedule list as JSON-serialisable data.

    Args:
        view: The report view.

    Returns:
        One mapping per schedule.
    """
    return [
        {
            "id": schedule.id,
            "account": schedule.rule.match_account,
            "next": schedule.next.isoformat() if schedule.next else None,
            "overdue": [day.isoformat() for day in schedule.overdue],
            "due": [line.nominal.isoformat() for line in schedule.due],
            "amount": _money(schedule.rule.match_amount),
        }
        for schedule in view.schedules
    ]


def _upcoming_json(rows: Sequence[UpcomingLine]) -> list[dict[str, object]]:
    """Render the upcoming ledger as JSON-serialisable data.

    Args:
        rows: The ledger rows.

    Returns:
        One mapping per occurrence.
    """
    return [
        {
            "schedule": row.schedule_id,
            "nominal": row.line.nominal.isoformat(),
            "effective": row.line.effective.isoformat(),
            "status": "due" if row.line.due else row.line.status,
            "due": row.line.due,
            "amount": _money(row.line.amount),
            "payee": row.line.payee,
            "narration": row.line.narration,
        }
        for row in rows
    ]


def _amortize_json(
    schedules: Sequence[ScheduleView], currency: str
) -> list[dict[str, object]]:
    """Render the amortization projections as JSON-serialisable data.

    Args:
        schedules: The amortized schedule views.
        currency: The operating currency.

    Returns:
        One mapping per schedule.
    """
    rendered: list[dict[str, object]] = []
    for schedule in schedules:
        amortization = schedule.amortization
        if amortization is None:
            continue
        rendered.append(
            {
                "id": schedule.id,
                "account": schedule.rule.match_account,
                "currency": currency,
                "method": amortization.method,
                "rate": str(amortization.rate),
                "remaining_payments": amortization.remaining_payments,
                "remaining_principal": _money(amortization.remaining_principal),
                "remaining_interest": _money(amortization.remaining_interest),
                "remaining_escrow": _money(amortization.remaining_escrow),
                "remaining_total": _money(amortization.remaining_total),
                "payoff": (
                    amortization.payoff_date.isoformat()
                    if amortization.payoff_date
                    else None
                ),
                "lines": [
                    {
                        "payment_number": line.payment_number,
                        "date": line.date.isoformat(),
                        "payment": _money(line.payment),
                        "principal": _money(line.principal),
                        "interest": _money(line.interest),
                        "escrow": _money(line.escrow),
                        "total": _money(line.total),
                        "balance_after": _money(line.balance_after),
                    }
                    for line in amortization.lines
                ],
            }
        )
    return rendered


# --- Loading -------------------------------------------------------------------


def _load(path: Path) -> tuple[list[Directive], Mapping[str, object]]:
    """Load a ledger file.

    Args:
        path: The ledger to load.

    Returns:
        The entries and the options map.
    """
    entries, _errors, options = loader.load_file(str(path))
    return list(entries), options


def _load_schedules(path: Path) -> list[Directive]:
    """Load the schedules file.

    The whole file is schedules, so every transaction is returned — even one
    missing its ``id``, so validation can report it. The file is parsed without
    Beancount's interpolation: an amortized schedule's leg postings are
    amount-less placeholders, and the full loader would drop a transaction with
    more than one of them. The engine reports its own diagnostics instead.

    Args:
        path: The schedules file.

    Returns:
        The schedule transactions, or an empty list when the file is missing.
    """
    if not path.is_file():
        return []
    entries, _errors, _options = parser.parse_file(str(path))
    from beancount.core.data import Transaction  # noqa: PLC0415 - narrow the type

    return [entry for entry in entries if isinstance(entry, Transaction)]


def _schedules_path(args: argparse.Namespace, ledger: Path) -> Path:
    """Resolve the schedules file for a command.

    A path is relative to the ledger's directory, so the same file is found
    however the CLI is invoked.

    Args:
        args: The parsed arguments.
        ledger: The ledger path.

    Returns:
        The schedules file path.
    """
    target = getattr(args, "schedules", None)
    base = ledger.parent
    requested = Path(target) if target else Path(_DEFAULT_SCHEDULES_FILE)
    return requested if requested.is_absolute() else base / requested


def _pending_path(args: argparse.Namespace, ledger: Path) -> Path:
    """Resolve the pending file for a command.

    Args:
        args: The parsed arguments.
        ledger: The ledger path.

    Returns:
        The pending file path.
    """
    target = getattr(args, "pending", None)
    base = ledger.parent
    requested = Path(target) if target else Path(_DEFAULT_PENDING_FILE)
    return requested if requested.is_absolute() else base / requested


def _load_pending(path: Path) -> list[PendingTransaction]:
    """Load the pending transactions when the file exists.

    Args:
        path: The pending file.

    Returns:
        The pending transactions, or an empty list.
    """
    return load_pending_transactions(path) if path.is_file() else []


# --- Read-only commands --------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    """Validate the schedules across a ledger.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules, today=_today(args))
    for diagnostic in result.diagnostics:
        print(f"{diagnostic.code} {diagnostic.message}")
    return 1 if any(d.severity.value == "error" for d in result.diagnostics) else 0


def cmd_report(args: argparse.Namespace) -> int:
    """Show each schedule's occurrences, next and overdue.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules, today=_today(args))
    view = build_view(result, entries, options, today=_today(args))
    if args.json:
        print(json.dumps(_report_json(view), indent=2))
        return 0
    for schedule in view.schedules:
        print(f"{schedule.id}  ({schedule.rule.match_account})")
        print(f"  next:    {schedule.next or '-'}")
        if schedule.overdue:
            print(
                f"  overdue: {', '.join(day.isoformat() for day in schedule.overdue)}"
            )
        rows = [
            (
                line.nominal.isoformat(),
                "due" if line.due else line.status,
                line.effective.isoformat(),
                format_money(line.amount, view.currency),
                line.payee or "",
            )
            for line in (*schedule.resolved, *schedule.upcoming)
        ]
        table = _format_table(_OCCURRENCE_HEADERS, rows, _OCCURRENCE_TEXT_COLUMNS)
        print(_indent(table, "  "))
        print()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List the schedules with their next and overdue occurrences.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules, today=_today(args))
    view = build_view(result, entries, options, today=_today(args))
    if args.json:
        print(json.dumps(_list_json(view), indent=2))
        return 0
    rows = [
        (
            schedule.id,
            (schedule.next.isoformat() if schedule.next else "-"),
            str(len(schedule.overdue)),
            str(len(schedule.due)),
            schedule.rule.match_account,
        )
        for schedule in view.schedules
    ]
    print(_format_table(_LIST_HEADERS, rows, _LIST_TEXT_COLUMNS))
    return 0


def cmd_upcoming(args: argparse.Namespace) -> int:
    """Show one ledger of every schedule's outstanding occurrences.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules, today=_today(args))
    view = build_view(result, entries, options, today=_today(args))
    rows = view.ledger(pending_only=not args.all)
    if args.json:
        print(json.dumps(_upcoming_json(rows), indent=2))
        return 0
    if not rows:
        print("nothing outstanding")
        return 0
    table_rows = [
        (
            row.line.nominal.isoformat(),
            "due" if row.line.due else row.line.status,
            row.schedule_id,
            format_money(row.line.amount, view.currency),
            row.line.payee or row.line.narration or row.rule.narration or "",
        )
        for row in rows
    ]
    print(_format_table(_UPCOMING_HEADERS, table_rows, _UPCOMING_TEXT_COLUMNS))
    return 0


def cmd_amortize(args: argparse.Namespace) -> int:
    """Show each loan's remaining amortization schedule.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules, today=_today(args))
    view = build_view(result, entries, options, today=_today(args))
    targets = [
        schedule
        for schedule in view.schedules
        if schedule.amortization is not None
        and (args.id is None or schedule.id == args.id)
    ]
    if args.json:
        print(json.dumps(_amortize_json(targets, view.currency), indent=2))
        return 0
    if not targets:
        print("no amortized schedules")
        return 0
    for schedule in targets:
        amortization = schedule.amortization
        assert amortization is not None  # noqa: S101 - filtered above
        print(f"{schedule.id}  ({schedule.rule.match_account})")
        if not amortization.has_lines:
            print("  no remaining payments")
            print()
            continue
        print(
            f"  {amortization.method}  rate {amortization.rate}  "
            f"payoff {amortization.payoff_date}"
        )
        print(
            f"  remaining: {amortization.remaining_payments} payments  "
            f"principal {format_money(amortization.remaining_principal, view.currency)}  "
            f"interest {format_money(amortization.remaining_interest, view.currency)}  "
            f"escrow {format_money(amortization.remaining_escrow, view.currency)}  "
            f"total {format_money(amortization.remaining_total, view.currency)}"
        )
        rows = [
            (
                str(line.payment_number or ""),
                line.date.isoformat(),
                format_money(line.payment, view.currency),
                format_money(line.principal, view.currency),
                format_money(line.interest, view.currency),
                format_money(line.escrow, view.currency),
                format_money(line.total, view.currency),
                format_money(line.balance_after, view.currency),
            )
            for line in amortization.lines
        ]
        table = _format_table(_AMORTIZATION_HEADERS, rows, _AMORTIZATION_TEXT_COLUMNS)
        print(_indent(table, "  "))
        print()
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    """Propose schedules for recurring payments in a ledger.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules)
    proposals = detector.detect(entries, exclude=result)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": proposal.schedule_id,
                        "account": proposal.account,
                        "rrule": proposal.rrule,
                        "start": proposal.start.isoformat(),
                        "confidence": round(proposal.confidence, 2),
                    }
                    for proposal in proposals
                ],
                indent=2,
            )
        )
        return 0
    for proposal in proposals:
        print(actions.render(proposal.transaction()))
        print()
    return 0


# --- reconcile -----------------------------------------------------------------


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Match imported transactions to schedules, advancing the frontiers.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules_path = _schedules_path(args, ledger)
    schedules = _load_schedules(schedules_path)
    pending_path = _pending_path(args, ledger)
    pending = _load_pending(pending_path)
    result = reconcile.plan(entries, schedules, pending, options, today=_today(args))
    currency = operating_currency(options)
    for match in result.pending:
        amount = format_money(_matched_amount(match.transaction), currency)
        print(
            f"pending  {match.transaction.date}  {amount:>14}  "
            f"{(match.transaction.payee or '')}  ->  #pending"
        )
    for match in result.matches:
        amount = format_money(_matched_amount(match.transaction), currency)
        print(
            f"schedule {match.rule.id:<24} {match.nominal}  {match.transaction.date}  "
            f"{amount:>14}  {(match.transaction.payee or '')}"
        )
    for advance in result.advances:
        target = advance.new_date.isoformat() if advance.new_date else "remove"
        print(f"advance  {advance.rule.id:<24} {advance.rule.start} -> {target}")
    if result.empty:
        print("nothing to reconcile")
        return 0
    if not args.write:
        print("dry run — pass --write to apply")
        return 0
    _apply(result, ledger, schedules_path, pending_path)
    print("applied")
    return 0


def _matched_amount(entry: Directive) -> Decimal | None:
    """Return a transaction's first amount, for the preview.

    Args:
        entry: The transaction.

    Returns:
        The first posting's amount, or ``None``.
    """
    postings = getattr(entry, "postings", ())
    for posting in postings:
        if posting.units is not None:
            return posting.units.number
    return None


def _apply(
    result: reconcile.Plan,
    ledger: Path,
    schedules_path: Path,
    pending_path: Path,
) -> None:
    """Apply a reconciliation plan by editing the ledger files.

    Args:
        result: The plan.
        ledger: The ledger path.
        schedules_path: The schedules file.
        pending_path: The pending file.
    """
    edits: dict[Path, list[tuple[int, Directive | None]]] = defaultdict(list)
    schedules_target = writer.resolve_target(schedules_path, ledger.parent)
    for match in result.matches:
        enriched = reconcile.enrich(match)
        _add_edit(edits, ledger, match.transaction, enriched)
    for match in result.pending:
        enriched = reconcile.enrich_pending(match)
        _add_edit(edits, ledger, match.transaction, enriched)
    for advance in result.advances:
        line = _lineno(advance.rule.entry)
        if line is None:
            continue
        if advance.new_date is None:
            edits[schedules_target].append((line, None))
        else:
            updated = actions.advance(advance.rule, advance.new_date)
            edits[schedules_target].append((line, updated))
    for path, changes in edits.items():
        writer.rewrite(path, changes)
    consumed = [match.pending for match in result.pending]
    if consumed:
        remove_pending_transactions(pending_path, consumed)


def _add_edit(
    edits: dict[Path, list[tuple[int, Directive | None]]],
    ledger: Path,
    original: Directive,
    updated: Directive,
) -> None:
    """Queue an in-place edit of a transaction's own source file.

    Args:
        edits: The per-file edit lists.
        ledger: The ledger path.
        original: The transaction being replaced.
        updated: Its replacement.
    """
    meta = getattr(original, "meta", None) or {}
    filename = meta.get("filename")
    line = meta.get("lineno")
    if filename is None or line is None:
        return
    target = writer.resolve_target(Path(str(filename)), ledger.parent)
    edits[target].append((int(line), updated))


def _lineno(entry: Directive | None) -> int | None:
    """Return a directive's line number.

    Args:
        entry: The directive, if any.

    Returns:
        The one-based line number, or ``None``.
    """
    meta = getattr(entry, "meta", None) or {}
    line = meta.get("lineno")
    return int(line) if line is not None else None


# --- Mutating commands ---------------------------------------------------------


def _emit(entries: Sequence[Directive], args: argparse.Namespace, kind: str) -> int:
    """Print or append one or more directives.

    Args:
        entries: The directives.
        args: The parsed arguments.
        kind: The action name, for the message.

    Returns:
        The process exit code.
    """
    if not args.write:
        for entry in entries:
            print(actions.render(entry))
        return 0
    ledger = Path(args.ledger)
    target = writer.resolve_target(Path(args.write), Path(ledger).parent)
    for entry in entries:
        writer.append(target, entry)
    print(f"wrote {kind} to {target}")
    return 0


def _skip_or_move(
    schedule_id: str, new_date: date | None, args: argparse.Namespace
) -> int:
    """Advance or move a schedule's frontier.

    Args:
        schedule_id: The schedule id.
        new_date: The new frontier date, or ``None`` to remove the series.
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules_path = _schedules_path(args, ledger)
    schedules = _load_schedules(schedules_path)
    result = compute(entries, options, schedules=schedules)
    rule = result.rule(schedule_id)
    if rule is None:
        print(f"unknown schedule: {schedule_id}", file=sys.stderr)
        return 1
    if not args.write:
        target = new_date.isoformat() if new_date else "remove"
        print(f"{schedule_id}: {rule.start} -> {target}")
        return 0
    target = writer.resolve_target(Path(args.write), ledger.parent)
    line = _lineno(rule.entry)
    if line is None:
        print("the schedule has no source location to edit", file=sys.stderr)
        return 1
    if new_date is None:
        writer.delete(target, line)
    else:
        writer.replace(target, line, actions.advance(rule, new_date))
    return 0


def cmd_skip(args: argparse.Namespace) -> int:
    """Skip a schedule's next occurrence, advancing its frontier.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules = _load_schedules(_schedules_path(args, ledger))
    result = compute(entries, options, schedules=schedules)
    rule = result.rule(args.schedule)
    if rule is None:
        print(f"unknown schedule: {args.schedule}", file=sys.stderr)
        return 1
    new_date = recurrence.next_after(rule.rrule, rule.start, rule.start, end=rule.end)
    return _skip_or_move(args.schedule, new_date, args)


def cmd_move(args: argparse.Namespace) -> int:
    """Move a schedule's frontier to a chosen date.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    return _skip_or_move(args.schedule, date.fromisoformat(args.new_date), args)


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new schedule transaction.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    _entries, options = _load(ledger)
    currency = operating_currency(options) or "USD"
    day = date.fromisoformat(args.start)
    postings = [
        (account, Decimal(amount) if amount else None, None)
        for account, amount in (args.posting or [])
    ]
    txn = actions.schedule_transaction(
        args.schedule,
        day,
        rrule=args.rrule,
        match_account=args.account,
        currency=currency,
        payee=args.write_payee,
        narration=args.narration,
        match_payee=args.payee,
        match_amount=Decimal(args.amount) if args.amount else None,
        amount_tolerance=Decimal(args.tolerance) if args.tolerance else None,
        postings=postings,
    )
    return _emit([txn], args, "schedule")


def cmd_edit(args: argparse.Namespace) -> int:
    """Edit a schedule's matched amount in place.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    schedules_path = _schedules_path(args, ledger)
    schedules = _load_schedules(schedules_path)
    result = compute(entries, options, schedules=schedules)
    rule = result.rule(args.schedule)
    if rule is None:
        print(f"unknown schedule: {args.schedule}", file=sys.stderr)
        return 1
    if args.amount is None:
        print("nothing to change: pass --amount", file=sys.stderr)
        return 1
    from dataclasses import replace  # noqa: PLC0415 - a single local use

    currency = operating_currency(options) or "USD"
    updated = actions.from_rule(
        replace(rule, match_amount=Decimal(args.amount)), currency
    )
    if not args.write:
        print(actions.render(updated))
        return 0
    target = writer.resolve_target(Path(args.write), ledger.parent)
    line = _lineno(rule.entry)
    if line is None:
        print("the schedule has no source location to edit", file=sys.stderr)
        return 1
    writer.replace(target, line, updated)
    return 0


# --- migrate -------------------------------------------------------------------


def cmd_migrate(args: argparse.Namespace) -> int:
    """Convert ``schedules/*.yaml`` to schedule transactions, idempotently.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    directory = Path(args.directory)
    ledger = Path(args.ledger) if args.ledger else Path("main.bean")
    schedules = _schedules_path(args, ledger)
    existing = (
        {rule.id for rule in compute(*_load(schedules)).rules}
        if schedules.is_file()
        else set()
    )
    blocks = [
        migrate.render(migration)
        for migration in migrate.directory(directory, existing)
    ]
    print("\n\n".join(blocks))
    return 0


def cmd_migrate_ledger(args: argparse.Namespace) -> int:
    """Strip v1 tracking metadata and placeholders from a ledger.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    plans = migrate_ledger.scan(Path(args.ledger))
    print(migrate_ledger.summarise(plans))
    if not plans:
        return 0
    if not args.write:
        print("dry run — pass --write to apply")
        return 0
    migrate_ledger.apply(plans)
    print("applied")
    return 0


# --- docs ----------------------------------------------------------------------


def _docs_dir() -> Path:
    """Return the directory the generated docs live in.

    Returns:
        The ``docs`` directory beside the package.
    """
    return Path(__file__).resolve().parents[2] / "docs"


def render_docs() -> dict[str, str]:
    """Render every generated documentation file.

    Returns:
        A mapping from file name to content.
    """
    return {
        "cli.md": cli_markdown(build_parser()),
        "schema.md": schema.schema_markdown(),
        "errors.md": schema.errors_markdown(),
    }


def _walk_commands(
    parser: argparse.ArgumentParser, path: tuple[str, ...]
) -> list[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    """Walk a parser tree, parents before children.

    Args:
        parser: The parser to walk.
        path: The command path so far.

    Returns:
        The ``(path, parser)`` pairs.
    """
    found = [(path, parser)]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                if isinstance(child, argparse.ArgumentParser):
                    found.extend(_walk_commands(child, (*path, name)))
    return found


def cli_markdown(parser: argparse.ArgumentParser) -> str:
    """Render the command tree as Markdown.

    Args:
        parser: The root parser.

    Returns:
        The contents of ``docs/cli.md``.
    """
    lines = [
        "# Command line\n",
        "> Generated by `beanschedule docs`. Do not edit by hand.\n",
    ]
    for path, node in _walk_commands(parser, ("beanschedule",)):
        if node.description:
            lines.append(f"## `{' '.join(path)}`\n")
            lines.append(node.description.rstrip(". ") + ".\n")
            table = _command_table(node)
            if table:
                lines.append(table)
    return "\n".join(lines)


def _command_table(parser: argparse.ArgumentParser) -> str:
    """Render a parser's arguments as a Markdown table.

    Args:
        parser: The parser.

    Returns:
        The table, or ``""`` when the parser takes no arguments.
    """
    rows: list[tuple[str, str, str]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        if action.dest == "help":
            continue
        flags = ", ".join(f"`{option}`" for option in action.option_strings)
        name = flags or f"`{action.dest}`"
        default = "" if action.default in (None, False) else f" `{action.default}`"
        rows.append(
            (name, "yes" if action.required else "no", (action.help or "") + default)
        )
    if not rows:
        return ""
    header = "| Argument | Required | Help |\n| --- | --- | --- |\n"
    body = "\n".join(
        f"| {name} | {required} | {help_} |" for name, required, help_ in rows
    )
    return header + body + "\n"


# --- top level -----------------------------------------------------------------


def _today(args: argparse.Namespace) -> date:
    """Resolve the reference date for a command.

    Args:
        args: The parsed arguments.

    Returns:
        The reference date.
    """
    requested = getattr(args, "today", None)
    if requested:
        return date.fromisoformat(requested)
    return date.today()  # noqa: DTZ011 - the reference date is wall-clock


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 - one wiring block
    """Build the command-line parser.

    Returns:
        The root parser.
    """
    parser = argparse.ArgumentParser(prog="beanschedule", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    _add_ledger(sub, "check", "Validate the schedules across a ledger", cmd_check)
    report = _add_ledger(sub, "report", "Show each schedule's occurrences", cmd_report)
    report.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    listing = _add_ledger(sub, "list", "List schedules with next and overdue", cmd_list)
    listing.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    upcoming = _add_ledger(
        sub,
        "upcoming",
        "Show one ledger of every outstanding occurrence",
        cmd_upcoming,
    )
    upcoming.add_argument(
        "--all", action="store_true", help="Include resolved occurrences too"
    )
    upcoming.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    amortize = _add_ledger(
        sub,
        "amortize",
        "Show each loan's remaining amortization schedule",
        cmd_amortize,
    )
    amortize.add_argument("--id", help="Show only this schedule id")
    amortize.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )

    detect = _add_ledger(
        sub, "detect", "Propose schedules for recurring payments", cmd_detect
    )
    detect.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )

    engine = _add_ledger(
        sub,
        "reconcile",
        "Match imported transactions to schedules",
        cmd_reconcile,
    )
    engine.add_argument("--pending", help="The pending file")
    engine.add_argument(
        "--write",
        nargs="?",
        const=_DEFAULT_SCHEDULES_FILE,
        help="Apply the plan, writing to this schedules file",
    )

    skip = _add_write(sub, "skip", "Skip a schedule's next occurrence", cmd_skip)
    skip.add_argument("schedule", help="The schedule id")

    move = _add_write(sub, "move", "Move a schedule's frontier date", cmd_move)
    move.add_argument("schedule", help="The schedule id")
    move.add_argument("new_date", help="The date to move it to")

    create = _add_write(sub, "create", "Create a new schedule", cmd_create)
    create.add_argument("schedule", help="The schedule id")
    create.add_argument("--rrule", required=True, help="The recurrence rule")
    create.add_argument("--start", required=True, help="The first occurrence date")
    create.add_argument("--account", required=True, help="The matched account")
    create.add_argument(
        "--posting",
        nargs=2,
        action="append",
        metavar=("ACCOUNT", "AMOUNT"),
        help="An other-side posting (repeatable; omit AMOUNT to let Beancount balance)",
    )
    create.add_argument("--payee", help="A payee regex for matching")
    create.add_argument("--amount", help="The matched amount")
    create.add_argument("--tolerance", help="The approximate-match tolerance")
    create.add_argument("--write-payee", dest="write_payee", help="The payee to write")
    create.add_argument("--narration", help="The narration to write")

    edit = _add_write(sub, "edit", "Edit a schedule's matched amount", cmd_edit)
    edit.add_argument("schedule", help="The schedule id")
    edit.add_argument("--amount", help="Set a new matched amount")

    migrate_cmd = sub.add_parser(
        "migrate",
        help="Convert schedules/*.yaml to schedule transactions",
        description=(
            "Convert a schedules/ directory of YAML files to schedule "
            "transactions, idempotently."
        ),
    )
    migrate_cmd.add_argument("directory", help="The schedules directory")
    migrate_cmd.add_argument("--ledger", help="The ledger, for the schedules file")
    migrate_cmd.add_argument("--schedules", help="The schedules file")
    migrate_cmd.set_defaults(func=cmd_migrate)

    migrate_ledger_cmd = sub.add_parser(
        "migrate-ledger",
        help="Strip v1 tracking metadata and placeholders from a ledger",
        description=(
            "Rename v1 `schedule_id` metadata to `schedule`, remove the v1 "
            "tracking metadata, and delete placeholder transactions, editing the "
            "ledger files in place. A dry run until --write is passed."
        ),
    )
    migrate_ledger_cmd.add_argument("ledger", help="The ledger file")
    migrate_ledger_cmd.add_argument(
        "--write", action="store_true", help="Apply the edits, in place"
    )
    migrate_ledger_cmd.set_defaults(func=cmd_migrate_ledger)

    docs = sub.add_parser(
        "docs",
        help="Generate the documentation",
        description=(
            "Generate docs/cli.md, docs/schema.md and docs/errors.md from the "
            "command tree and the registries."
        ),
    )
    docs.add_argument(
        "--check", action="store_true", help="Fail when the docs are stale"
    )
    docs.set_defaults(func=cmd_docs)
    return parser


def _add_ledger(
    sub: argparse._SubParsersAction,
    name: str,
    help_text: str,
    func: Callable[[argparse.Namespace], int],
) -> argparse.ArgumentParser:
    """Add a command taking a ledger and an optional schedules file.

    Args:
        sub: The subparser action.
        name: The command name.
        help_text: The command's one-line help.
        func: The command function.

    Returns:
        The command's parser.
    """
    parser = sub.add_parser(name, help=help_text, description=help_text)
    parser.add_argument("ledger", help="The ledger file")
    parser.add_argument("--schedules", help="The schedules file")
    parser.add_argument("--today", help="The reference date (YYYY-MM-DD)")
    parser.set_defaults(func=func)
    return parser


def _add_write(
    sub: argparse._SubParsersAction,
    name: str,
    help_text: str,
    func: Callable[[argparse.Namespace], int],
) -> argparse.ArgumentParser:
    """Add a mutating command with the shared ``--write`` options.

    Args:
        sub: The subparser action.
        name: The command name.
        help_text: The command's one-line help.
        func: The command function.

    Returns:
        The command's parser.
    """
    parser = sub.add_parser(name, help=help_text, description=help_text)
    parser.add_argument("ledger", help="The ledger file")
    parser.add_argument("--schedules", help="The schedules file")
    parser.add_argument("--today", help="The reference date (YYYY-MM-DD)")
    parser.add_argument(
        "--write",
        nargs="?",
        const=_DEFAULT_SCHEDULES_FILE,
        help="Write to this file",
    )
    parser.set_defaults(func=func)
    return parser


def cmd_docs(args: argparse.Namespace) -> int:
    """Write the generated documentation, or check it.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    directory = _docs_dir()
    rendered = render_docs()
    if args.check:
        stale = [
            name
            for name, content in rendered.items()
            if not (directory / name).exists()
            or (directory / name).read_text(encoding="utf-8") != content
        ]
        if stale:
            for name in stale:
                print(_diff(directory / name, rendered[name]), file=sys.stderr)
            return 1
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (directory / name).write_text(content, encoding="utf-8")
    return 0


def _diff(path: Path, expected: str) -> str:
    """Render a unified diff of a stale generated file.

    Args:
        path: The file on disk.
        expected: The expected content.

    Returns:
        The diff text.
    """
    actual = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    wanted = expected.splitlines()
    return "\n".join(
        difflib.unified_diff(actual, wanted, fromfile=str(path), tofile="expected")
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: The arguments, or ``None`` for ``sys.argv``.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
