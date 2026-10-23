"""A thread-safe log of propagation and verification steps skipped mid-release."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_kit.phases.shared.ops import ReleaseOps

# Recorded whenever the .github sibling does not resolve — by Phase 10a
# (propagation) and by both Phase 11 checks (install-all.sh, profile SHA). One
# shared template, worded to cover both the propagation-skip and the verify-skip,
# so SkipRecorder deduplicates every phase's notice into a SINGLE recap line for
# the common meta-repo case where .github is absent for the whole run. The repo
# and version make the interpolated message identical across phases within one
# release (one release, one project — so dedup still collapses them).
GITHUB_ABSENT_SKIP = (
    "SKIPPED — manual action required: the .github sibling did not resolve, so "
    "the org install-all.sh SHA and profile README were neither propagated nor "
    "verified for {name} v{ver}. Update ../.github/install-all.sh and "
    "../.github/profile/README.md manually."
)


@final
class SkipRecorder:
    """Thread-safe log of propagation/verification steps skipped mid-release.

    Phase 10 propagates to siblings concurrently, so a warning printed from a
    worker thread can scroll past among interleaved output; and Phase 11 does
    not fail on an absent sibling, so nothing downstream re-raises the
    condition. Each recorded skip is surfaced immediately as a loud warning
    and retained so the pipeline's summary can recap every outstanding manual
    action at the end of the run, whichever phase skipped.
    """

    __slots__ = ("_lock", "_notices", "_ops")

    _lock: threading.Lock
    _notices: list[str]
    _ops: ReleaseOps

    def __new__(cls, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._notices = []
        self._ops = ops
        return self

    def record(self, message: str) -> None:
        """Retain a skip notice and surface it immediately as a warning.

        Deduplicates: a message already recorded is neither stored again nor
        re-warned, so two phases reporting the same absent sibling collapse to
        one recap line and one inline warning.
        """
        with self._lock:
            if message in self._notices:
                return
            self._notices.append(message)
        self._ops.warn(message)

    def drain(self) -> tuple[str, ...]:
        """Return every retained notice and clear the log."""
        with self._lock:
            notices = tuple(self._notices)
            self._notices.clear()
        return notices

    def clear(self) -> None:
        """Discard retained notices without surfacing them."""
        with self._lock:
            self._notices.clear()
