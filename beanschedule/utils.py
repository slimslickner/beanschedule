"""Utility functions for beanschedule."""

import re


def slugify(text: str) -> str:
    """Convert text to valid schedule ID.

    Converts text to lowercase, removes special characters,
    replaces spaces with hyphens, and strips leading/trailing hyphens.

    Args:
        text: The text to slugify.

    Returns:
        A valid schedule ID string.
    """
    # Lowercase and replace spaces with hyphens
    slug = text.lower().replace(" ", "-")
    # Remove special characters, keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove leading/trailing hyphens and multiple consecutive hyphens
    slug = slug.strip("-")
    return re.sub(r"-+", "-", slug)
