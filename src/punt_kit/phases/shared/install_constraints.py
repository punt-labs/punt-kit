"""The pin file a project ships so a PyPI install resolves like its lockfile."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps

CONSTRAINTS_FILENAME = "install-constraints.txt"


@final
class InstallConstraints:
    """``install-constraints.txt`` as committed at a release tag.

    ``uv tool install pkg==X`` ignores the project's lock, so a project that
    wants its users to get the locked dependency set ships this file and passes
    it to ``--constraints``. Reading it from the tag, not the working tree,
    verifies what the release published, whatever ``main`` has moved on to.
    """

    __slots__ = ("_ops", "_root", "_tag")

    _root: Path
    _tag: str
    _ops: ReleaseOps

    def __new__(cls, root: Path, tag: str, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._tag = tag
        self._ops = ops
        return self

    def text(self) -> str | None:
        """The file's content at the tag, or ``None`` when the tag has none.

        "Absent" and "could not be read" are different answers: only an
        ``ls-tree`` that succeeds and lists nothing means absent. An
        unresolvable tag, a failing git command, or a failing ``git show``
        fails the phase, because installing unpinned on a read error would
        verify an environment no user gets.
        """
        ops = self._ops
        cwd = str(self._root)
        self._require_tag()
        listing = ops.run(
            ["git", "ls-tree", "--name-only", self._tag, "--", CONSTRAINTS_FILENAME],
            cwd=cwd,
            check=False,
        )
        if listing.returncode != 0:
            ops.fail(f"git ls-tree {self._tag} failed:\n{listing.stderr.strip()}")
        if not listing.stdout.strip():
            return None
        shown = ops.run(
            ["git", "show", f"{self._tag}:{CONSTRAINTS_FILENAME}"],
            cwd=cwd,
            check=False,
        )
        if shown.returncode != 0:
            ops.fail(
                f"git show {self._tag}:{CONSTRAINTS_FILENAME} failed:\n"
                f"{shown.stderr.strip()}"
            )
        return shown.stdout

    def _require_tag(self) -> None:
        """Resolve the tag locally, fetching it from origin once if it is missing."""
        if self._resolves():
            return
        self._ops.run(
            ["git", "fetch", "origin", "tag", self._tag],
            cwd=str(self._root),
            check=False,
        )
        if not self._resolves():
            self._ops.fail(
                f"tag {self._tag} does not resolve locally or on origin — cannot "
                f"read {CONSTRAINTS_FILENAME} from the release"
            )

    def _resolves(self) -> bool:
        found = self._ops.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{self._tag}^{{commit}}"],
            cwd=str(self._root),
            check=False,
        )
        return found.returncode == 0
