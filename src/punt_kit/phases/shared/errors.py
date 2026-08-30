"""Exception type raised by release phases and their collaborators."""

from __future__ import annotations


class ReleaseError(Exception):
    """Raised by release phases to indicate a failure with a message."""
