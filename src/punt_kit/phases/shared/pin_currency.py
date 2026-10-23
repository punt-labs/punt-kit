"""The one test for whether a commit pin names the commit a release produced."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.install_urls import InstallUrlRecognizer

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@dataclass(frozen=True, slots=True)
class PinVerdict:
    """Whether a pin is current, and the detail to show for it."""

    is_current: bool
    detail: str


@final
class PinCurrency:
    """Decides whether a pin names the same commit as ``expected_sha``.

    Writers ask it before leaving a pin alone and Phase 11 asks it when
    verifying, so a pin one calls current the other cannot call stale.

    Ancestry alone (is the pin reachable from the tag?) would pass the exact
    rot this exists to catch: a previous release's install.sh commit is an
    ancestor of every later tag. A textual prefix match would pass a
    fabricated hash that merely starts with the right characters, or an
    unrelated commit sharing a short prefix. Both sides are therefore
    resolved to full commit object IDs with ``git rev-parse <sha>^{commit}``
    and compared for equality: an abbreviated or full pin of the right
    commit is current, and anything else is not. A segment that is not a
    commit SHA (a release tag such as ``v1.2.3``) is never current: the
    writer exists to replace it with the SHA.
    """

    __slots__ = ("_cwd", "_expected", "_ops")

    _expected: str
    _cwd: Path
    _ops: ReleaseOps

    def __new__(cls, expected_sha: str, *, cwd: Path, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._expected = expected_sha
        self._cwd = cwd
        self._ops = ops
        return self

    def is_current(self, pinned: str) -> bool:
        """True when ``pinned`` resolves to the expected commit."""
        return self.verdict(pinned).is_current

    def verdict(self, pinned: str) -> PinVerdict:
        """The verdict for ``pinned``, with the reason when it is not current."""
        if not InstallUrlRecognizer.is_sha_segment(pinned):
            return PinVerdict(
                False,
                f"{pinned} (a release-tag pin, stale — expected {self._expected})",
            )
        expected = self._resolve(self._expected)
        if expected.returncode != 0:
            # The expected SHA comes from a fresh git log on the caller's own
            # repo, so it always resolves: a failure here is a genuine git
            # error, not a stale pin, and must not be misreported as one.
            return PinVerdict(
                False,
                f"SHA={pinned} (git error resolving expected commit "
                f"{self._expected}: {expected.stderr.strip()})",
            )
        resolved = self._resolve(pinned)
        if resolved.returncode != 0:
            return PinVerdict(False, f"SHA={pinned} (does not resolve to a commit)")
        if resolved.stdout.strip() == expected.stdout.strip():
            return PinVerdict(True, f"SHA={pinned}")
        return PinVerdict(False, f"SHA={pinned} (stale — expected {self._expected})")

    def _resolve(self, sha: str) -> subprocess.CompletedProcess[str]:
        return self._ops.run(
            ["git", "rev-parse", f"{sha}^{{commit}}"], cwd=str(self._cwd), check=False
        )
