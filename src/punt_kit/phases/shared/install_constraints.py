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
        """The file's content at the tag, or ``None`` when the tag has none."""
        shown = self._ops.run(
            ["git", "show", f"{self._tag}:{CONSTRAINTS_FILENAME}"],
            cwd=str(self._root),
            check=False,
        )
        return shown.stdout if shown.returncode == 0 else None
