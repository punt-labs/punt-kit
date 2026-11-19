"""Find plugin swap paths and read or restore their committed state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps


@final
class PluginSwap:
    """Inspect and restore files shared by the release swap and dev restore."""

    __slots__ = ("_info", "_ops")

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        """Bind operations for the project's dev and prod plugin files."""
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        return self

    def manifest_path_rel(self) -> str:
        """Return the repository-relative plugin manifest path for Git.

        Use the detected manifest location so Git reads the same file as the
        release swap, regardless of the repository's plugin layout.
        """
        return self._info.plugin_manifest.relative_to(self._info.root).as_posix()

    def swap_paths(self) -> tuple[str, ...]:
        """List the paths written by both the release swap and the dev restore."""
        commands = (
            (self._info.plugin_root / "commands")
            .relative_to(self._info.root)
            .as_posix()
        )
        return (self.manifest_path_rel(), f"{commands}/")

    def head_state(self) -> dict[str, object]:
        """Read plugin.json as committed at HEAD, not from the working tree.

        A working-tree change can survive a rejected commit, so only HEAD
        establishes that a swap is complete.

        Raises:
            ReleaseError: The committed manifest is not a JSON object.
            subprocess.CalledProcessError: Git could not read the manifest.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        result = self._ops.run(
            ["git", "show", f"HEAD:{self.manifest_path_rel()}"],
            cwd=str(self._info.root),
        )
        return JsonFile.parse_object(
            result.stdout, source=f"HEAD:{self.manifest_path_rel()}"
        )

    def reset_to_head(self) -> None:
        """Restore the plugin swap paths in the index and working tree.

        Clear incomplete swap edits before retrying, leaving other paths
        alone. A nonzero checkout exit is not raised.

        Raises:
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        self._ops.run(
            ["git", "checkout", "HEAD", "--", *self.swap_paths()],
            cwd=str(self._info.root),
            check=False,
            timeout=GIT_HOOK,
        )
