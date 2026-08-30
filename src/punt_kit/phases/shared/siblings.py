"""Sibling-repo resolution, validation, and propagation-branch recovery."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared import timeouts

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps

# Sibling repos checked during preflight and used during propagation (phase 10).
# Must stay in sync with the propagator classes in phase10_propagate.py.
PROPAGATION_SIBLINGS: tuple[str, ...] = ("claude-plugins", ".github", "public-website")

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

# Files each sibling's propagation writes. SiblingRegistry.reset_all uses this
# map to reconcile a sibling left dirty by an interrupted phase 10 — the
# propagation writes the file, then calls into PrMerger.merge_in_sibling which
# checks out a branch, and if the checkout times out the sibling stays on main
# with the write still on disk. Restricted to files the release owns so
# unrelated operator work in the same repo survives the reset — the guard in
# SiblingRepo.validate still trips on anything outside this set. Must stay in
# sync with the propagator classes and InstallAllPropagator._sync_profile.
PROPAGATION_OWNED_PATHS: dict[str, tuple[str, ...]] = {
    ".github": ("install-all.sh", "profile/README.md"),
    "claude-plugins": (".claude-plugin/marketplace.json",),
    "public-website": ("src/data/projects.json",),
}


@final
class SkipRecorder:
    """Thread-safe log of propagation/verification steps skipped mid-release.

    Phase 10 propagates to siblings concurrently, so a warning printed from a
    worker thread can scroll past among interleaved output; and Phase 11 no
    longer hard-fails when a sibling is absent, so nothing downstream re-raises
    the condition. Each recorded skip is surfaced immediately as a loud warning
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


@final
class SiblingRepo:
    """A resolved sibling git repository, ready for validation or reset."""

    __slots__ = ("_name", "_ops", "_path")

    _path: Path
    _name: str
    _ops: ReleaseOps

    def __new__(cls, path: Path, name: str, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._name = name
        self._ops = ops
        return self

    @classmethod
    def resolve(cls, root: Path, name: str, *, ops: ReleaseOps) -> Self | None:
        """Resolve a sibling repo directory.

        Checks ``root``'s parent for a directory named ``name`` with a
        ``.git`` directory. ``None`` if not found — a legitimate absence
        (not every project has every propagation sibling checked out).
        """
        sibling = root.parent / name
        if sibling.is_dir() and (sibling / ".git").exists():
            return cls(sibling, name, ops=ops)
        return None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def name(self) -> str:
        return self._name

    def validate(self) -> None:
        """Validate this sibling repo is ready for propagation."""
        branch = self._ops.run(
            ["git", "branch", "--show-current"], cwd=str(self._path)
        ).stdout.strip()
        if branch != "main":
            self._ops.fail(
                f"Sibling {self._name} is on branch '{branch}', expected main"
            )

        # Only block on modified/staged files — untracked files and .beads/
        # are harmless.
        status = self._ops.run(
            ["git", "status", "--porcelain"], cwd=str(self._path)
        ).stdout.strip()
        dirty_lines: list[str] = []
        for ln in status.splitlines():
            if ln.startswith("?? "):
                continue
            file_path = ln[3:] if len(ln) > 3 else ""
            if file_path == ".beads" or file_path.startswith(".beads/"):
                continue
            dirty_lines.append(ln)
        dirty = "\n".join(dirty_lines)
        if dirty:
            self._ops.fail(f"Sibling {self._name} has uncommitted changes:\n{dirty}")

        result = self._ops.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=str(self._path),
            check=False,
            timeout=timeouts.GIT_HOOK,
        )
        if result.returncode != 0:
            self._ops.fail(
                f"Sibling {self._name}: git pull --ff-only failed:\n"
                f"{result.stderr.strip()}"
            )

    def reset_owned_dirt(self, *, fail_on_error: bool) -> None:
        """Restore propagation-owned files if this sibling is dirty in them.

        The propagation writes a tracked file before calling into
        ``PrMerger.merge_in_sibling``; any interruption between those two
        steps leaves the sibling on main with the write on disk.
        ``validate`` correctly refuses to proceed against a dirty sibling —
        this restores the owned files so the retry can re-run the same
        idempotent write.

        Only touches files in ``PROPAGATION_OWNED_PATHS[name]``. If any other
        file in the sibling is modified, this does nothing and lets
        ``validate`` fail — the whole point of the ownership map is that a
        human's unrelated work in the sibling survives the reset. On sibling
        names with no ownership entry, also do nothing rather than guess.
        """
        owned = PROPAGATION_OWNED_PATHS.get(self._name)
        if not owned:
            return

        status = self._ops.run(
            ["git", "status", "--porcelain"], cwd=str(self._path), check=False
        )
        if status.returncode != 0:
            self._ops.info(
                f"Could not read status for sibling {self._name} "
                f"({status.stderr.strip()}) — skipping owned-file reset"
            )
            return

        dirty_owned: list[str] = []
        for ln in status.stdout.splitlines():
            # Same filter validate() applies: untracked and .beads noise do
            # not block propagation and are not ours to reset.
            if ln.startswith("?? "):
                continue
            file_path = ln[3:] if len(ln) > 3 else ""
            if file_path == ".beads" or file_path.startswith(".beads/"):
                continue
            if file_path in owned:
                dirty_owned.append(file_path)
                continue
            # A modification outside the ownership map. Leave the whole
            # sibling alone — validate() will surface it, and the operator
            # decides how to handle their own work.
            return

        if not dirty_owned:
            return

        self._ops.info(
            f"Restoring propagation-owned files in sibling {self._name} "
            f"(was dirty on main): {', '.join(dirty_owned)}"
        )
        restore = self._ops.run(
            ["git", "checkout", "HEAD", "--", *dirty_owned],
            cwd=str(self._path),
            check=False,
            timeout=timeouts.GIT_HOOK,
        )
        if restore.returncode != 0:
            msg = (
                f"Could not restore propagation-owned files in sibling "
                f"{self._name}: {restore.stderr.strip()}\n"
                "Fix manually before retrying propagation."
            )
            if fail_on_error:
                self._ops.fail(msg)
            else:
                self._ops.info(f"Warning: {msg}")


