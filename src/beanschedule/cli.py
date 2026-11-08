# PYTHONARGCOMPLETE_OK
"""The ``beanschedule`` command line interface.

A thin ``argparse`` front end over :mod:`beanschedule.core`. The read-only
commands — ``check``, ``report``, ``forecast``, ``list`` and ``detect`` — never
touch the ledger. The mutating commands — ``skip``, ``move``, ``create``,
``edit`` and ``rebuild`` — write only with ``--write``, and only through
:mod:`beanschedule.writer`, at one configured file inside the ledger directory.
``docs`` renders the generated documentation and gates it with ``--check``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import argcomplete
from beancount import loader

from beanschedule import __version__, actions, detector, migrate, schema, writer
from beanschedule.core import Rule, compute
from beanschedule.hook import SCHEDULES_FILE
from beanschedule.report import build_view, format_money

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from beancount.core.data import Custom, Directive

__all__ = ["build_parser", "cli_markdown", "main", "render_docs"]

_GENERATED_FILES = ("cli.md", "schema.md", "errors.md")


# --- Loading -------------------------------------------------------------------


def _load(path: Path) -> tuple[list[Directive], Mapping[str, object]]:
    """Load a ledger file.

    Args:
        path: The ledger to load.

    Returns:
        The entries and the options map.
    """
    entries, _errors, options = loader.load_file(str(path))
    return entries, options


def _load_schedules(path: Path | None) -> list[Directive]:
    """Load the schedules file when one is configured.

    Args:
        path: The schedules file, or ``None``.

    Returns:
        The schedule entries, or an empty list.
    """
    if path is None or not path.is_file():
        return []
    entries, _errors, _options = loader.load_file(str(path))
    return entries


def _schedules_path(args: argparse.Namespace, ledger: Path) -> Path:
    """Resolve the schedules file for a command.

    Args:
        args: The parsed arguments.
        ledger: The ledger path.

    Returns:
        The schedules file path.
    """
    target = getattr(args, "schedules", None)
    if target is not None:
        return Path(target)
    return ledger.parent / SCHEDULES_FILE


def _combined(entries: list[Directive], schedules_path: Path) -> list[Directive]:
    """Return the ledger entries with the schedules, without double-loading.

    A general ledger usually ``include`` s ``Schedules.bean`` already, so its
    entries carry the schedule directives. The file is loaded separately only
    when the ledger does not, so the same rule is never parsed twice.

    Args:
        entries: The ledger entries.
        schedules_path: The schedules file to load when needed.

    Returns:
        The combined entries.
    """
    if any(getattr(entry, "type", None) == schema.TYPE for entry in entries):
        return entries
    return entries + _load_schedules(schedules_path)


# --- Read-only commands --------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    """Validate the schedules across a ledger.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    entries, options = _load(Path(args.ledger))
    entries = _combined(entries, _schedules_path(args, Path(args.ledger)))
    result = compute(entries, options, today=_today(args))
    for diagnostic in result.diagnostics:
        print(f"{diagnostic.code} {diagnostic.message}")
    errors = [d for d in result.diagnostics if d.severity.value == "error"]
    return 1 if errors else 0


