"""Exception type raised by release phases and their collaborators."""

from __future__ import annotations


class ReleaseError(Exception):
    """Raised by release phases to indicate a failure with a message."""


class RemoteLookupError(ReleaseError):
    """Raised when git cannot say what the ``origin`` remote is.

    Distinct from "there is no github.com origin", which is a legitimate
    answer: this one means the question itself failed (git timed out, could
    not run, or refused), so no answer can be trusted.
    """
