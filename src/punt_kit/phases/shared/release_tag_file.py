"""Read install-pin files from a release tag for PyPI installs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps

CONSTRAINTS_FILENAME = "install-constraints.txt"
OVERRIDES_FILENAME = "install-overrides.txt"


@final
class ReleaseTagFile:
    """Read an optional file as committed at a release tag.

    ``uv tool install pkg==X`` ignores the project's lock and its installer's
    overrides, so a project that wants its users to get the same dependency
    set ships ``install-constraints.txt`` (for ``--constraints``) and
    ``install-overrides.txt`` (for ``--overrides``). Reading them from the
    tag, not the working tree, verifies what the release published, whatever
    ``main`` has moved on to.
    """

    __slots__ = ("_filename", "_ops", "_root", "_tag")

    _root: Path
    _tag: str
    _filename: str
    _ops: ReleaseOps

    def __new__(cls, root: Path, tag: str, filename: str, *, ops: ReleaseOps) -> Self:
        """Identify a repository path at a release tag."""
        self = super().__new__(cls)
        self._root = root
        self._tag = tag
        self._filename = filename
        self._ops = ops
        return self

    def text(self) -> str | None:
        """Read the file at the tag, or return ``None`` when it is absent.

        A failed Git read must not silently trigger unpinned installation.

        Raises:
            ReleaseError: Git could not resolve the tag or read its tree or file.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        ops = self._ops
        cwd = str(self._root)
        self._require_tag()
        listing = ops.run(
            ["git", "ls-tree", "--name-only", self._tag, "--", self._filename],
            cwd=cwd,
            check=False,
        )
        if listing.returncode != 0:
            ops.fail(f"git ls-tree {self._tag} failed:\n{listing.stderr.strip()}")
        if not listing.stdout.strip():
            return None
        shown = ops.run(
            ["git", "show", f"{self._tag}:{self._filename}"],
            cwd=cwd,
            check=False,
        )
        if shown.returncode != 0:
            ops.fail(
                f"git show {self._tag}:{self._filename} failed:\n{shown.stderr.strip()}"
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
                f"read {self._filename} from the release"
            )

    def _resolves(self) -> bool:
        found = self._ops.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{self._tag}^{{commit}}"],
            cwd=str(self._root),
            check=False,
        )
        return found.returncode == 0
