"""Rewrite a ledger's v1 tracking metadata for the v2 reconciliation model.

The v1 beangulp hook tagged matched transactions with ``schedule_id`` and a trail
of tracking metadata, and wrote placeholder transactions for missing occurrences.
The v2 model needs a plain ``schedule: "<id>"`` tag, no tracking metadata, and no
placeholders. This module finds those and edits the ledger files in place, by
line, so everything else — comments, formatting and line endings — is preserved.

It performs no writes of its own; :func:`scan` returns :class:`FilePlan` records
and the CLI applies them through :func:`apply`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from beancount import loader as bc_loader
from beancount.core import data

from beanschedule import writer

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ["FilePlan", "apply", "scan", "summarise"]

#: The v1 tracking metadata keys, which have no v2 equivalent.
TRACKING_KEYS = frozenset(
    {
        "schedule_matched_date",
        "schedule_confidence",
        "schedule_expected_date",
        "schedule_skipped",
        "amortization_principal",
        "amortization_interest",
        "amortization_balance_after",
        "amortization_linked_date",
        "amortization_payment_number",
    }
)

#: The metadata key a matched transaction carries in v2.
SCHEDULE_KEY = "schedule"

#: The v1 metadata key that links a transaction to a schedule.
LEGACY_KEY = "schedule_id"

#: The v1 metadata key that marks a placeholder transaction.
PLACEHOLDER_KEY = "schedule_placeholder"


@dataclass(slots=True)
class FilePlan:
    """The line edits for one ledger file.

    Attributes:
        path: The file to edit.
        edits: ``(lineno, count, replacement)`` triples; ``replacement`` is the
            new lines for the span (each keeping its line ending), empty to
            delete the directive.
        placeholders: How many placeholder transactions are deleted.
        stripped: How many tracking metadata lines are removed.
        renamed: How many ``schedule_id`` tags are renamed to ``schedule``.
    """

    path: Path
    edits: list[tuple[int, int, list[str]]] = field(default_factory=list)
    placeholders: int = 0
    stripped: int = 0
    renamed: int = 0

    @property
    def empty(self) -> bool:
        """Whether the file has no edits."""
        return not self.edits


def scan(ledger: Path) -> list[FilePlan]:
    """Find the v1-tracking changes a ledger needs.

    Args:
        ledger: The ledger file to load. Its ``include`` d files are edited too.

    Returns:
        One :class:`FilePlan` per file with changes, in first-seen order.
    """
    entries, _errors, _options = bc_loader.load_file(str(ledger))
    base = ledger.parent
    lines_by_file: dict[Path, list[str]] = {}
    plans: dict[Path, FilePlan] = {}
    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue
        meta = entry.meta or {}
        filename = meta.get("filename")
        lineno = meta.get("lineno")
        if filename is None or lineno is None:
            continue
        path = writer.resolve_target(_resolve(filename, base), base)
        if path not in lines_by_file:
            lines_by_file[path] = _read(path)
            plans[path] = FilePlan(path)
        lines = lines_by_file[path]
        plan = plans[path]
        start = int(lineno) - 1
        count = writer.directive_line_count(lines, int(lineno))
        span = lines[start : start + count]
        if meta.get(PLACEHOLDER_KEY):
            plan.edits.append((int(lineno), count, []))
            plan.placeholders += 1
            continue
        replacement, stripped, renamed = _strip_span(span)
        if stripped or renamed:
            plan.edits.append((int(lineno), count, replacement))
            plan.stripped += stripped
            plan.renamed += renamed
    return [plan for plan in plans.values() if not plan.empty]


def summarise(plans: Iterable[FilePlan]) -> str:
    """Render a one-line-per-file summary of a scan.

    Args:
        plans: The file plans.

    Returns:
        The summary text.
    """
    plans = list(plans)
    if not plans:
        return "nothing to migrate"
    lines = [
        (
            f"{plan.path}: {plan.placeholders} placeholder(s), "
            f"{plan.stripped} tracking metadata line(s), "
            f"{plan.renamed} schedule_id(s) renamed"
        )
        for plan in plans
    ]
    return "\n".join(lines)


def apply(plans: Iterable[FilePlan]) -> None:
    """Apply a scan's edits, in place, bottom-up.

    Args:
        plans: The file plans.
    """
    for plan in plans:
        lines = _read(plan.path)
        for lineno, count, replacement in sorted(
            plan.edits, key=lambda edit: edit[0], reverse=True
        ):
            lines[lineno - 1 : lineno - 1 + count] = list(replacement)
        _write(plan.path, lines)


def _resolve(filename: object, base: Path) -> Path:
    """Resolve an entry's source file against the ledger directory.

    Args:
        filename: The ``filename`` metadata value.
        base: The ledger directory.

    Returns:
        The path, relative to ``base`` when it is not absolute.
    """
    from pathlib import Path  # noqa: PLC0415 - a narrow local import

    path = Path(str(filename))
    return path if path.is_absolute() else base / path


def _strip_span(span: list[str]) -> tuple[list[str], int, int]:
    """Rewrite one directive's lines: drop tracking keys, rename the tag.

    Args:
        span: The directive's lines, each keeping its line ending.

    Returns:
        The ``(replacement, stripped, renamed)`` triple.
    """
    keys = {key for line in span if (key := _meta_key(line)) is not None}
    has_both = LEGACY_KEY in keys and SCHEDULE_KEY in keys
    replacement: list[str] = []
    stripped = 0
    renamed = 0
    for line in span:
        key = _meta_key(line)
        if key is None:
            replacement.append(line)
        elif key in TRACKING_KEYS:
            stripped += 1
        elif key == LEGACY_KEY:
            if has_both:
                stripped += 1
            else:
                replacement.append(_rename_key(line, SCHEDULE_KEY))
                renamed += 1
        else:
            replacement.append(line)
    return replacement, stripped, renamed


def _meta_key(line: str) -> str | None:
    """Return the metadata key of an indented ``key: value`` line.

    Args:
        line: The line.

    Returns:
        The key, or ``None`` when the line is not metadata.
    """
    if not line[:1].isspace():
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith(";"):
        return None
    key, sep, _ = stripped.partition(":")
    return key.strip() if sep else None


def _rename_key(line: str, new_key: str) -> str:
    """Rename a metadata line's key, preserving indentation and value.

    Args:
        line: The line.
        new_key: The new key.

    Returns:
        The rewritten line.
    """
    indent = line[: len(line) - len(line.lstrip())]
    _key, sep, rest = line.lstrip().partition(":")
    return f"{indent}{new_key}{sep}{rest}"


def _read(path: Path) -> list[str]:
    """Read a file's lines, keeping their endings.

    Args:
        path: The file.

    Returns:
        The lines.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read().splitlines(keepends=True)


def _write(path: Path, lines: list[str]) -> None:
    """Write a file's lines, preserving its inode.

    Args:
        path: The file.
        lines: The lines, each keeping its line ending.
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("".join(lines))
