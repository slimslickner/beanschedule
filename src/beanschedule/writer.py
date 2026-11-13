"""The opt-in writer for schedule transactions.

Pure code never touches disk. This is the only module through which the CLI
edits a ledger file; the Fava report edits included files through Fava's own
file API and its non-included schedules file through this module, but both
render through :mod:`beanschedule.actions` and both edit by literal line
changes, never by regenerating a file, so line endings and the file's inode
are preserved. Writing outside the ledger directory is refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from beanschedule import actions

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from beancount.core.data import Directive

__all__ = [
    "SOURCE_SUFFIXES",
    "append",
    "apply_edits",
    "delete",
    "directive_line_count",
    "replace",
    "resolve_target",
    "rewrite",
]

#: The file suffixes the writer will edit.
SOURCE_SUFFIXES = (".bean", ".beancount")


def resolve_target(target: Path, ledger_dir: Path) -> Path:
    """Resolve a write target and refuse anything outside the ledger directory.

    Args:
        target: The requested file, relative to ``ledger_dir`` or absolute.
        ledger_dir: The directory of the ledger being edited.

    Returns:
        The resolved path.

    Raises:
        ValueError: If the target escapes the ledger directory or is not a
            Beancount source file.
    """
    base = ledger_dir.resolve()
    resolved = (
        (base / target).resolve() if not target.is_absolute() else target.resolve()
    )
    if not resolved.is_relative_to(base):
        message = f"{target} is outside the ledger directory {base}"
        raise ValueError(message)
    if resolved.suffix not in SOURCE_SUFFIXES:
        message = f"{target} is not a Beancount source file (.bean or .beancount)"
        raise ValueError(message)
    return resolved


def directive_line_count(lines: list[str], lineno: int) -> int:
    """Count the lines a directive occupies, including its metadata.

    Args:
        lines: The file's lines.
        lineno: The directive's one-based line number.

    Returns:
        The number of lines from ``lineno`` to the first non-indented, non-blank
        line after it.
    """
    count = 1
    index = lineno
    while index < len(lines):
        line = lines[index]
        if not line.strip() or not line[0].isspace():
            break
        count += 1
        index += 1
    return count


def append(path: Path, entry: Directive) -> None:
    """Append a directive to a file.

    Args:
        path: The file to edit.
        entry: The directive to append.
    """
    lines = _read_lines(path)
    ending = _ending(lines)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += ending
    if lines and lines[-1].strip():
        lines.append(ending)
    lines.extend(f"{line}{ending}" for line in actions.render(entry).split("\n"))
    _write_lines(path, lines)


def replace(path: Path, lineno: int, entry: Directive) -> None:
    """Replace the directive at a line with another.

    Args:
        path: The file to edit.
        lineno: The one-based line number of the directive to replace.
        entry: The directive to write in its place.
    """
    lines = _read_lines(path)
    count = directive_line_count(lines, lineno)
    ending = _ending(lines)
    written = [f"{line}{ending}" for line in actions.render(entry).split("\n")]
    lines[lineno - 1 : lineno - 1 + count] = written
    _write_lines(path, lines)


def delete(path: Path, lineno: int) -> None:
    """Delete the directive at a line.

    Args:
        path: The file to edit.
        lineno: The one-based line number of the directive to delete.
    """
    lines = _read_lines(path)
    count = directive_line_count(lines, lineno)
    del lines[lineno - 1 : lineno - 1 + count]
    _write_lines(path, lines)


def apply_edits(
    lines: list[str],
    edits: Sequence[tuple[int, Directive | None]],
) -> list[str]:
    """Replace or delete directives in a file's lines, without touching disk.

    The edits are applied from the bottom up, so each ``lineno`` still names its
    original directive after the lines below it have changed. A directive spans
    its own line plus any indented metadata lines.

    Args:
        lines: The file's lines, with line endings.
        edits: ``(lineno, entry)`` pairs. ``entry`` is the directive to write in
            place of the one at ``lineno``; ``None`` deletes it.

    Returns:
        The new lines.
    """
    updated = list(lines)
    ending = _ending(lines)
    for lineno, entry in sorted(edits, key=lambda edit: edit[0], reverse=True):
        count = directive_line_count(updated, lineno)
        start = lineno - 1
        if entry is None:
            del updated[start : start + count]
        else:
            written = [f"{line}{ending}" for line in actions.render(entry).split("\n")]
            updated[start : start + count] = written
    return updated


def rewrite(path: Path, edits: Sequence[tuple[int, Directive | None]]) -> None:
    """Replace or delete directives in a file, in place.

    Args:
        path: The file to edit.
        edits: ``(lineno, entry)`` pairs, as :func:`apply_edits`.
    """
    _write_lines(path, apply_edits(_read_lines(path), edits))


def _read_lines(path: Path) -> list[str]:
    """Read a file's lines without translating line endings.

    Args:
        path: The file to read.

    Returns:
        The lines, each keeping its own line ending.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read().splitlines(keepends=True)


def _write_lines(path: Path, lines: list[str]) -> None:
    """Write a file's lines, preserving its inode.

    Args:
        path: The file to write.
        lines: The lines, each keeping its own line ending.
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("".join(lines))


def _ending(lines: list[str]) -> str:
    r"""Return the line ending a file uses.

    Args:
        lines: The file's lines.

    Returns:
        ``"\r\n"`` when the first line uses CRLF, else ``"\n"``.
    """
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"
