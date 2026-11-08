"""The Beancount plugin entry point.

Load with::

    plugin "beanschedule.plugin"

The plugin calls :func:`beanschedule.core.compute`, returns the entries
unchanged and appends the validation diagnostics as ordinary Beancount errors,
so Fava lists them on its errors page. Errors never stop the ledger from
loading.

Pass ``"forecast"`` to also inject ``#``-flagged forecast transactions for each
schedule's upcoming occurrences, so future balances project in the ledger::

    plugin "beanschedule.plugin" "forecast"

Forecast injection requires the two-ledger split: the import ledger excludes the
plugin, so the hook never sees the injected entries as existing ones.

Beancount runs ``beancount.ops.pad`` after every user plugin, so a plugin never
sees the transactions ``pad`` synthesizes. To report the same occurrences the CLI
does, the plugin applies ``pad`` to a working copy before computing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, NamedTuple

from beancount.core import amount as bc_amount
from beancount.core import data
from beancount.ops import pad as pad_ops

from beanschedule.config import parse_config
from beanschedule.core import (
    Diagnostic,
    Rule,
    ScheduleResult,
    Split,
    amortization_splits,
    amortized_accounts,
    compute,
    ledger_balances,
    resolve_postings,
)
from beanschedule.report import operating_currency

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from beancount.core.data import Directive

__all__ = ["__plugins__", "forecast_entries", "plugin"]

#: The plugin functions for Beancount to run, discovered via ``__plugins__``.
__plugins__ = ["plugin"]

#: The config value that switches on forecast injection.
_CONFIG_FORECAST = "forecast"

#: How many months of future occurrences are injected by default.
_DEFAULT_FORECAST_MONTHS = 3

#: The metadata key written on a matched or forecast transaction.
SCHEDULE_KEY = "schedule"

#: The metadata key marking an injected forecast transaction.
FORECAST_KEY = "schedule-forecast"


class ScheduleError(NamedTuple):
    """A Beancount-compatible error.

    Attributes:
        source: The ledger location, a ``filename``/``lineno`` mapping.
        message: The rendered message.
        entry: The directive the error refers to, if any.
    """

    source: Mapping[str, object]
    message: str
    entry: Directive | None


@dataclass(frozen=True, slots=True)
class _Config:
    """The plugin's resolved configuration.

    Attributes:
        forecast: Whether to inject forecast transactions.
        months: How many months forward to forecast.
    """

    forecast: bool = False
    months: int = _DEFAULT_FORECAST_MONTHS


def plugin(
    entries: list[Directive],
    options_map: Mapping[str, object],
    config: str | Mapping[str, object] | None = None,
) -> tuple[list[Directive], list[ScheduleError]]:
    """Validate the ledger and, opt-in, inject forecast transactions.

    Args:
        entries: The ledger entries.
        options_map: The Beancount options map.
        config: The plugin config, ``"forecast"`` or a mapping.

    Returns:
        The entries, with forecast transactions appended when enabled, and the
        list of errors and warnings.
    """
    resolved = _config(config)
    today = date.today()  # noqa: DTZ011 - the forecast window is wall-clock
    padded = _with_padding(entries, options_map)
    # Overdue (W001) is a report concern, not a load error, so the reference date
    # is only used for the forecast window, not the diagnostics.
    result = compute(padded, options_map)
    errors = [_to_error(diagnostic, options_map) for diagnostic in result.diagnostics]
    if not resolved.forecast:
        return entries, errors
    forecast = forecast_entries(
        result,
        padded,
        options_map,
        months=resolved.months,
        today=today,
    )
    return [*entries, *forecast], errors


def _config(config: str | Mapping[str, object] | None) -> _Config:
    """Resolve the plugin config.

    The config is the string after the ``plugin`` directive, either the bare
    word ``"forecast"`` or a Python-literal mapping, e.g.
    ``"{'forecast': True, 'months': 3}"``.

    Args:
        config: The raw config value.

    Returns:
        The resolved :class:`_Config`.
    """
    if config is None:
        return _Config()
    if isinstance(config, str) and config.strip().lower() == _CONFIG_FORECAST:
        return _Config(forecast=True)
    mapping = parse_config(config)
    if mapping is None:
        return _Config()
    forecast = bool(mapping.get("forecast", False))
    months = mapping.get("months", _DEFAULT_FORECAST_MONTHS)
    return _Config(
        forecast=forecast,
        months=(int(months) if isinstance(months, int) else _DEFAULT_FORECAST_MONTHS),
    )


def forecast_entries(
    result: ScheduleResult,
    entries: list[Directive],
    options_map: Mapping[str, object],
    *,
    months: int = _DEFAULT_FORECAST_MONTHS,
    today: date | None = None,
) -> list[Directive]:
    """Build the forecast transactions for a computed result.

    Each upcoming unresolved occurrence becomes a ``#``-flagged transaction
    dated at its nominal date, carrying the schedule's payee and narration. A
    rule that names no amount cannot be forecast, since the amount is unknown.

    Args:
        result: The computed schedule result.
        entries: The ledger entries, for balance-from-ledger amortization.
        options_map: The Beancount options map, for the currency.
        months: How many months forward to forecast.
        today: The reference date, or ``None`` for the ledger's last date.

    Returns:
        The forecast transactions, in date order.
    """
    reference = today or _last_date(entries)
    horizon = _horizon(reference, months)
    currency = operating_currency(options_map)
    balances = ledger_balances(entries, amortized_accounts(result))
    forecast: list[Directive] = []
    for report in result.reports:
        rule = report.rule
        if rule.match_amount is None:
            continue
        if not rule.postings and rule.amortization is None:
            # A rule with no other side cannot form a balanced transaction.
            continue
        nominals = [
            occurrence.nominal
            for occurrence in report.occurrences
            if not occurrence.resolved and reference <= occurrence.nominal <= horizon
        ]
        if not nominals:
            continue
        splits = amortization_splits(
            rule,
            [o.nominal for o in report.occurrences],
            entries,
            balances=balances,
        )
        forecast.extend(
            transaction
            for nominal in nominals
            if (
                transaction := _forecast_transaction(
                    rule, nominal, splits.get(nominal), currency
                )
            )
            is not None
        )
    forecast.sort(key=lambda entry: entry.date)
    return forecast


def _forecast_transaction(
    rule: Rule,
    nominal: date,
    split: Split | None,
    currency: str,
) -> data.Transaction | None:
    """Build one forecast transaction.

    Args:
        rule: The schedule's rule.
        nominal: The nominal date.
        split: The amortization split, if any.
        currency: The operating currency.

    Returns:
        The forecast transaction, or ``None`` when the rule's postings cannot be
        resolved to a balanced transaction.
    """
    postings = _forecast_postings(rule, split, currency)
    if postings is None:
        return None
    meta = data.new_metadata("<beanschedule>", 0)
    meta[SCHEDULE_KEY] = rule.id
    meta[FORECAST_KEY] = True
    return data.Transaction(
        meta=meta,
        date=nominal,
        flag="#",
        payee=rule.payee or "",
        narration=rule.narration or rule.id,
        tags=frozenset(),
        links=frozenset(),
        postings=postings,
    )


def _forecast_postings(
    rule: Rule, split: Split | None, currency: str
) -> list[data.Posting] | None:
    """Build a forecast transaction's postings.

    Every posting carries an explicit amount: Beancount's balance check reads
    ``get_weight`` on each one, so a posting left for interpolation to fill would
    crash it. When one declared posting omits its amount, it is computed here so
    the transaction balances against ``match-amount``. When more than one omits
    its amount there is nothing to resolve, and the rule is not forecast.

    Args:
        rule: The schedule's rule.
        split: The amortization split, if any.
        currency: The operating currency.

    Returns:
        The postings, or ``None`` when they cannot be resolved.
    """
    amount = rule.match_amount
    if amount is None:
        return None
    postings = [_posting(rule.match_account, amount, currency)]
    if split is not None and rule.amortization is not None:
        amort = rule.amortization
        postings.extend(
            _posting(account, value, currency)
            for account, value in (
                (amort.principal_account, split.principal),
                (amort.interest_account, split.interest),
                (amort.escrow_account, split.escrow),
            )
            if account is not None and value != 0
        )
        return postings
    resolved = resolve_postings(rule.postings, -amount)
    if resolved is None:
        return None
    postings.extend(
        _posting(account, value, currency, metadata)
        for account, value, metadata in resolved
    )
    return postings
    return postings


def _posting(
    account: str,
    amount: Decimal | None,
    currency: str,
    metadata: dict[str, object] | None = None,
) -> data.Posting:
    """Build a posting.

    Args:
        account: The account.
        amount: The amount, or ``None`` to let Beancount balance it.
        currency: The currency.
        metadata: The posting's metadata, if any.

    Returns:
        The posting.
    """
    units = None if amount is None else bc_amount.Amount(amount, currency)
    return data.Posting(
        account=account,
        units=units,
        cost=None,
        price=None,
        flag=None,
        meta=metadata,
    )


def _last_date(entries: list[Directive]) -> date:
    """Return the latest date in the ledger.

    Args:
        entries: The ledger entries.

    Returns:
        The latest date, or today when the ledger is empty.
    """
    dates = [entry.date for entry in entries if getattr(entry, "date", None)]
    return max(dates) if dates else date.today()  # noqa: DTZ011 - fallback only


def _horizon(reference: date, months: int) -> date:
    """Return the last date a forecast reaches.

    Args:
        reference: The reference date.
        months: How many months forward.

    Returns:
        The last day of the month ``months`` ahead.
    """
    index = reference.year * 12 + (reference.month - 1) + months
    return date(index // 12, index % 12 + 1, 1) - timedelta(days=1)


def _with_padding(
    entries: list[Directive],
    options_map: Mapping[str, object],
) -> list[Directive]:
    """Return the entries as Beancount's post-plugins will leave them.

    Beancount appends ``beancount.ops.pad`` after every user plugin, so a plugin
    never sees the padded ledger; applying ``pad`` to a working copy first keeps
    the plugin's view in step with the CLI's.

    Args:
        entries: The ledger entries.
        options_map: The Beancount options map.

    Returns:
        The padded entries, or ``entries`` unchanged when padding does not apply.
    """
    if options_map.get("plugin_processing_mode") != "default":
        return entries
    if not any(isinstance(entry, data.Pad) for entry in entries):
        return entries
    try:
        padded, _errors = pad_ops.pad(entries, options_map)
    except Exception:  # noqa: BLE001 - fall back; Beancount reports the failure
        return entries
    return padded


def _to_error(
    diagnostic: Diagnostic,
    options_map: Mapping[str, object],
) -> ScheduleError:
    """Convert a core diagnostic into a Beancount error.

    Args:
        diagnostic: The core diagnostic.
        options_map: The Beancount options map, for a fallback file name.

    Returns:
        The Beancount-compatible error.
    """
    if diagnostic.entry is not None:
        return ScheduleError(
            diagnostic.entry.meta, diagnostic.message, diagnostic.entry
        )
    filename = str(options_map.get("filename", "<unknown>"))
    lineno = diagnostic.source.lineno if diagnostic.source is not None else 0
    return ScheduleError(data.new_metadata(filename, lineno), diagnostic.message, None)
