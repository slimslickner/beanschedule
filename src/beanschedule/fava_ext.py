"""The Fava report for schedules, read-only by default.

Load with::

    2026-01-01 custom "fava-extension" "beanschedule.fava_ext"

The report is **read-only unless a write goal is configured**. Add a ``write``
key naming a Beancount file, relative to the ledger's directory, to let the
report append and edit ``custom "schedule"`` directives::

    2026-01-01 custom "fava-extension" "beanschedule.fava_ext" "{'write': 'Schedules.bean'}"

A path that escapes the ledger directory or is not a Beancount source file is
refused. Writes go through Fava's own file API (its lock, watcher and printer),
so Fava's editor and this report stay consistent; the directives themselves come
from :mod:`beanschedule.actions`, the same module the CLI uses.

The extension is the only module that imports Fava. The view it renders is built
by :func:`beanschedule.report.build_view`, the same function the CLI uses, so the
terminal and the page cannot disagree.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fava.core import file as fava_file
from fava.ext import ExtensionConfigError, FavaExtensionBase, extension_endpoint
from flask import jsonify, make_response, redirect, request

from beanschedule import actions, writer
from beanschedule.config import parse_config
from beanschedule.core import ScheduleResult, compute
from beanschedule.report import ScheduleViewResult, build_view

if TYPE_CHECKING:
    from collections.abc import Mapping

    from beancount.core.data import Custom, Directive
    from fava.beans.abc import Directive as FavaDirective
    from fava.core import FavaLedger
    from flask import Response

    from beanschedule.core import Rule

__all__ = ["Schedules"]

_DEFAULT_MONTHS = 3


class Schedules(FavaExtensionBase):
    """A report of schedules that can edit them when configured."""

    report_title = "Schedules"

    def __init__(self, ledger: FavaLedger, config: str | None = None) -> None:
        """Initialise the extension.

        Args:
            ledger: The Fava ledger.
            config: The optional extension config. A mapping may set a ``write``
                key (the file to write directives to, relative to the ledger
                directory; writing stays off when absent) and a ``months`` key
                (how many months of future occurrences to show).

        Raises:
            ExtensionConfigError: If the write goal escapes the ledger
                directory or is not a Beancount source file.
        """
        super().__init__(ledger, config)
        self.result: ScheduleResult | None = None
        try:
            self.write_target = self._resolve_write(_write_setting(self.config))
            self.default_months = _months_setting(self.config)
        except (TypeError, ValueError) as error:
            raise ExtensionConfigError(SyntaxError(str(error)), config or "") from error

    def _resolve_write(self, value: str | None) -> Path | None:
        """Resolve the configured write goal, refusing an unsafe path.

        Args:
            value: The configured ``write`` path, or ``None``.

        Returns:
            The absolute goal path, or ``None`` when writing is not configured.
        """
        if value is None:
            return None
        base = Path(self.ledger.beancount_file_path).parent
        return writer.resolve_target(Path(value), base)

    @property
    def writable(self) -> bool:
        """Whether a write goal is configured, so the report can edit.

        Returns:
            ``True`` when the report may write directives.
        """
        return self.write_target is not None

    def after_load_file(self) -> None:
        """Drop the cached result once the ledger has been reloaded."""
        self.result = None

    def _entries(self) -> list[Directive]:
        """Return the ledger's entries as Beancount directives.

        Returns:
            The entries.
        """
        return cast("list[Directive]", list(self.ledger.all_entries))

    def _result(self) -> ScheduleResult:
        """Return the computed result, computing it once on first use.

        Returns:
            The :class:`~beanschedule.core.ScheduleResult`.
        """
        if self.result is None:
            self.result = compute(
                self._entries(),
                self.ledger.options,
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

    def perform(self, params: Mapping[str, str]) -> list[Custom]:
        """Apply a submitted action form.

        Args:
            params: The submitted fields: an ``action`` and its arguments.

        Returns:
            The directives that were written, empty for a delete.

        Raises:
            RuntimeError: If writing is not configured.
            ValueError: If the action is unknown or its fields are malformed.
        """
        if self.write_target is None:
            message = "writing is not configured for this report"
            raise RuntimeError(message)
        action = params.get("action", "")
        if action == "create":
            entries = _create_entries(params)
            for entry in entries:
                _insert(self.ledger, self.write_target, entry)
            return entries
        if action == "skip":
            entry = actions.skip(params["id"], date.fromisoformat(params["date"]))
            _insert(self.ledger, self.write_target, entry)
            return [entry]
        if action == "move":
            entry = actions.move(
                params["id"],
                date.fromisoformat(params["date"]),
                date.fromisoformat(params["new_date"]),
            )
            _insert(self.ledger, self.write_target, entry)
            return [entry]
        if action == "edit":
            return self._edit(params)
        if action == "delete":
            lineno = int(params["lineno"])
            _rewrite_source(self.ledger, self.write_target, [(lineno, None)])
            return []
        message = f"unknown action: {action}"
        raise ValueError(message)

    def _edit(self, params: Mapping[str, str]) -> list[Custom]:
        """Rewrite a rule's directive in place with a new amount.

        Args:
            params: The submitted fields, with ``id`` and ``amount``.

        Returns:
            The directive that was written.

        Raises:
            ValueError: If the schedule is unknown or has no source location.
        """
        rule = self._result().rule(params["id"])
        if rule is None or rule.entry is None:
            message = f"unknown schedule: {params['id']}"
            raise ValueError(message)
        lineno = rule.entry.meta.get("lineno")
        if lineno is None or self.write_target is None:
            message = "the rule has no source location to edit"
            raise ValueError(message)
        updated = actions.from_rule(_with_amount(rule, Decimal(params["amount"])))[0]
        _rewrite_source(self.ledger, self.write_target, [(int(lineno), updated)])
        return [updated]

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


def _create_entries(params: Mapping[str, str]) -> list[Custom]:
    """Build a ``new`` directive and its postings from a create form.

    Args:
        params: The submitted fields. ``postings`` is one ``ACCOUNT [AMOUNT]``
            pair per line; ``amount`` is the matched-account reference.

    Returns:
        The directives, the ``new`` first.
    """
    day = date.fromisoformat(params["start"])
    amount = params.get("amount")
    directives = [
        actions.new(
            params["id"],
            day,
            rrule=params["rrule"],
            start=day,
            match_account=params["account"],
            match_payee=params.get("match_payee") or None,
            match_amount=Decimal(amount) if amount else None,
            payee=params.get("payee") or None,
            narration=params.get("narration") or None,
        )
    ]
    for line in params.get("postings", "").splitlines():
        parts = line.split()
        if not parts:
            continue
        directives.append(
            actions.posting(
                params["id"],
                parts[0],
                day,
                amount=Decimal(parts[1]) if len(parts) > 1 else None,
            )
        )
    return directives


def _write_setting(config: object) -> str | None:
    """Read the ``write`` path from the extension config.

    The config is the string after the ``custom "fava-extension"`` directive, a
    Python-literal mapping such as ``"{'write': 'Schedules.bean'}"``.

    Args:
        config: The raw config.

    Returns:
        The path, or ``None`` when writing is not configured.
    """
    mapping = parse_config(config)
    if mapping is None:
        return None
    value = mapping.get("write")
    return str(value) if value else None


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


def _insert(ledger: FavaLedger, path: Path, entry: Custom) -> None:
    """Append a directive through Fava's own file API.

    Args:
        ledger: The Fava ledger.
        path: The file to append to.
        entry: The directive.
    """
    options = ledger.fava_options
    with ledger.file._lock:  # noqa: SLF001 - Fava's own lock is the point
        fava_entry = cast("FavaDirective", entry)
        written, _ = fava_file.insert_entry(
            fava_entry,
            str(path),
            [],
            options.currency_column,
            options.indent,
        )
        ledger.watcher.notify(written)
        ledger.extensions.after_insert_entry(fava_entry)


def _rewrite_source(
    ledger: FavaLedger,
    path: Path,
    edits: list[tuple[int, Custom | None]],
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
