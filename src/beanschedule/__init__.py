"""Beanschedule - Scheduled transaction framework for Beancount.

This package provides a beangulp hook for matching imported transactions
to scheduled/recurring transactions and enriching them with metadata, tags,
and full posting information.

Main export:
    schedule_hook: Beangulp hook function to add to HOOKS list
"""

from .hook import schedule_hook

__all__ = ["schedule_hook"]
__version__ = "1.0.0"
