"""Plugin manifest swap paths and HEAD-committed state, for the release
(prod-name) swap and its dev-restore counterpart."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps


@final
class PluginSwap:
    """The paths phase 4's release swap and phase 9's dev restore both touch."""

    __slots__ = ("_info", "_ops")

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        return self

    def manifest_path_rel(self) -> str:
        """The repo-relative plugin.json path, spelled for a git pathspec.

        Resolved rather than hardcoded: since DES-025 the manifest lives at
        ``plugin/.claude-plugin/plugin.json``, and ``punt release`` runs in
        every plugin repo, which migrate one at a time. A stale literal
        would make ``git show HEAD:<path>`` fail mid-release.
        """
        return self._info.plugin_manifest.relative_to(self._info.root).as_posix()

    def swap_paths(self) -> tuple[str, ...]:
        """The paths the release swap and the dev restore both rewrite."""
        commands = (
            (self._info.plugin_root / "commands")
            .relative_to(self._info.root)
            .as_posix()
        )
        return (self.manifest_path_rel(), f"{commands}/")

    def head_state(self) -> dict[str, object]:
        """Read plugin.json as committed at HEAD, not from the working tree.

        Idempotency checks in phases 4 and 9 answer "is the swap done?" and
        the only source of truth for "done" is the commit that lands on the
        release branch — never the working tree. A prior run that mutated
        plugin.json and then hit a failing pre-commit hook leaves the tree
        already showing the target name with nothing committed; trusting
        disk would report the phase complete and skip past the missing
        commit. ``git show HEAD:<path>`` always describes HEAD alone,
        regardless of the index state.
        """
        result = self._ops.run(
            ["git", "show", f"HEAD:{self.manifest_path_rel()}"],
            cwd=str(self._info.root),
        )
        return cast("dict[str, object]", json.loads(result.stdout))

    def reset_to_head(self) -> None:
        """Revert plugin.json and commands/ to their state at HEAD.

        The plugin swap and dev restore each mutate the working tree AND
        stage the changes before committing. If the commit fails on a
        pre-commit hook, resume needs a clean slate to re-run the script:
        ``release-plugin.sh`` errors out with "Plugin name is already
        '<prod>'" when the tree it starts on already shows the target
        state, and ``restore-dev-plugin.sh`` behaves similarly. Restoring
        the swap paths to HEAD undoes only the failed run's own edits —
        every other path is left alone.

        Paths not present at HEAD are silently ignored (a fresh test repo
        without ``commands/`` at HEAD is still a valid input).
        """
        self._ops.run(
            ["git", "checkout", "HEAD", "--", *self.swap_paths()],
            cwd=str(self._info.root),
            check=False,
            timeout=GIT_HOOK,
        )
