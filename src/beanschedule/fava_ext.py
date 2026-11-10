"""The Fava report for schedules, read-only by default.

Load with::

    2026-01-01 custom "fava-extension" "beanschedule.fava_ext"

The report is **read-only unless a write goal is configured**. Add a ``write``
key naming the schedules file, relative to the ledger's directory, to let the
report reconcile matches and edit schedules::

    2026-01-01 custom "fava-extension" "beanschedule.fava_ext" "{'write': 'schedules.bean'}"

A path that escapes the ledger directory or is not a Beancount source file is
refused. Writes go through Fava's own file API (its lock, watcher and printer),
so Fava's editor and this report stay consistent; the transactions themselves
come from :mod:`beanschedule.actions` and :mod:`beanschedule.reconcile`, the same
modules the CLI uses. The extension is the only module that imports Fava.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast

from beancount.core import data
from fava.core import file as fava_file
from fava.ext import ExtensionConfigError, FavaExtensionBase, extension_endpoint
from flask import jsonify, make_response, redirect, request

from beanschedule import actions, reconcile, writer
from beanschedule.config import parse_config
from beanschedule.core import ScheduleResult, compute
from beanschedule.pending import load_pending_transactions
from beanschedule.plugin import load_schedules
from beanschedule.report import ScheduleViewResult, build_view

if TYPE_CHECKING:
    from collections.abc import Mapping

    from beancount.core.data import Directive, Transaction
    from fava.beans.abc import Directive as FavaDirective
    from fava.core import FavaLedger
    from flask import Response

    from beanschedule.pending import PendingTransaction

__all__ = ["Schedules"]

_DEFAULT_MONTHS = 3
_DEFAULT_SCHEDULES_FILE = "schedules.bean"
_DEFAULT_PENDING_FILE = "pending.bean"


class Schedules(FavaExtensionBase):
    """A report of schedules that can reconcile and edit them when configured."""

    report_title = "Schedules"

    def __init__(self, ledger: FavaLedger, config: str | None = None) -> None:
        """Initialise the extension.

        Args:
            ledger: The Fava ledger.
            config: The optional extension config. A mapping may set a ``write``
                key — ``true`` to enable writing to the schedules file named by
                the plugin, or a string to name a different file — and a
                ``months`` key (how many months of future occurrences to show).
                The schedules and pending files are read from the
                ``beanschedule.plugin`` directive's config, so they are not
                repeated here.

        Raises:
            ExtensionConfigError: If the write goal escapes the ledger
                directory or is not a Beancount source file.
        """
        super().__init__(ledger, config)
        self.result: ScheduleResult | None = None
        self._schedules: list[Directive] | None = None
        self._pending: list[PendingTransaction] | None = None
        try:
            plugin = _plugin_config(self.ledger.options)
            self.default_schedules = _string(
                plugin.get("schedules_file"), _DEFAULT_SCHEDULES_FILE
            )
            self.default_pending = _string(
                plugin.get("pending_file"), _DEFAULT_PENDING_FILE
            )
            self.write_target = self._resolve_write(_write_setting(self.config))
            self.default_months = _months_setting(self.config)
        except (TypeError, ValueError) as error:
            raise ExtensionConfigError(SyntaxError(str(error)), config or "") from error

    def _resolve_write(self, value: object) -> Path | None:
        """Resolve the configured write goal, refusing an unsafe path.

        Args:
            value: The ``write`` config value: ``None``/``False`` for read-only,
                ``True`` to write the plugin's schedules file, or a string to
                name a different file.

        Returns:
            The absolute goal path, or ``None`` when writing is not configured.
        """
        if value is None or value is False:
            return None
        base = Path(self.ledger.beancount_file_path).parent
        target = self.default_schedules if value is True else str(value)
        return writer.resolve_target(Path(target), base)

    @property
    def writable(self) -> bool:
        """Whether a write goal is configured, so the report can edit.

        Returns:
            ``True`` when the report may write schedules.
        """
        return self.write_target is not None

    def after_load_file(self) -> None:
        """Drop the cached result once the ledger has been reloaded."""
        self.result = None
        self._schedules = None
        self._pending = None

    def _entries(self) -> list[Directive]:
        """Return the ledger's entries as Beancount directives.

        Returns:
            The entries.
        """
        return cast("list[Directive]", list(self.ledger.all_entries))

    def _schedules_file(self) -> Path:
        """Return the schedules file path.

        Returns:
            The configured write target, or the default beside the ledger.
        """
        if self.write_target is not None:
            return self.write_target
        base = Path(self.ledger.beancount_file_path).parent
        return base / self.default_schedules

    def _schedule_entries(self) -> list[Directive]:
        """Return the schedule transactions, loading them once.

        Returns:
            The schedule transactions.
        """
        if self._schedules is None:
            self._schedules = load_schedules(self._schedules_file())
        return self._schedules

    def _pending_file(self) -> Path:
        """Return the pending file path.

        Returns:
            The configured pending file, or the default beside the ledger.
        """
        requested = Path(self.default_pending)
        base = Path(self.ledger.beancount_file_path).parent
        return requested if requested.is_absolute() else base / requested

    def _pending_transactions(self) -> list[PendingTransaction]:
        """Return the pending transactions, loading them once.

        Returns:
            The pending transactions, or an empty list when the file is absent.
        """
        if self._pending is None:
            path = self._pending_file()
            self._pending = load_pending_transactions(path) if path.is_file() else []
        return self._pending

    def _result(self) -> ScheduleResult:
        """Return the computed result, computing it once on first use.

        Returns:
            The :class:`~beanschedule.core.ScheduleResult`.
        """
        if self.result is None:
            self.result = compute(
                self._entries(),
                self.ledger.options,
                schedules=self._schedule_entries(),
                today=date.today(),  # noqa: DTZ011 - the reference date is wall-clock
            )
        return self.result

    def view(self) -> ScheduleViewResult:
        """Build the report view.

        Returns:
            The :class:`~beanschedule.report.ScheduleViewResult`.
        """
        return build_view(
            self._result(),
            self._entries(),
            self.ledger.options,
            today=date.today(),  # noqa: DTZ011 - the reference date is wall-clock
            forecast_months=self.default_months,
        )

    def money(self, value: Decimal | None) -> str:
        """Format an amount for the page.

        Args:
            value: The amount, or ``None``.

        Returns:
            The formatted amount, or ``-``.
        """
        currency = self.view().currency
        return "-" if value is None else f"{value:.2f} {currency}".strip()

    def _plan(self) -> reconcile.Plan:
        """Build the reconciliation plan for the current ledger.

        Returns:
            The plan.
        """
        return reconcile.plan(
            self._entries(),
            self._schedule_entries(),
            self._pending_transactions(),
            self.ledger.options,
            today=date.today(),  # noqa: DTZ011 - the reference date is wall-clock
        )

    def reconcile_count(self) -> int:
        """Return the number of matches reconciliation would make.

        Returns:
            The count of schedule and pending matches.
        """
        plan = self._plan()
        return len(plan.matches) + len(plan.pending)

    def perform(self, params: Mapping[str, str]) -> list[Directive]:
        """Apply a submitted action form.

        Args:
            params: The submitted fields: an ``action`` and its arguments.

        Returns:
            The transactions that were written.

        Raises:
            RuntimeError: If writing is not configured.
            ValueError: If the action is unknown or its fields are malformed.
        """
        if self.write_target is None:
            message = "writing is not configured for this report"
            raise RuntimeError(message)
        action = params.get("action", "")
        if action == "create":
            entry = _create_entry(params, self.view().currency or "USD")
            self._write(self.write_target, entry)
            return [entry]
        if action == "reconcile":
            return self._reconcile()
        if action in ("skip", "move", "edit", "delete"):
            return self._edit_schedule(action, params)
        message = f"unknown action: {action}"
        raise ValueError(message)

    def _reconcile(self) -> list[Directive]:
        """Apply the reconciliation plan, batching the edits per file.

        Returns:
            The transactions that were written (the enriched matches).
        """
        plan = self._plan()
        base = Path(self.ledger.beancount_file_path).parent
        edits: dict[Path, list[tuple[int, Directive | None]]] = defaultdict(list)
        written: list[Directive] = []
        for match in plan.matches:
            enriched = reconcile.enrich(match)
            self._queue(edits, match.transaction, enriched, base)
            written.append(enriched)
        for match in plan.pending:
            enriched = reconcile.enrich_pending(match)
            self._queue(edits, match.transaction, enriched, base)
            written.append(enriched)
        for advance in plan.advances:
            entry = advance.rule.entry
            lineno = _lineno(entry)
            if entry is None or lineno is None:
                continue
            filename = (entry.meta or {}).get("filename")
            if filename is None:
                continue
            target = writer.resolve_target(Path(str(filename)), base)
            if advance.new_date is None:
                edits[target].append((lineno, None))
            else:
                updated = actions.advance(advance.rule, advance.new_date)
                edits[target].append((lineno, updated))
        self._queue_pending_removals(edits, plan)
        for path, changes in edits.items():
            _rewrite_source(self.ledger, path, changes)
        self.after_load_file()
        return written

    def _queue(
        self,
        edits: dict[Path, list[tuple[int, Directive | None]]],
        original: Directive,
        updated: Directive,
        base: Path,
    ) -> None:
        """Queue an in-place edit of a transaction's own source file.

        Args:
            edits: The per-file edit lists.
            original: The transaction being replaced.
            updated: Its replacement.
            base: The ledger directory.
        """
        meta = getattr(original, "meta", None) or {}
        filename = meta.get("filename")
        lineno = meta.get("lineno")
        if filename is None or lineno is None:
            return
        target = writer.resolve_target(Path(str(filename)), base)
        edits[target].append((int(lineno), updated))

    def _queue_pending_removals(
        self,
        edits: dict[Path, list[tuple[int, Directive | None]]],
        plan: reconcile.Plan,
    ) -> None:
        """Queue the removal of the consumed pending placeholders.

        Args:
            edits: The per-file edit lists.
            plan: The applied plan.
        """
        consumed = {
            (match.pending.date, match.pending.payee, match.pending.amount)
            for match in plan.pending
        }
        if not consumed:
            return
        pending_name = self._pending_file().name
        for entry in self._entries():
            if not isinstance(entry, data.Transaction):
                continue
            meta = entry.meta or {}
            filename = meta.get("filename")
            lineno = meta.get("lineno")
            if filename is None or lineno is None:
                continue
            if Path(str(filename)).name != pending_name:
                continue
            key = (entry.date, entry.payee, _first_amount(entry))
            if key in consumed:
                edits[Path(str(filename))].append((int(lineno), None))

    def _edit_schedule(self, action: str, params: Mapping[str, str]) -> list[Directive]:
        """Skip, move, edit or delete a schedule's transaction.

        Args:
            action: The action name.
            params: The submitted fields, with ``id`` and its arguments.

        Returns:
            The transactions that were written.

        Raises:
            ValueError: If the schedule is unknown or has no source location.
        """
        rule = self._result().rule(params["id"])
        if rule is None or rule.entry is None:
            message = f"unknown schedule: {params['id']}"
            raise ValueError(message)
        lineno = _lineno(rule.entry)
        filename = (rule.entry.meta or {}).get("filename")
        if lineno is None or filename is None:
            message = "the schedule has no source location to edit"
            raise ValueError(message)
        base = Path(self.ledger.beancount_file_path).parent
        target = writer.resolve_target(Path(str(filename)), base)
        if action == "delete":
            _rewrite_source(self.ledger, target, [(lineno, None)])
            self.after_load_file()
            return []
        if action == "edit":
            from dataclasses import replace  # noqa: PLC0415 - a single local use

            updated = actions.from_rule(
                replace(rule, match_amount=Decimal(params["amount"])),
                self.view().currency or "USD",
            )
        elif action == "skip":
            from beanschedule import recurrence  # noqa: PLC0415

            new_date = recurrence.next_after(
                rule.rrule, rule.start, rule.start, end=rule.end
            )
            if new_date is None:
                _rewrite_source(self.ledger, target, [(lineno, None)])
                self.after_load_file()
                return []
            updated = actions.advance(rule, new_date)
        else:
            updated = actions.advance(rule, date.fromisoformat(params["new_date"]))
        _rewrite_source(self.ledger, target, [(lineno, updated)])
        self.after_load_file()
        return [updated]

    def _write(self, path: Path, entry: Directive) -> None:
        """Append a directive through Fava's file API.

        Args:
            path: The file to append to.
            entry: The directive.
        """
        options = self.ledger.fava_options
        with self.ledger.file._lock:  # noqa: SLF001 - Fava's own lock is the point
            fava_entry = cast("FavaDirective", entry)
            written, _ = fava_file.insert_entry(
                fava_entry,
                str(path),
                [],
                options.currency_column,
                options.indent,
            )
            self.ledger.watcher.notify(written)
            self.ledger.extensions.after_insert_entry(fava_entry)

    @extension_endpoint("commit", ["POST"])
    def commit(self) -> Response:
        """Apply a submitted form, then return.

        Returns:
            JSON, or a redirect back to the report.
        """
        params = request.form.to_dict()
        as_json = params.get("format") == "json"
        try:
            self.perform(params)
        except (KeyError, ValueError, RuntimeError) as error:
            if as_json:
                return make_response(jsonify({"error": str(error)}), 400)
            raise
        if as_json:
            return make_response(jsonify({"status": "ok"}))
        report = request.path.rpartition("/")[0] + "/"
        return cast("Response", redirect(request.referrer or report))


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


def _first_amount(entry: Transaction) -> Decimal | None:
    """Return a transaction's first posting amount.

    Args:
        entry: The transaction.

    Returns:
        The amount, or ``None``.
    """
    for posting in entry.postings:
        if posting.units is not None:
            return posting.units.number
    return None


def _create_entry(params: Mapping[str, str], currency: str) -> Directive:
    """Build a schedule transaction from a create form.

    Args:
        params: The submitted fields. ``postings`` is one ``ACCOUNT [AMOUNT]``
            pair per line; ``amount`` is the matched amount.
        currency: The operating currency.

    Returns:
        The transaction.
    """
    day = date.fromisoformat(params["start"])
    amount = params.get("amount")
    postings: list[tuple[str, Decimal | None, None]] = []
    for line in params.get("postings", "").splitlines():
        parts = line.split()
        if not parts:
            continue
        postings.append((parts[0], Decimal(parts[1]) if len(parts) > 1 else None, None))
    return actions.schedule_transaction(
        params["id"],
        day,
        rrule=params["rrule"],
        match_account=params["account"],
        currency=currency,
        payee=params.get("payee") or None,
        narration=params.get("narration") or None,
        match_amount=Decimal(amount) if amount else None,
        postings=postings,
    )


def _write_setting(config: object) -> object:
    """Read the ``write`` setting from the extension config.

    The config is the string after the ``custom "fava-extension"`` directive, a
    Python-literal mapping such as ``"{'write': true}"`` or
    ``"{'write': 'schedules.bean'}"``.

    Args:
        config: The raw config.

    Returns:
        ``True`` to write the plugin's schedules file, a string to name a
        different file, or ``None`` when writing is not configured.
    """
    mapping = parse_config(config)
    return None if mapping is None else mapping.get("write")


def _months_setting(config: object) -> int:
    """Read the ``months`` setting from the extension config.

    Args:
        config: The raw config.

    Returns:
        The number of months, defaulting to :data:`_DEFAULT_MONTHS`.
    """
    mapping = parse_config(config)
    if mapping is not None:
        value = mapping.get("months")
        if isinstance(value, int) and value > 0:
            return value
    return _DEFAULT_MONTHS


def _plugin_config(options: Mapping[str, object]) -> dict[str, object]:
    """Read the beanschedule plugin's config from the ledger options.

    Beancount exposes every ``plugin`` directive in ``options["plugin"]`` as an
    ``(name, config)`` pair, so the extension shares the plugin's config rather
    than repeating it.

    Args:
        options: The Beancount options map.

    Returns:
        The plugin config mapping, or an empty mapping when the plugin is absent.
    """
    plugins = options.get("plugin")
    if not isinstance(plugins, list | tuple):
        return {}
    for entry in plugins:
        if (
            isinstance(entry, tuple)
            and len(entry) >= 2  # noqa: PLR2004 - a (name, config) pair
            and entry[0] == "beanschedule.plugin"
        ):
            return parse_config(entry[1]) or {}
    return {}


def _string(value: object, default: str) -> str:
    """Return a config value as a non-empty string.

    Args:
        value: The raw value.
        default: The fallback.

    Returns:
        The string, or the default.
    """
    return value if isinstance(value, str) and value else default


def _rewrite_source(
    ledger: FavaLedger,
    path: Path,
    edits: list[tuple[int, Directive | None]],
) -> None:
    """Rewrite a source file's directives through Fava's own file API.

    Args:
        ledger: The Fava ledger.
        path: The source file to rewrite.
        edits: ``(lineno, entry)`` pairs; ``None`` deletes the directive.
    """
    source, sha256sum = ledger.file.get_source(path)
    updated = writer.apply_edits(source.splitlines(keepends=True), edits)
    ledger.file.set_source(path, "".join(updated), sha256sum)
