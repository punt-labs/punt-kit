"""Exception type raised by release phases and their collaborators."""

from __future__ import annotations

import re
import subprocess
import traceback
from typing import final

from punt_kit.phases.shared.repo_slug import RepoSlug

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


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

        A failed command also says why it failed: its stderr, or its output
        when stderr is empty: one line, URL credentials removed, cut to its tail.
        """
        line = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, subprocess.CalledProcessError):
            raw = " ".join(str(exc.stderr or exc.output or "").split())
            detail = _URL.sub(lambda m: RepoSlug.without_userinfo(m.group()), raw)
            if len(detail) > cls.DETAIL_LIMIT:
                # The tail: git's useful line is usually the last.
                detail = f"...{detail[-cls.DETAIL_LIMIT :]}"
            if detail:
                line = f"{line}: {detail}"
        return line

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
