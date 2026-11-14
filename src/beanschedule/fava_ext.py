"""The Fava report for schedules, read-only by default.

Load with::

    2026-01-01 custom "fava-extension" "beanschedule.fava_ext"

The report is **read-only unless a write goal is configured**. Add a ``write``
key naming the schedules file, relative to the ledger's directory, to let the
report reconcile matches and edit schedules::

    2026-01-01 custom "fava-extension" "beanschedule.fava_ext" "{'write': 'schedules.bean'}"

A path that escapes the ledger directory or is not a Beancount source file is
refused. Edits to an included file go through Fava's own file API (its lock,
watcher and printer), so Fava's editor and this report stay consistent; the
schedules file is not included by the ledger, so it is edited directly under
Fava's lock instead. The transactions themselves come from
:mod:`beanschedule.actions` and :mod:`beanschedule.reconcile`, the same modules
the CLI uses. The extension is the only module that imports Fava.

The report has three tabs, selected by the ``view`` query parameter: an
**Overview** of every schedule, an **Upcoming** ledger of all outstanding
occurrences across schedules, and a per-schedule **drill-down** that projects an
amortized loan's remaining payments and, when writing is configured, edits the
schedule's own Beancount source in place.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast

from beancount.core import data
from fava.core import file as fava_file
from fava.ext import ExtensionConfigError, FavaExtensionBase, extension_endpoint
from flask import jsonify, make_response, redirect, request

from beanschedule import actions, reconcile, recurrence, writer
from beanschedule.config import (
    DEFAULT_PENDING_FILE,
    DEFAULT_SCHEDULES_FILE,
    parse_config,
)
from beanschedule.config import (
    string as _string,
)
from beanschedule.core import ScheduleResult, compute, first_amount
from beanschedule.pending import load_pending_transactions
from beanschedule.plugin import load_schedules
from beanschedule.report import (
    AmortizationView,
    ScheduleRow,
    ScheduleView,
    ScheduleViewResult,
    UpcomingLine,
    build_view,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from beancount.core.data import Directive
    from fava.beans.abc import Directive as FavaDirective
    from fava.core import FavaLedger
    from flask import Response

    from beanschedule.pending import PendingTransaction

__all__ = ["Schedules"]

_DEFAULT_MONTHS = 3


class Schedules(FavaExtensionBase):
    """A report of schedules that can reconcile and edit them when configured."""

    report_title = "Schedules"

    #: Load the report's interactivity from Schedules.js, which Fava runs on
    #: every navigation to the report (an inline ``<script>`` in the template
    #: would not execute for a client-side navigation).
    has_js_module = True

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
        self._view: ScheduleViewResult | None = None
        try:
            plugin = _plugin_config(self.ledger.options)
            self.default_schedules = _string(
                plugin.get("schedules_file"), DEFAULT_SCHEDULES_FILE
            )
            self.default_pending = _string(
                plugin.get("pending_file"), DEFAULT_PENDING_FILE
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
        self._view = None

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
        """Build the report view, caching it for the request.

        Returns:
            The :class:`~beanschedule.report.ScheduleViewResult`.
        """
        if self._view is None:
            self._view = build_view(
                self._result(),
                self._entries(),
                self.ledger.options,
                today=date.today(),  # noqa: DTZ011 - the reference date is wall-clock
                forecast_months=self.default_months,
            )
        return self._view

    def money(self, value: Decimal | None) -> str:
        """Format an amount for the page.

        Args:
            value: The amount, or ``None``.

        Returns:
            The formatted amount, or ``-``.
        """
        currency = self.view().currency
        return "-" if value is None else f"{value:.2f} {currency}".strip()

    def accounts(self) -> tuple[str, ...]:
        """Return every open account, for the form's autocomplete.

        Returns:
            The account names, sorted. Empty when the ledger exposes none, so the
            report still renders under a minimal ledger object.
        """
        accounts = getattr(self.ledger, "accounts", None)
        if not accounts:
            return ()
        return tuple(sorted(str(name) for name in accounts))

    def rrule_fields(self, schedule_id: str | None) -> recurrence.RuleFields | None:
        """Decompose a schedule's recurrence rule for the edit form.

        Args:
            schedule_id: The schedule to decompose, or ``None`` for the first.

        Returns:
            The parsed :class:`~beanschedule.recurrence.RuleFields`, or ``None``
            when the schedule cannot be found.
        """
        result = self._result()
        sid = schedule_id
        if sid is None:
            sid = result.rules[0].id if result.rules else None
        if sid is None:
            return None
        rule = result.rule(sid)
        return None if rule is None else recurrence.rrule_fields(rule.rrule)

    def schedule(self, schedule_id: str | None) -> ScheduleView | None:
        """Return one schedule's view, for the drill-down.

        Args:
            schedule_id: The schedule to show, or ``None`` for the first.

        Returns:
            The :class:`~beanschedule.report.ScheduleView`, or ``None`` when
            there are no schedules or the id is unknown.
        """
        view = self.view()
        if schedule_id is None:
            return view.schedules[0] if view.schedules else None
        return view.schedule(schedule_id)

    def schedule_ids(self) -> tuple[str, ...]:
        """Return every schedule's id, in declaration order.

        Returns:
            The schedule ids.
        """
        return tuple(view.id for view in self.view().schedules)

    def amortization(self, schedule_id: str | None) -> AmortizationView | None:
        """Return a schedule's amortization projection, if it amortizes.

        Args:
            schedule_id: The schedule to show, or ``None`` for the first.

        Returns:
            The :class:`~beanschedule.report.AmortizationView`, or ``None``.
        """
        schedule = self.schedule(schedule_id)
        return schedule.amortization if schedule is not None else None

    def upcoming(self, *, pending_only: bool = True) -> tuple[UpcomingLine, ...]:
        """Return the cross-schedule upcoming ledger.

        Args:
            pending_only: When ``True``, show only the unresolved occurrences.

        Returns:
            The :class:`~beanschedule.report.UpcomingLine` rows, date-ordered.
        """
        return self.view().ledger(pending_only=pending_only)

    def rows(self, scope: str) -> tuple[ScheduleRow, ...]:
        """Return the Schedules table rows for a scope.

        Args:
            scope: ``"all"`` for one row per schedule, otherwise one row per
                outstanding occurrence.

        Returns:
            The :class:`~beanschedule.report.ScheduleRow` rows.
        """
        return self.view().rows(scope=scope)

    def schedule_source(self, schedule_id: str | None) -> str:
        """Render a schedule's directive, to seed the edit form.

        Args:
            schedule_id: The schedule to render, or ``None`` for the first.

        Returns:
            The Beancount text, or ``""`` when the schedule cannot be found.
        """
        result = self._result()
        sid = schedule_id
        if sid is None:
            sid = result.rules[0].id if result.rules else None
        if sid is None:
            return ""
        rule = result.rule(sid)
        if rule is None or rule.entry is None:
            return ""
        return actions.render(rule.entry)

    def schedule_diagnostics(
        self, schedule_id: str | None
    ) -> tuple[tuple[str, str], ...]:
        """Return the diagnostics that refer to one schedule.

        Args:
            schedule_id: The schedule id, or ``None`` for the first.

        Returns:
            ``(code, message)`` pairs for the schedule's errors and warnings.
        """
        result = self._result()
        sid = schedule_id
        if sid is None:
            sid = result.rules[0].id if result.rules else None
        if sid is None:
            return ()
        rule = result.rule(sid)
        if rule is None:
            return ()
        view = self.view()
        return tuple(
            (diagnostic.code, diagnostic.message)
            for diagnostic in (*view.errors, *view.warnings)
            if _refers_to(diagnostic.entry, rule.entry)
        )

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

    def perform(self, params: Mapping[str, object]) -> list[Directive]:
        """Apply a submitted action form.

        Args:
            params: The submitted fields: an ``action`` and its arguments. A
                repeated field (a posting row) may arrive as a list, as Fava's
                request form does.

        Returns:
            The transactions that were written.

        Raises:
            RuntimeError: If writing is not configured.
            ValueError: If the action is unknown or its fields are malformed.
        """
        if self.write_target is None:
            message = "writing is not configured for this report"
            raise RuntimeError(message)
        action = str(params.get("action", ""))
        if action == "create":
            entry = _schedule_entry(params, self.view().currency or "USD")
            self._write(self.write_target, entry)
            return [entry]
        if action == "update":
            return self._update(params)
        if action == "reconcile":
            return self._reconcile()
        if action == "save":
            return self._save(params)
        if action in ("skip", "move", "edit", "delete"):
            return self._edit_schedule(action, params)
        message = f"unknown action: {action}"
        raise ValueError(message)

    def _update(self, params: Mapping[str, object]) -> list[Directive]:
        """Rebuild a schedule from the structured form and splice it in place.

        The entry is rebuilt from the form's fields the same way a new one is,
        then written over the schedule's own line, so the ledger keeps a single
        source of truth and a schedule is never duplicated. A schedule without a
        source location is appended instead.

        Args:
            params: The submitted fields, with ``id`` (or ``original_id``) naming
                the schedule being replaced.

        Returns:
            The transaction that was written.

        Raises:
            RuntimeError: If writing is not configured.
        """
        if self.write_target is None:
            message = "writing is not configured for this report"
            raise RuntimeError(message)
        schedule_id = _form_value(params, "original_id") or _form_value(params, "id")
        entry = _schedule_entry(
            params, self.view().currency or "USD", schedule_id=schedule_id
        )
        rule = self._result().rule(schedule_id) if schedule_id else None
        if rule is None or rule.entry is None:
            self._write(self.write_target, entry)
            return [entry]
        lineno = writer.entry_lineno(rule.entry)
        filename = (rule.entry.meta or {}).get("filename")
        if lineno is None or filename is None:
            self._write(self.write_target, entry)
            return [entry]
        base = Path(self.ledger.beancount_file_path).parent
        target = writer.resolve_target(Path(str(filename)), base)
        _rewrite_source(self.ledger, target, [(lineno, entry)])
        self.after_load_file()
        return [entry]

    def _save(self, params: Mapping[str, object]) -> list[Directive]:
        """Replace a schedule with an edited Beancount source, or append it.

        The submitted ``source`` is parsed as a single schedule transaction and
        spliced back in place at the original schedule's line; when the schedule
        is new (or has no source location) it is appended instead. This gives the
        edit form every field — rrule, rate, escrow, term, method, payee and
        postings — without a bespoke field per key.

        Args:
            params: The submitted fields: ``source`` (the Beancount text) and an
                optional ``id`` naming the schedule being replaced.

        Returns:
            The transaction that was written.

        Raises:
            ValueError: If the source is malformed or not a single schedule.
        """
        from beancount.parser import parser  # noqa: PLC0415 - narrow local import

        if self.write_target is None:
            message = "writing is not configured for this report"
            raise RuntimeError(message)
        source = _form_value(params, "source")
        entries, errors, _options = parser.parse_string(source)
        if errors:
            message = "; ".join(
                str(getattr(error, "message", error)) for error in errors
            )
            raise ValueError(message)
        transactions = [
            entry for entry in entries if isinstance(entry, data.Transaction)
        ]
        if len(transactions) != 1:
            message = "the source must hold exactly one transaction"
            raise ValueError(message)
        entry = transactions[0]
        if not (entry.meta or {}).get("id"):
            message = "the schedule needs an `id` metadata key"
            raise ValueError(message)
        schedule_id = _form_value(params, "id")
        rule = self._result().rule(schedule_id) if schedule_id else None
        if rule is None or rule.entry is None:
            self._write(self.write_target, entry)
            return [entry]
        lineno = writer.entry_lineno(rule.entry)
        filename = (rule.entry.meta or {}).get("filename")
        if lineno is None or filename is None:
            self._write(self.write_target, entry)
            return [entry]
        base = Path(self.ledger.beancount_file_path).parent
        target = writer.resolve_target(Path(str(filename)), base)
        _rewrite_source(self.ledger, target, [(lineno, entry)])
        self.after_load_file()
        return [entry]

    def _reconcile(self) -> list[Directive]:
        """Apply the reconciliation plan, batching the edits per file.

        Returns:
            The transactions that were written (the enriched matches).
        """
        plan = self._plan()
        base = Path(self.ledger.beancount_file_path).parent
        edits, written, consumed = reconcile.plan_edits(plan, ledger_dir=base)
        self._queue_pending_removals(edits, consumed)
        for path, changes in edits.items():
            _rewrite_source(self.ledger, path, changes)
        self.after_load_file()
        return written

    def _queue_pending_removals(
        self,
        edits: dict[Path, list[tuple[int, Directive | None]]],
        consumed: Sequence[PendingTransaction],
    ) -> None:
        """Queue the removal of the consumed pending placeholders.

        Args:
            edits: The per-file edit lists.
            consumed: The pending placeholders the plan consumed.
        """
        keys = {(item.date, item.payee, item.amount) for item in consumed}
        if not keys:
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
            key = (entry.date, entry.payee, first_amount(entry))
            if key in keys:
                edits[Path(str(filename))].append((int(lineno), None))

    def _edit_schedule(
        self, action: str, params: Mapping[str, object]
    ) -> list[Directive]:
        """Skip, move, edit or delete a schedule's transaction.

        Args:
            action: The action name.
            params: The submitted fields, with ``id`` and its arguments.

        Returns:
            The transactions that were written.

        Raises:
            ValueError: If the schedule is unknown or has no source location.
        """
        schedule_id = _form_value(params, "id")
        rule = self._result().rule(schedule_id)
        if rule is None or rule.entry is None:
            message = f"unknown schedule: {schedule_id}"
            raise ValueError(message)
        lineno = writer.entry_lineno(rule.entry)
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
                replace(rule, match_amount=Decimal(_form_value(params, "amount"))),
                self.view().currency or "USD",
            )
        elif action == "skip":
            new_date = actions.next_frontier(rule)
            if new_date is None:
                _rewrite_source(self.ledger, target, [(lineno, None)])
                self.after_load_file()
                return []
            updated = actions.advance(rule, new_date)
        else:
            updated = actions.advance(
                rule, date.fromisoformat(_form_value(params, "new_date"))
            )
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
        params: Mapping[str, object] = request.form
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


def _refers_to(candidate: Directive | None, entry: Directive | None) -> bool:
    """Report whether a diagnostic's directive is the given schedule.

    A diagnostic is attached to a directive, so identity is the reliable link;
    where the engine attached none, the source location is compared instead.

    Args:
        candidate: The diagnostic's directive, if any.
        entry: The schedule's directive, if any.

    Returns:
        ``True`` when the diagnostic refers to the schedule.
    """
    if candidate is None or entry is None:
        return False
    if candidate is entry:
        return True
    left = getattr(candidate, "meta", None) or {}
    right = getattr(entry, "meta", None) or {}
    return (left.get("filename"), left.get("lineno")) == (
        right.get("filename"),
        right.get("lineno"),
    )


def _schedule_entry(
    params: Mapping[str, object],
    currency: str,
    *,
    schedule_id: str | None = None,
) -> Directive:
    """Build a schedule transaction from a structured form.

    The recurrence rule is composed from the form's builder fields, and the
    other-side postings from the repeated ``posting_account``/``posting_amount``
    rows, so no field of the entry has to be typed as raw ledger text.

    Args:
        params: The submitted fields.
        currency: The operating currency.
        schedule_id: The id to write, overriding the form's ``id``.

    Returns:
        The transaction.

    Raises:
        ValueError: If the id, start or builder fields are missing or malformed.
    """
    sid = schedule_id or _form_value(params, "id")
    start = _form_value(params, "start")
    if not sid:
        message = "the schedule needs an id"
        raise ValueError(message)
    if not start:
        message = "the schedule needs a start date"
        raise ValueError(message)
    day = date.fromisoformat(start)
    rrule = recurrence.build_rrule(
        _form_value(params, "freq") or "MONTHLY",
        interval=_int_field(params, "interval", 1),
        byday=_form_values(params, "byday"),
        bymonthday=_optional_int_field(params, "bymonthday"),
        bymonth=_optional_int_field(params, "bymonth"),
    )
    postings: list[tuple[str, Decimal | None, Mapping[str, object] | None]] = []
    accounts = _form_list(params, "posting_account")
    amounts = _form_list(params, "posting_amount")
    legs = _form_list(params, "posting_leg")
    for index, account in enumerate(accounts):
        if not account:
            continue
        amount = amounts[index] if index < len(amounts) else ""
        leg = legs[index] if index < len(legs) else ""
        metadata = {"schedule-leg": leg} if leg else None
        postings.append((account, Decimal(amount) if amount else None, metadata))
    amount = _form_value(params, "amount")
    tolerance = _form_value(params, "tolerance")
    end = _form_value(params, "end")
    extra: dict[str, object] = {}
    method = _form_value(params, "method")
    if method:
        extra["method"] = method
        extra["rate"] = Decimal(_form_value(params, "rate") or "0")
        term = _form_value(params, "term")
        if term:
            extra["term"] = Decimal(term)
    escrow = _form_value(params, "escrow")
    if escrow:
        extra["escrow"] = Decimal(escrow)
    return actions.schedule_transaction(
        sid,
        day,
        rrule=rrule,
        match_account=_form_value(params, "account"),
        currency=currency,
        payee=_form_value(params, "payee") or None,
        narration=_form_value(params, "narration") or None,
        match_payee=_form_value(params, "match_payee") or None,
        match_amount=Decimal(amount) if amount else None,
        amount_tolerance=Decimal(tolerance) if tolerance else None,
        end=date.fromisoformat(end) if end else None,
        postings=postings,
        metadata=extra,
    )


def _form_value(params: Mapping[str, object], key: str) -> str:
    """Return a single field as a stripped string.

    Args:
        params: The submitted fields; a repeated field may hold a list.
        key: The field name.

    Returns:
        The first value, as a string, or ``""``.
    """
    value = params.get(key)
    if isinstance(value, list | tuple):
        value = value[0] if value else None
    return "" if value is None else str(value)


def _form_values(params: Mapping[str, object], key: str) -> list[str]:
    """Return a repeated field's non-empty values as strings.

    Fava's request form exposes repeated fields through ``getlist``; a plain
    mapping (as tests submit) may instead carry a list. Both are accepted, and
    blank rows are dropped so an empty posting row never becomes a posting.

    Args:
        params: The submitted fields.
        key: The field name.

    Returns:
        The non-empty values, in order.
    """
    return [value for value in _form_list(params, key) if value]


def _form_list(params: Mapping[str, object], key: str) -> list[str]:
    """Return a repeated field's values as strings, in order, blanks included.

    Positional alignment matters for the posting rows: a blank amount or leg
    must stay beside its account, so unlike :func:`_form_values` this keeps the
    empty entries.

    Args:
        params: The submitted fields.
        key: The field name.

    Returns:
        The values, in order.
    """
    getlist = getattr(params, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(key)]
    raw = params.get(key)
    if raw is None:
        return []
    if isinstance(raw, list | tuple):
        return [str(value) for value in raw]
    return [str(raw)]


def _int_field(params: Mapping[str, object], key: str, default: int) -> int:
    """Return an integer field, falling back to a default.

    Args:
        params: The submitted fields.
        key: The field name.
        default: The value to use when the field is blank or unparseable.

    Returns:
        The parsed integer, or the default.
    """
    value = _form_value(params, key)
    return int(value) if value else default


def _optional_int_field(params: Mapping[str, object], key: str) -> int | None:
    """Return an optional integer field.

    Args:
        params: The submitted fields.
        key: The field name.

    Returns:
        The parsed integer, or ``None`` when the field is blank.
    """
    value = _form_value(params, key)
    return int(value) if value else None


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


def _rewrite_source(
    ledger: FavaLedger,
    path: Path,
    edits: list[tuple[int, Directive | None]],
) -> None:
    """Rewrite a file's directives, in place.

    The included files are edited through Fava's own file API, which detects an
    external change and reloads the ledger. The schedules file is deliberately
    *not* included by the ledger, so Fava refuses it as a non-source file; it is
    edited directly instead, under Fava's lock, the same way the append path
    already writes it, and the ledger is reloaded so the plugin re-validates it.

    Args:
        ledger: The Fava ledger.
        path: The file to rewrite.
        edits: ``(lineno, entry)`` pairs; ``None`` deletes the directive.
    """
    if str(path) in ledger.options.get("include", ()):
        source, sha256sum = ledger.file.get_source(path)
        updated = writer.apply_edits(source.splitlines(keepends=True), edits)
        ledger.file.set_source(path, "".join(updated), sha256sum)
        return
    with ledger.file._lock:  # noqa: SLF001 - Fava's own lock is the point
        writer.rewrite(path, edits)
        ledger.watcher.notify(path)
        ledger.load_file()
