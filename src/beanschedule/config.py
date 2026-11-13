"""Parsing for the config strings a directive can carry.

Beancount passes a ``plugin "module" "<config>"`` argument, and Fava passes a
``custom "fava-extension" "module" "<config>"`` argument, both as a plain
**string**. This module turns such a string — a Python-literal mapping, the only
form Beancount's lexer allows for a dict-shaped config — into a mapping, so a
plugin or Fava extension can read named settings rather than a single keyword.
"""

from __future__ import annotations

import ast
from typing import Any, cast

__all__ = ["parse_config"]


def parse_config(value: object) -> dict[str, Any] | None:
    """Parse a directive-carried config into a mapping.

    Accepts a mapping already (a caller may pass one directly), or a string
    holding a Python-literal mapping such as ``"{'forecast': True}"``. Anything
    else, or a malformed string, yields ``None``.

    Args:
        value: The raw config value.

    Returns:
        The config mapping, or ``None`` when there is none.

    Examples:
        >>> parse_config("{'forecast': True, 'months': 2}")
        {'forecast': True, 'months': 2}
        >>> parse_config("forecast") is None
        True
        >>> parse_config(None) is None
        True
    """
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    return parsed if isinstance(parsed, dict) else None
