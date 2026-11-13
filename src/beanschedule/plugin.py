"""The Beancount plugin entry point.

Load with::

    plugin "beanschedule.plugin"

The plugin does two things, both in memory — it never writes a ledger and never
injects an entry:

* it **relabels** the transactions that came from the pending file, adding a tag
  and setting a flag, so pending items are obvious in Fava and ``bean-query``;
* it **validates** the schedules file, which ``main.bean`` does not include, by
  loading it itself and reporting the engine's diagnostics as ordinary Beancount
  errors that point back at the schedules file.

Config is a Python-literal mapping, e.g.::

    plugin "beanschedule.plugin" "{'schedules_file': 'schedules.bean', 'pending_file': 'pending.bean', 'pending_tag': 'pending', 'pending_flag': '!'}"

Every key has a default, so a bare ``plugin "beanschedule.plugin"`` works.
Relative paths resolve against the ledger's directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from beancount.core import data
from beancount.ops import pad as pad_ops
from beancount.parser import parser

from beanschedule.config import parse_config
from beanschedule.core import Diagnostic, compute

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from beancount.core.data import Directive

__all__ = ["SchedulesError", "__plugins__", "plugin", "relabel_pending"]

#: The plugin functions for Beancount to run, discovered via ``__plugins__``.
__plugins__ = ["plugin"]

#: The metadata key written on a matched transaction.
SCHEDULE_KEY = "schedule"

_DEFAULT_SCHEDULES_FILE = "schedules.bean"
_DEFAULT_PENDING_FILE = "pending.bean"
_DEFAULT_PENDING_TAG = "pending"
_DEFAULT_PENDING_FLAG = "!"


class SchedulesError(NamedTuple):
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
        schedules_file: The schedules file, relative to the ledger.
        pending_file: The pending file, relative to the ledger.
        pending_tag: The tag added to pending transactions.
        pending_flag: The flag set on pending transactions.
    """

    schedules_file: str = _DEFAULT_SCHEDULES_FILE
    pending_file: str = _DEFAULT_PENDING_FILE
    pending_tag: str = _DEFAULT_PENDING_TAG
    pending_flag: str = _DEFAULT_PENDING_FLAG


def _config(config: object) -> _Config:
    """Resolve the plugin config.

    Args:
        config: The raw config value.

    Returns:
        The resolved :class:`_Config`.
    """
    mapping = parse_config(config) or {}
    return _Config(
        schedules_file=_string(mapping.get("schedules_file"), _DEFAULT_SCHEDULES_FILE),
        pending_file=_string(mapping.get("pending_file"), _DEFAULT_PENDING_FILE),
        pending_tag=_string(mapping.get("pending_tag"), _DEFAULT_PENDING_TAG),
        pending_flag=_string(mapping.get("pending_flag"), _DEFAULT_PENDING_FLAG),
    )


def _string(value: object, default: str) -> str:
    """Return a config value as a non-empty string.

    Args:
        value: The raw value.
        default: The fallback.

    Returns:
        The string, or the default.
    """
    return value if isinstance(value, str) and value else default


def _ledger_dir(options_map: Mapping[str, object]) -> Path:
    """Return the ledger's directory.

    Args:
        options_map: The Beancount options map.

    Returns:
        The directory holding the ledger file.
    """
    from pathlib import Path  # noqa: PLC0415 - a narrow local import

    filename = options_map.get("filename")
    return Path(str(filename)).resolve().parent if filename else Path.cwd()


def relabel_pending(
    entries: list[Directive], pending_file: str, tag: str, flag: str
) -> list[Directive]:
    """Add the pending tag and flag to every pending transaction.

    Args:
        entries: The ledger entries.
        pending_file: The pending file's basename.
        tag: The tag to add.
        flag: The flag to set.

    Returns:
        The entries, with pending transactions relabelled.
    """
    from pathlib import Path  # noqa: PLC0415 - a narrow local import

    returned: list[Directive] = []
    for entry in entries:
        if not isinstance(entry, data.Transaction):
            returned.append(entry)
            continue
        filename = (entry.meta or {}).get("filename")
        if filename is None or Path(str(filename)).name != pending_file:
            returned.append(entry)
            continue
        returned.append(
            entry._replace(
                tags=(entry.tags or frozenset()) | {tag},
                flag=flag,
            )
        )
    return returned


def load_schedules(path: Path) -> list[Directive]:
    """Load the schedule transactions from a file.

    The whole file is schedules, so every transaction is returned — even one
    missing its ``id``, so the engine can report it. The file is parsed without
    Beancount's interpolation and validation: a schedule's amortization legs are
    legitimately amount-less placeholders, and the full loader would reject a
    transaction with more than one of them and drop it entirely. The engine
    reports its own diagnostics instead.

    Args:
        path: The schedules file.

    Returns:
        The schedule transactions, or an empty list when the file is missing.
    """
    if not path.is_file():
        return []
    entries, _errors, _options = parser.parse_file(str(path))
    return [entry for entry in entries if isinstance(entry, data.Transaction)]


def plugin(
    entries: list[Directive],
    options_map: Mapping[str, object],
    config: object = None,
) -> tuple[list[Directive], list[SchedulesError]]:
    """Relabel pending transactions and validate the schedules file.

    Args:
        entries: The ledger entries.
        options_map: The Beancount options map.
        config: The plugin config, a mapping or its string form.

    Returns:
        The entries with pending transactions relabelled, and the errors.
    """
    resolved = _config(config)
    labelled = relabel_pending(
        entries, resolved.pending_file, resolved.pending_tag, resolved.pending_flag
    )
    schedules_path = _ledger_dir(options_map) / resolved.schedules_file
    schedules = load_schedules(schedules_path)
    padded = _with_padding(labelled, options_map)
    result = compute(padded, options_map, schedules=schedules)
    errors = [_to_error(diagnostic, options_map) for diagnostic in result.diagnostics]
    return labelled, errors


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
) -> SchedulesError:
    """Convert a core diagnostic into a Beancount error.

    Args:
        diagnostic: The core diagnostic.
        options_map: The Beancount options map, for a fallback file name.

    Returns:
        The Beancount-compatible error.
    """
    if diagnostic.entry is not None:
        return SchedulesError(
            diagnostic.entry.meta, diagnostic.message, diagnostic.entry
        )
    filename = str(options_map.get("filename", "<unknown>"))
    lineno = diagnostic.source.lineno if diagnostic.source is not None else 0
    return SchedulesError(data.new_metadata(filename, lineno), diagnostic.message, None)
