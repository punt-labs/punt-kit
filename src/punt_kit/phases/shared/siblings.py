"""Resolve, validate, and recover propagation checkouts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared import timeouts

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps

# Sibling repos checked during preflight and used during propagation (phase 10).
# Must stay in sync with the propagator classes in phase10_propagate.py.
TAP_SIBLING = "homebrew-tap"

PROPAGATION_SIBLINGS: tuple[str, ...] = (
    "claude-plugins",
    ".github",
    "public-website",
    TAP_SIBLING,
)

# Files each sibling's propagation writes. SiblingRegistry.reset_all uses this
# map to reconcile a sibling left dirty by an interrupted phase 10 — the
# propagation writes the file, then calls into PrMerger.merge_in_sibling which
# checks out a branch, and if the checkout times out the sibling stays on main
# with the write still on disk. Restricted to files the release owns so
# unrelated operator work in the same repo survives the reset — the guard in
# SiblingRepo.validate still trips on anything outside this set. Must stay in
# sync with the propagator classes and InstallAllPropagator._sync_profile.
# The tap has no entry: which formula a release owns depends on the project, so
# SiblingRegistry.reset_all is handed it (``tap_paths``) and never touches the
# tap without it.
PROPAGATION_OWNED_PATHS: dict[str, tuple[str, ...]] = {
    ".github": ("install-all.sh", "profile/README.md"),
    "claude-plugins": (".claude-plugin/marketplace.json",),
    "public-website": ("src/data/projects.json",),
}


@final
class SiblingRepo:
    """Inspect and recover a sibling Git checkout."""

    __slots__ = ("_name", "_ops", "_path")

    _path: Path
    _name: str
    _ops: ReleaseOps

    def __new__(cls, path: Path, name: str, *, ops: ReleaseOps) -> Self:
        """Bind a sibling repository's name and checkout path."""
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
        """Return the path to the sibling checkout."""
        return self._path

    @property
    def name(self) -> str:
        """Return the name of the sibling repository."""
        return self._name

    def validate(self) -> None:
        """Require a clean sibling checkout on main and fast-forward it.

        Ignore untracked files and tracked changes confined to .beads.

        Raises:
            ReleaseError: The checkout is not ready or a Git command fails.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        branch_result = self._ops.run(
            ["git", "branch", "--show-current"], cwd=str(self._path), check=False
        )
        if branch_result.returncode != 0:
            # A sibling checkout is far less controlled than the project's
            # own repo — a git command failing here (a
            # corrupted checkout, a detached/unborn HEAD in some git
            # versions) must raise a diagnosed ReleaseError, not a raw
            # CalledProcessError with no indication which sibling or which
            # command failed.
            self._ops.fail(
                f"Sibling {self._name}: git branch --show-current failed:\n"
                f"{branch_result.stderr.strip()}"
            )
        branch = branch_result.stdout.strip()
        if not branch:
            # --show-current prints nothing on a detached HEAD.
            self._ops.fail(
                f"Sibling {self._name} has a detached HEAD, expected branch main"
            )
        if branch != "main":
            self._ops.fail(
                f"Sibling {self._name} is on branch '{branch}', expected main"
            )

        # Only block on modified/staged files — untracked files and .beads/
        # are harmless.
        status_result = self._ops.run(
            ["git", "status", "--porcelain"], cwd=str(self._path), check=False
        )
        if status_result.returncode != 0:
            self._ops.fail(
                f"Sibling {self._name}: git status --porcelain failed:\n"
                f"{status_result.stderr.strip()}"
            )
        # No strip(): a leading " M" space is significant to ln[3:].
        dirty_lines: list[str] = []
        for ln in status_result.stdout.splitlines():
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

    def reset_owned_dirt(
        self, *, fail_on_error: bool, owned: tuple[str, ...] | None = None
    ) -> None:
        """Restore propagation-owned changes without touching unrelated edits.

        Leave the checkout alone if any other tracked path is dirty, except
        for .beads state. An unreadable status produces a notice, not a reset.

        Args:
            owned: Override owned paths; an empty tuple or ``None`` uses the default.
            fail_on_error: Raise on a failed restore instead of reporting it.

        Raises:
            ReleaseError: Git rejected the restore with ``fail_on_error`` set.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        owned = owned or PROPAGATION_OWNED_PATHS.get(self._name)
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
    """Recover the fixed set of propagation sibling repositories."""

    __slots__ = ("_ops",)

    _ops: ReleaseOps

    def __new__(cls, *, ops: ReleaseOps) -> Self:
        """Bind release operations for sibling propagation."""
        self = super().__new__(cls)
        self._ops = ops
        return self

    def reset_all(
        self,
        root: Path,
        *,
        resolve: Callable[[Path, str], Path | None],
        fail_on_error: bool = True,
        tap_paths: tuple[str, ...] = (),
    ) -> None:
        """Recover interrupted propagation checkouts without discarding unrelated edits.

        Switch propagation branches to main and restore owned changes in
        otherwise clean checkouts on main.

        Args:
            resolve: Find a named sibling by project root, or return ``None``.
            fail_on_error: Raise on failed checkout or restore instead of reporting it.
            tap_paths: Formula paths owned by this release, or empty to skip the tap.

        Raises:
            ReleaseError: Git rejected a checkout or restore with ``fail_on_error`` set.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        for sib_name in PROPAGATION_SIBLINGS:
            # The tap is shared with every other project's formulas: a project
            # that does not propagate into it must never reset anything there.
            if sib_name == TAP_SIBLING and not tap_paths:
                continue
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
                fail_on_error=fail_on_error,
                owned=tap_paths if sib_name == TAP_SIBLING else None,
            )