def cmd_report(args: argparse.Namespace) -> int:
    """Show each schedule's occurrences, next and overdue.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    combined = _combined(entries, _schedules_path(args, ledger))
    result = compute(combined, options, today=_today(args))
    view = build_view(result, combined, options, today=_today(args))
    for schedule in view.schedules:
        print(f"{schedule.id}  ({schedule.rule.match_account})")
        print(f"  next:    {schedule.next or '-'}")
        if schedule.overdue:
            print(
                f"  overdue: {', '.join(day.isoformat() for day in schedule.overdue)}"
            )
        for line in schedule.resolved:
            amount = format_money(line.amount, view.currency)
            print(
                f"  {line.nominal}  {line.status:<8} "
                f"{line.effective}  {amount:>14}  {line.payee or ''}"
            )
        for line in schedule.upcoming:
            amount = format_money(line.amount, view.currency)
            print(f"  {line.nominal}  {line.status:<8} {'':10}  {amount:>14}")
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
    combined = _combined(entries, _schedules_path(args, ledger))
    result = compute(combined, options, today=_today(args))
    for report in result.reports:
        overdue = len(report.overdue)
        flag = f"  {overdue} overdue" if overdue else ""
        nxt = report.next.isoformat() if report.next else "-"
        print(f"{report.id:<32} next {nxt:<12}{flag}")
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    """Print the upcoming occurrences for every schedule.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    from beancount.core import data  # noqa: PLC0415 - narrow the entry type

    from beanschedule.plugin import forecast_entries  # noqa: PLC0415 - avoid a cycle

    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    combined = _combined(entries, _schedules_path(args, ledger))
    today = _today(args)
    result = compute(combined, options, today=today)
    forecast = forecast_entries(
        result, combined, options, months=args.months, today=today
    )
    for entry in forecast:
        if not isinstance(entry, data.Transaction):
            continue
        amount = next((p.units for p in entry.postings if p.units), None)
        print(f"{entry.date}  {entry.payee or '':<24} {amount}")
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
    combined = _combined(entries, _schedules_path(args, ledger))
    result = compute(combined, options)
    proposals = detector.detect(entries, exclude=result)
    as_json = json.dumps(
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
    if args.json:
        print(as_json)
        return 0
    for proposal in proposals:
        for directive in proposal.directives():
            print(actions.render(directive))
        print()
    return 0


# --- Mutating commands ---------------------------------------------------------


def _write_target(args: argparse.Namespace, ledger: Path) -> Path:
    """Resolve the file a mutating command writes to.

    Args:
        args: The parsed arguments.
        ledger: The ledger path.

    Returns:
        The resolved write target.
    """
    requested = Path(args.write)
    return writer.resolve_target(requested, ledger.parent)


def cmd_skip(args: argparse.Namespace) -> int:
    """Record a skip for one nominal occurrence.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    entry = actions.skip(args.schedule, date.fromisoformat(args.date))
    return _emit([entry], args, "skip")


def cmd_move(args: argparse.Namespace) -> int:
    """Record a move for one nominal occurrence.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    entry = actions.move(
        args.schedule, date.fromisoformat(args.date), date.fromisoformat(args.new_date)
    )
    return _emit([entry], args, "move")


def cmd_create(args: argparse.Namespace) -> int:
    """Write a new schedule rule.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    day = date.fromisoformat(args.start)
    directives = [
        actions.new(
            args.schedule,
            day,
            rrule=args.rrule,
            start=day,
            match_account=args.account,
            match_payee=args.payee,
            match_amount=Decimal(args.amount) if args.amount else None,
            amount_mode=args.amount_mode,
            payee=args.write_payee,
            narration=args.narration,
        ),
        *(
            actions.posting(
                args.schedule,
                account,
                day,
                amount=Decimal(amount) if amount else None,
            )
            for account, amount in (args.posting or [])
        ),
    ]
    return _emit(directives, args, "new")


def cmd_edit(args: argparse.Namespace) -> int:
    """Edit a rule in place, or split its series on a cadence change.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    combined = _combined(entries, _schedules_path(args, ledger))
    result = compute(combined, options)
    rule = result.rule(args.schedule)
    if rule is None:
        print(f"unknown schedule: {args.schedule}", file=sys.stderr)
        return 1
    if args.rrule is not None or args.start is not None:
        print(
            "a cadence change splits the series: set `end` on the current rule "
            "and create a new one",
            file=sys.stderr,
        )
        return 1
    updated = actions.from_rule(
        _with_amount(rule, Decimal(args.amount)) if args.amount is not None else rule
    )
    if not args.write:
        for directive in updated:
            print(actions.render(directive))
        return 0
    target = _write_target(args, ledger)
    lineno = rule.entry.meta.get("lineno") if rule.entry else None
    if lineno is None:
        print("the rule has no source location to edit", file=sys.stderr)
        return 1
    writer.replace(target, int(lineno), updated[0])
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    """Recompute the schedules and rewrite their directives canonically.

    Re-running the forecast is idempotent, so a rebuild with no ``--write`` is a
    read-only no-op that proves the invariant.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit code.
    """
    ledger = Path(args.ledger)
    entries, options = _load(ledger)
    combined = _combined(entries, _schedules_path(args, ledger))
    result = compute(combined, options, today=_today(args))
    if not args.write:
        print(f"{len(result.rules)} schedule(s), {len(result.reports)} report(s)")
        return 0
    target = _write_target(args, ledger)
    edits: list[tuple[int, Custom | None]] = []
    for rule in result.rules:
        if rule.entry is None or not rule.entry.meta.get("lineno"):
            continue
        directives = actions.from_rule(rule)
        edits.append((int(rule.entry.meta["lineno"]), directives[0]))
        for spec, directive in zip(rule.postings, directives[1:], strict=True):
            if spec.entry is not None and spec.entry.meta.get("lineno"):
                edits.append((int(spec.entry.meta["lineno"]), directive))
    writer.rewrite(target, edits)
    return 0


def _with_amount(rule: Rule, amount: Decimal) -> Rule:
    """Return a copy of a rule with a new reference amount.

    Args:
        rule: The rule.
        amount: The new amount.

    Returns:
        The updated rule.
    """
    from dataclasses import replace  # noqa: PLC0415 - a single local use

    return replace(rule, match_amount=amount)


def _emit(entries: Sequence[Custom], args: argparse.Namespace, kind: str) -> int:
    """Print or write one or more directives.

    Args:
        entries: The directives.
        args: The parsed arguments.
        kind: The verb, for the message.

    Returns:
        The process exit code.
    """
    if not args.write:
        for entry in entries:
            print(actions.render(entry))
        return 0
    ledger = Path(args.ledger)
    target = _write_target(args, ledger)
    for entry in entries:
        writer.append(target, entry)
    print(f"wrote {kind} to {target}")
    return 0


# --- migrate -------------------------------------------------------------------


def cmd_migrate(args: argparse.Namespace) -> int:
    """Convert ``schedules/*.yaml`` to directives, idempotently.

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
    ledger_entries, _options = _load(ledger) if ledger.is_file() else ([], {})
    legacy = sum(
        1
        for entry in ledger_entries
        if getattr(entry, "meta", None) and "schedule_id" in entry.meta
    )
    print(f"; {legacy} enriched transaction(s) still carry schedule_id metadata")
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


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        The root parser.
    """
    parser = argparse.ArgumentParser(prog="beanschedule", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    _add_ledger(sub, "check", "Validate the schedules across a ledger", cmd_check)
    _add_ledger(sub, "report", "Show each schedule's occurrences", cmd_report)
    _add_ledger(sub, "list", "List schedules with next and overdue", cmd_list)

    forecast = _add_ledger(sub, "forecast", "Print upcoming occurrences", cmd_forecast)
    forecast.add_argument("--months", type=int, default=3, help="Months to forecast")

    detect = _add_ledger(
        sub, "detect", "Propose schedules for recurring payments", cmd_detect
    )
    detect.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )

    skip = _add_write(sub, "skip", "Record a skip for one occurrence", cmd_skip)
    skip.add_argument("schedule", help="The schedule id")
    skip.add_argument("date", help="The nominal date to skip")

    move = _add_write(sub, "move", "Record a move for one occurrence", cmd_move)
    move.add_argument("schedule", help="The schedule id")
    move.add_argument("date", help="The original nominal date")
    move.add_argument("new_date", help="The date to move it to")

    create = _add_write(sub, "create", "Create a new schedule rule", cmd_create)
    create.add_argument("schedule", help="The schedule id")
    create.add_argument("--rrule", required=True, help="The recurrence rule")
    create.add_argument("--start", required=True, help="The first nominal date")
    create.add_argument("--account", required=True, help="The matched account")
    create.add_argument(
        "--posting",
        nargs=2,
        action="append",
        metavar=("ACCOUNT", "AMOUNT"),
        help="An other-side posting (repeatable; omit AMOUNT to let Beancount balance)",
    )
    create.add_argument("--payee", help="A payee regex for matching")
    create.add_argument("--amount", help="The reference amount")
    create.add_argument(
        "--amount-mode",
        choices=["exact", "approx", "range", "any"],
        help="The amount mode",
    )
    create.add_argument("--write-payee", dest="write_payee", help="The payee to write")
    create.add_argument("--narration", help="The narration to write")

    edit = _add_write(sub, "edit", "Edit a schedule rule in place", cmd_edit)
    edit.add_argument("schedule", help="The schedule id")
    edit.add_argument("--amount", help="Set a new reference amount")
    edit.add_argument("--rrule", help="A new recurrence rule (splits the series)")
    edit.add_argument("--start", help="A new start (splits the series)")

    _add_write(
        sub, "rebuild", "Recompute and canonically rewrite the rules", cmd_rebuild
    )

    migrate = sub.add_parser(
        "migrate",
        help="Convert schedules/*.yaml to directives",
        description=(
            'Convert a schedules/ directory of YAML files to `custom "schedule"` '
            "directives, idempotently, and report enriched transactions still "
            "carrying schedule_id metadata."
        ),
    )
    migrate.add_argument("directory", help="The schedules directory")
    migrate.add_argument(
        "--ledger", help="The ledger, for the schedules file and report"
    )
    migrate.add_argument("--schedules", help="The Schedules.bean file")
    migrate.set_defaults(func=cmd_migrate)

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
    """Add a read-only command taking a ledger and an optional schedules file.

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
    parser.add_argument("--schedules", help="The Schedules.bean file")
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
    parser.add_argument("--schedules", help="The Schedules.bean file")
    parser.add_argument("--today", help="The reference date (YYYY-MM-DD)")
    parser.add_argument(
        "--write",
        nargs="?",
        const=SCHEDULES_FILE,
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
