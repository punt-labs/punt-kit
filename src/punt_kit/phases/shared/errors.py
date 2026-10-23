"""Exception type raised by release phases and their collaborators."""

from __future__ import annotations


class ReleaseError(Exception):
    """Raised by release phases to indicate a failure with a message."""


class ReportedReleaseError(ReleaseError):
    """A :class:`ReleaseError` whose message was already printed to the operator.

    ``Reporter.fail`` prints before it raises. Every other ``ReleaseError``
    (an unreadable file, a failed detection) reaches ``run_release`` unprinted,
    and the top-level handler uses this type to tell the two apart so that
    each failure is shown exactly once.
    """


class RemoteLookupError(ReleaseError):
    """Raised when git cannot say what the ``origin`` remote is.

    Distinct from "there is no github.com origin", which is a legitimate
    answer: this one means the question itself failed (git timed out, could
    not run, or refused), so no answer can be trusted.
    """
