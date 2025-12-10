"""
Datetime utilities for consistent timezone handling.

Python 3.12+ deprecated datetime.utcnow() in favor of datetime.now(timezone.utc).
This module provides a consistent way to get UTC time across the codebase.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    Return current UTC time.

    Use this instead of datetime.utcnow() which is deprecated in Python 3.12+.

    Returns:
        datetime: Current UTC time with timezone info
    """
    return datetime.now(timezone.utc)
