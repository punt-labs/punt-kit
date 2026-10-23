"""Exception type raised by release phases and their collaborators."""

from __future__ import annotations

import subprocess
import traceback
from typing import final

from punt_kit.phases.shared.repo_slug import RepoSlug


@final
class OperationalFailure:
    """Tells a failure the environment caused from a bug, and reports each.

    Operational means a timeout, a failed command, or any ``OSError``: a
    missing tool and a permission problem are properties of the machine, not
    of the code, so every ``OSError`` counts and the one-line entry keeps the
    exception type to say which. Everything else is a bug and keeps its
    traceback. The worker-thread collector and the main-thread handler both
    classify here so the same error reads the same wherever it surfaces.
    """

    __slots__ = ()

    TYPES = (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError)

    @classmethod
    def covers(cls, exc: BaseException) -> bool:
        """True when ``exc`` is an environmental failure, not a bug."""
        return isinstance(exc, cls.TYPES)

    DETAIL_LIMIT = 300

    @classmethod
    def one_line(cls, exc: BaseException) -> str:
        """Return ``Type: message``; ``str(KeyError("x"))`` alone is ``'x'``.

        A failed or timed-out command also says why: see :meth:`detail`.
        """
        # The argv of a failed command is in str(exc); redact the whole line.
        line = RepoSlug.redacted(f"{type(exc).__name__}: {exc}")
        if detail := cls.detail(exc):
            line = f"{line}: {detail}"
        return line

    @classmethod
    def detail(cls, exc: BaseException) -> str:
        """What a command said before it ended, or ``""`` when it said nothing.

        Its stderr, or its output when stderr is empty: one line, URL
        credentials removed, cut to its tail. Only a failed or timed-out
        command has any.
        """
        if not isinstance(
            exc, subprocess.CalledProcessError | subprocess.TimeoutExpired
        ):
            return ""
        raw = cls._text(exc.stderr) or cls._text(exc.output)
        detail = RepoSlug.redacted(raw)
        if len(detail) > cls.DETAIL_LIMIT:
            # The tail: git's useful line is usually the last.
            detail = f"...{detail[-cls.DETAIL_LIMIT :]}"
        return detail

    @staticmethod
    def _text(raw: str | bytes | None) -> str:
        """``raw`` as one line of text: a timeout hands back bytes, not str."""
        text = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        return " ".join((text or "").split())

    @classmethod
    def report(cls, exc: BaseException) -> str:
        """Print a traceback if ``exc`` is a bug; return its one-line entry."""
        if not cls.covers(exc):
            traceback.print_exception(exc)
        return cls.one_line(exc)


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
