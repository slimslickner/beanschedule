"""Ledger-native scheduled transactions for Beancount.

Public entry points live in :mod:`beanschedule.core` (pure computation),
:mod:`beanschedule.schema` (the metadata and diagnostic registry),
:mod:`beanschedule.reconcile` (post-import reconciliation),
:mod:`beanschedule.plugin` (the Beancount plugin), :mod:`beanschedule.cli` (the
command line interface) and :mod:`beanschedule.fava_ext` (the Fava report).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("beanschedule")
except PackageNotFoundError:  # pragma: no cover - only from an uninstalled tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