@final
class SiblingRegistry:
    """Recovery over the fixed set of propagation siblings."""

    __slots__ = ("_ops",)

    _ops: ReleaseOps

    def __new__(cls, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        return self

    def reset_all(
        self,
        root: Path,
        *,
        resolve: Callable[[Path, str], Path | None],
        fail_on_error: bool = True,
    ) -> None:
        """Return all propagation sibling repos to the main branch.

        No-op for siblings already on main and clean. Used by the interrupt
        handler and at the start of Phase 10 to recover from prior interrupted
        runs. Handles two residues a mid-phase-10 interruption can leave:

        * a sibling on a ``propagate/v*`` branch — check it out back to main
        * a sibling on main with a propagation-owned file dirty — the more
          likely residue, since the propagation writes the file *before*
          calling ``PrMerger.merge_in_sibling`` and any interruption between
          the two leaves exactly that. Restored to HEAD so the idempotent
          retry re-runs the same write.

        ``fail_on_error=False`` should be used from the signal handler so
        that a checkout failure on one sibling does not abort cleanup of the
        remaining siblings. The Phase 10 call site uses the default
        ``fail_on_error=True`` so that release failures are loud.

        ``resolve`` is injected rather than calling ``SiblingRepo.resolve``
        directly so callers that expose sibling resolution as a
        monkeypatchable seam (``punt_kit.release._resolve_sibling``) can pass
        that seam through unchanged.
        """
        for sib_name in PROPAGATION_SIBLINGS:
            sib_path = resolve(root, sib_name)
            if sib_path is None:
                continue
            branch_result = self._ops.run(
                ["git", "branch", "--show-current"],
                cwd=str(sib_path),
                check=False,
            )
            if branch_result.returncode != 0:
                self._ops.info(
                    f"Could not read branch for sibling {sib_name} "
                    f"({branch_result.stderr.strip()}) — skipping reset"
                )
                continue
            branch = branch_result.stdout.strip()
            if branch and branch != "main":
                if not branch.startswith("propagate/v"):
                    self._ops.info(
                        f"Sibling {sib_name} is on '{branch}' (not a "
                        "propagation branch) — skipping reset to avoid "
                        "disrupting active work"
                    )
                    continue
                self._ops.info(
                    f"Returning sibling {sib_name} to main (was on '{branch}')..."
                )
                checkout = self._ops.run(
                    ["git", "checkout", "main"],
                    cwd=str(sib_path),
                    check=False,
                    timeout=timeouts.GIT_HOOK,
                )
                if checkout.returncode != 0:
                    msg = (
                        f"Could not return sibling {sib_name} to main: "
                        f"{checkout.stderr.strip()}\n"
                        "Fix manually before retrying propagation."
                    )
                    if fail_on_error:
                        self._ops.fail(msg)
                    else:
                        self._ops.info(f"Warning: {msg}")
                    continue
            # Sibling is on main (either was already, or just returned to
            # it). Reconcile a dirty propagation-owned file left by an
            # interrupted write; leave unrelated modifications alone.
            SiblingRepo(sib_path, sib_name, ops=self._ops).reset_owned_dirt(
                fail_on_error=fail_on_error
            )
