"""Convert legacy ``schedules/*.yaml`` files to ``custom "schedule"`` directives.

This is the one module that reads YAML. It is pure apart from reading the files
it is pointed at: it returns :class:`Migration` records, and the CLI renders
them. Idempotence is by schedule id — a file whose id a ledger already declares
is skipped.

The v1 format was richer than the directive model in places, so what has no
equivalent is reported as a warning rather than silently dropped: a
``transaction``'s tags, links and custom metadata, its ``missing_transaction``
placeholder settings, a multi-currency posting, and an amortization block's
original ``principal`` (the static method derives it from ``match-amount``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import yaml

from beanschedule import actions
from beanschedule.core import DEFAULT_WINDOW

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from pathlib import Path

    from beancount.core.data import Custom

__all__ = ["Migration", "directory", "file", "render"]

#: The config file in a schedules directory, which is not a schedule.
_CONFIG_FILE = "_config.yaml"

#: The legacy recurrence frequency names.
_LEGACY_FREQUENCY = {
    "WEEKLY": "FREQ=WEEKLY",
    "MONTHLY": "FREQ=MONTHLY",
    "YEARLY": "FREQ=YEARLY",
    "BIMONTHLY": "FREQ=MONTHLY;INTERVAL=2",
    "INTERVAL": "FREQ=MONTHLY",
    "MONTHLY_ON_DAYS": "FREQ=MONTHLY",
    "NTH_WEEKDAY": "FREQ=MONTHLY",
    "LAST_DAY_OF_MONTH": "FREQ=MONTHLY;BYMONTHDAY=-1",
}

#: The legacy weekday names and the RFC 5545 day tokens they map to.
_WEEKDAYS = {
    "MON": "MO",
    "TUE": "TU",
    "WED": "WE",
    "THU": "TH",
    "FRI": "FR",
    "SAT": "SA",
    "SUN": "SU",
}


@dataclass(frozen=True, slots=True)
class Migration:
    """One converted YAML schedule.

    Attributes:
        schedule_id: The schedule's identifier.
        source: The file it came from.
        directives: The ``new`` directive and its postings, in order.
        warnings: What could not be expressed in the directive model.
        disabled: Whether the source had ``enabled: false``.
    """

    schedule_id: str
    source: Path
    directives: tuple[Custom, ...]
    warnings: tuple[str, ...] = ()
    disabled: bool = False


def directory(path: Path, existing: Collection[str] = ()) -> list[Migration]:
    """Convert every schedule file in a directory.

    Args:
        path: The directory holding the YAML files.
        existing: Schedule ids already declared, skipped for idempotence.

    Returns:
        The migrations, in file order.
    """
    known = set(existing)
    migrations: list[Migration] = []
    for yaml_path in sorted(path.glob("*.yaml")):
        if yaml_path.name.startswith("_"):
            continue
        migration = file(yaml_path, known)
        if migration is not None:
            migrations.append(migration)
            known.add(migration.schedule_id)
    return migrations


def file(yaml_path: Path, existing: Collection[str] = ()) -> Migration | None:
    """Convert one YAML schedule file.

    Args:
        yaml_path: The YAML file.
        existing: Schedule ids already declared, skipped for idempotence.

    Returns:
        The :class:`Migration`, or ``None`` when the file holds no schedule or
        its id is already declared.
    """
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "id" not in data:
        return None
    schedule_id = str(data["id"])
    if schedule_id in set(existing):
        return None

    warnings: list[str] = []
    match = _mapping(data.get("match"))
    recurrence = _mapping(data.get("recurrence"))
    transaction = _mapping(data.get("transaction"))
    amortization = data.get("amortization")

    rrule_text = _as_str(recurrence.get("rrule")) or _legacy_rrule(recurrence)
    start_value = recurrence.get("start_date") or recurrence.get("start")
    if rrule_text is None or start_value is None:
        return None
    start = date.fromisoformat(str(start_value))
    end = (
        date.fromisoformat(str(recurrence["end_date"]))
        if recurrence.get("end_date")
        else None
    )

    amount, mode, tolerance = _amount_hints(match)
    window = _as_int(match.get("date_window_days"))
    window_arg = window if window is not None and window != DEFAULT_WINDOW else None
    amort = _amortization_fields(amortization, match, transaction, warnings)
    directives = [
        actions.new(
            schedule_id,
            start,
            rrule=rrule_text,
            start=start,
            end=end,
            match_account=str(match.get("account", "")),
            match_payee=_as_str(match.get("payee_pattern")),
            match_amount=amount,
            amount_mode=_explicit_mode(amount, mode),
            amount_tolerance=tolerance,
            amount_min=_as_dec(match.get("amount_min")),
            amount_max=_as_dec(match.get("amount_max")),
            window_before=window_arg,
            window_after=window_arg,
            payee=_as_str(transaction.get("payee")),
            narration=_as_str(transaction.get("narration")),
            method=amort.method,
            rate=amort.rate,
            term=amort.term,
            escrow=amort.escrow,
            principal_account=amort.principal_account,
            interest_account=amort.interest_account,
            escrow_account=amort.escrow_account,
        )
    ]

    if _is_amortized(amortization):
        # The account keys carry the split; the legacy postings have no place.
        warnings.append(
            "amortized postings are dropped; the principal/interest/escrow "
            "account keys carry the split"
        )
    else:
        directives.extend(_postings(schedule_id, match, transaction, start, warnings))

    _warn_dropped(transaction, warnings)
    return Migration(
        schedule_id=schedule_id,
        source=yaml_path,
        directives=tuple(directives),
        warnings=tuple(warnings),
        disabled=data.get("enabled") is False,
    )


def render(migration: Migration) -> str:
    """Render a migration as Beancount text with its warning comments.

    Args:
        migration: The migration.

    Returns:
        The directives, each rendered, with a leading comment per warning and,
        when the source was disabled, every directive line commented out.
    """
    lines: list[str] = []
    if migration.disabled:
        lines.append("; disabled in the source; uncomment to enable")
    lines.extend(f"; note: {warning}" for warning in migration.warnings)
    for directive in migration.directives:
        rendered = actions.render(directive)
        if migration.disabled:
            lines.extend(f"; {line}" for line in rendered.splitlines())
        else:
            lines.append(rendered)
    return "\n".join(lines)


# --- Field mapping -------------------------------------------------------------


def _mapping(value: object) -> Mapping[str, Any]:
    """Return a mapping, or an empty one when the value is not a mapping.

    Args:
        value: The value.

    Returns:
        The mapping.
    """
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else {}


def _as_str(value: object) -> str | None:
    """Return a non-empty string, or ``None``.

    Args:
        value: The value.

    Returns:
        The string, or ``None``.
    """
    return value if isinstance(value, str) and value else None


def _as_int(value: object) -> int | None:
    """Return an integer, or ``None``.

    Args:
        value: The value.

    Returns:
        The integer, or ``None``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _as_dec(value: object) -> Decimal | None:
    """Return a decimal, or ``None``.

    Args:
        value: The value.

    Returns:
        The decimal, or ``None``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        return Decimal(str(value))
    return None


def _amount_hints(
    match: Mapping[str, Any],
) -> tuple[Decimal | None, str | None, Decimal | None]:
    """Resolve the legacy match block's amount mode.

    Args:
        match: The legacy ``match`` mapping.

    Returns:
        The ``(amount, mode, tolerance)`` triple, with ``mode`` ``None`` when it
        can be inferred from the amount.
    """
    amount = _as_dec(match.get("amount"))
    tolerance = _as_dec(match.get("amount_tolerance"))
    minimum = _as_dec(match.get("amount_min"))
    maximum = _as_dec(match.get("amount_max"))
    if minimum is not None or maximum is not None:
        return amount, "range", tolerance
    if tolerance is not None:
        return amount, "approx", tolerance
    if amount is not None:
        return amount, "exact", None
    return None, "any", None


def _explicit_mode(amount: Decimal | None, mode: str | None) -> str | None:
    """Return an amount mode only when it is not the inferred default.

    Args:
        amount: The reference amount, if any.
        mode: The resolved mode.

    Returns:
        The mode, or ``None`` when it can be inferred without being written.
    """
    inferred = "any" if amount is None else "exact"
    return None if mode == inferred else mode


def _is_amortized(amortization: object) -> bool:
    """Report whether a schedule amortizes.

    Args:
        amortization: The legacy ``amortization`` mapping, if any.

    Returns:
        ``True`` when an amortization block is present.
    """
    return isinstance(amortization, dict) and bool(amortization)


@dataclass(frozen=True, slots=True)
class AmortizationFields:
    """The amortization metadata a migrated rule carries.

    Attributes:
        method: ``"static"`` or ``"balance-from-ledger"``, or ``None``.
        rate: The annual rate, if any.
        term: The term in months, for the static method.
        escrow: The summed escrow amount, if any.
        principal_account: The principal account, if any.
        interest_account: The interest account, if any.
        escrow_account: The escrow account, if any.
    """

    method: str | None = None
    rate: Decimal | None = None
    term: int | None = None
    escrow: Decimal | None = None
    principal_account: str | None = None
    interest_account: str | None = None
    escrow_account: str | None = None


def _amortization_fields(
    amortization: object,
    match: Mapping[str, Any],
    transaction: Mapping[str, Any],
    warnings: list[str],
) -> AmortizationFields:
    """Map a legacy amortization block to rule metadata.

    Args:
        amortization: The legacy ``amortization`` mapping, if any.
        match: The legacy ``match`` mapping.
        transaction: The legacy ``transaction`` mapping.
        warnings: Extended in place.

    Returns:
        The :class:`AmortizationFields`.
    """
    if not isinstance(amortization, dict) or not amortization:
        return AmortizationFields()
    block = cast("Mapping[str, Any]", amortization)
    roles = _role_accounts(transaction)
    method = "balance-from-ledger" if block.get("balance_from_ledger") else "static"
    term = (
        None if method == "balance-from-ledger" else _as_int(block.get("term_months"))
    )
    if block.get("principal") is not None:
        warnings.append(
            "amortization principal is dropped; the static method derives it "
            "from match-amount"
        )
    if _as_dec(match.get("amount")) is None:
        warnings.append(
            "no match-amount: set it so the amortized payment can be computed"
        )
    return AmortizationFields(
        method=method,
        rate=_as_dec(block.get("annual_rate")),
        term=term,
        escrow=_escrow_total(transaction),
        principal_account=roles.get("principal"),
        interest_account=roles.get("interest"),
        escrow_account=roles.get("escrow"),
    )


def _role_accounts(transaction: Mapping[str, Any]) -> dict[str, str]:
    """Collect the first account for each amortization role.

    Args:
        transaction: The legacy ``transaction`` mapping.

    Returns:
        A mapping from role to account.
    """
    roles: dict[str, str] = {}
    for posting in transaction.get("postings") or []:
        if not isinstance(posting, dict):
            continue
        role = posting.get("role")
        account = posting.get("account")
        if isinstance(role, str) and isinstance(account, str) and role not in roles:
            roles[role] = account
    return roles


def _escrow_total(transaction: Mapping[str, Any]) -> Decimal | None:
    """Sum the legacy escrow-role posting amounts.

    Args:
        transaction: The legacy ``transaction`` mapping.

    Returns:
        The total escrow, or ``None`` when there is none.
    """
    total = Decimal(0)
    found = False
    for posting in transaction.get("postings") or []:
        if not isinstance(posting, dict) or posting.get("role") != "escrow":
            continue
        amount = _as_dec(posting.get("amount"))
        if amount is not None:
            total += amount
            found = True
    return total if found else None


def _postings(
    schedule_id: str,
    match: Mapping[str, Any],
    transaction: Mapping[str, Any],
    day: date,
    warnings: list[str],
) -> list[Custom]:
    """Map legacy postings to ``posting`` directives.

    The matched account's posting is skipped (the imported transaction carries
    it), and a multi-currency posting is skipped and reported, since the
    directive model carries one currency. The survivors are checked against
    ``match-amount``: a v1 template was a full double-entry split, not
    necessarily a split of the matched amount, so an unbalanced one is reported
    rather than passed on silently.

    Args:
        schedule_id: The schedule id.
        match: The legacy ``match`` mapping.
        transaction: The legacy ``transaction`` mapping.
        day: The directive date.
        warnings: Extended in place.

    Returns:
        The ``posting`` directives.
    """
    match_account = match.get("account")
    resolved: list[tuple[str, Decimal | None, dict[str, object]]] = []
    for posting in transaction.get("postings") or []:
        if not isinstance(posting, dict) or not posting.get("account"):
            continue
        account = str(posting["account"])
        if account == match_account:
            continue
        if posting.get("currency"):
            warnings.append(
                f"posting {account} uses currency {posting['currency']}, which "
                "schedules cannot carry; skipped"
            )
            continue
        if posting.get("role"):
            warnings.append(f"posting {account}'s role {posting['role']!r} is dropped")
        resolved.append(
            (
                account,
                _as_dec(posting.get("amount")),
                {
                    key: value
                    for key, value in posting.items()
                    if key not in ("account", "amount", "currency", "role")
                    and value is not None
                },
            )
        )
    _warn_balance(match, resolved, warnings)
    return [
        actions.posting(
            schedule_id, account, day, amount=amount, metadata=metadata or None
        )
        for account, amount, metadata in resolved
    ]


def _warn_balance(
    match: Mapping[str, Any],
    resolved: Sequence[tuple[str, Decimal | None, dict[str, object]]],
    warnings: list[str],
) -> None:
    """Report postings that cannot balance against ``match-amount``.

    A single amount-less posting is resolvable (the engine fills it), so it is
    fine. More than one is ambiguous. When every posting has an amount, their
    total must equal the negative of ``match-amount``.

    Args:
        match: The legacy ``match`` mapping.
        resolved: The ``(account, amount, metadata)`` postings.
        warnings: Extended in place.
    """
    missing = sum(1 for _account, amount, _meta in resolved if amount is None)
    if missing > 1:
        warnings.append(f"{missing} postings omit their amount; at most one may (E014)")
        return
    match_amount = _as_dec(match.get("amount"))
    if match_amount is None or missing == 1:
        return
    total = sum(
        (amount for _account, amount, _meta in resolved if amount is not None),
        Decimal(0),
    )
    expected = -match_amount
    if total != expected:
        warnings.append(
            f"postings total {total:.2f}, not {expected:.2f}; "
            "they will not balance (E011)"
        )


def _warn_dropped(transaction: Mapping[str, Any], warnings: list[str]) -> None:
    """Report the legacy transaction fields with no equivalent.

    Args:
        transaction: The legacy ``transaction`` mapping.
        warnings: Extended in place.
    """
    if transaction.get("tags"):
        warnings.append("transaction tags are dropped")
    if transaction.get("links"):
        warnings.append("transaction links are dropped")
    metadata = _mapping(transaction.get("metadata"))
    dropped = [key for key in metadata if key != "schedule_id"]
    if dropped:
        warnings.append(
            "transaction metadata " + ", ".join(sorted(dropped)) + " is dropped"
        )


def _legacy_rrule(  # noqa: C901, PLR0911 - one branch per legacy frequency
    recurrence: Mapping[str, Any],
) -> str | None:
    """Convert a legacy frequency block to an RRULE string.

    Args:
        recurrence: The legacy ``recurrence`` mapping.

    Returns:
        The RRULE text, or ``None`` when no frequency is present.
    """
    frequency = str(recurrence.get("frequency", "")).upper()
    if frequency not in _LEGACY_FREQUENCY:
        return None
    day_of_month = _as_int(recurrence.get("day_of_month"))
    month = _as_int(recurrence.get("month"))
    interval = _as_int(recurrence.get("interval")) or 1
    interval_months = _as_int(recurrence.get("interval_months"))
    day_of_week = _weekday(recurrence.get("day_of_week"))
    if frequency == "WEEKLY":
        parts = ["FREQ=WEEKLY"]
        if interval > 1:
            parts.append(f"INTERVAL={interval}")
        if day_of_week:
            parts.append(f"BYDAY={day_of_week}")
        return ";".join(parts)
    if frequency == "YEARLY":
        parts = ["FREQ=YEARLY"]
        if month is not None:
            parts.append(f"BYMONTH={month}")
        if day_of_month is not None:
            parts.append(f"BYMONTHDAY={day_of_month}")
        return ";".join(parts)
    if frequency == "INTERVAL":
        months = interval_months or interval or 1
        return f"FREQ=MONTHLY;INTERVAL={months};BYMONTHDAY={day_of_month or 1}"
    if frequency in ("MONTHLY", "BIMONTHLY", "MONTHLY_ON_DAYS"):
        days = recurrence.get("days_of_month")
        if isinstance(days, list) and days:
            return "FREQ=MONTHLY;BYMONTHDAY=" + ",".join(str(day) for day in days)
        step = 2 if frequency == "BIMONTHLY" else 1
        suffix = f";INTERVAL={step}" if step > 1 else ""
        return f"FREQ=MONTHLY{suffix};BYMONTHDAY={day_of_month or 1}"
    if frequency == "NTH_WEEKDAY":
        nth = _as_int(recurrence.get("nth_occurrence")) or 1
        prefix = f"+{nth}" if nth > 0 else str(nth)
        return f"FREQ=MONTHLY;BYDAY={prefix}{day_of_week or 'MO'}"
    return _LEGACY_FREQUENCY[frequency]


def _weekday(value: object) -> str | None:
    """Map a legacy weekday token to its RFC 5545 form.

    Args:
        value: The weekday token.

    Returns:
        The two-letter day, or ``None``.
    """
    token = str(value).upper() if value else ""
    return _WEEKDAYS.get(token, token or None)
