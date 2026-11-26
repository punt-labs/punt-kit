"""Merge the release PR and pin the README install SHA."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.plugin_swap import PluginSwap
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase4ReleasePr:
    """Merge the release PR and pin the README install SHA."""

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls, info: ProjectInfo, version: str, *, dry_run: bool, ops: ReleaseOps
    ) -> Self:
        """Create the phase with its release inputs and operations."""
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        return self

    def run(
        self,
        *,
        merge: Callable[..., str],
        land_readme_sha_pin: Callable[..., None],
    ) -> str:
        """Merge the release PR and pin the README install SHA.

        Args:
            merge: Merge the release PR and return its squash-merge SHA.
            land_readme_sha_pin: Land the README pin after the merge.

        Returns:
            The release commit SHA to tag, excluding the later README-pin commit.

        Raises:
            ReleaseError: The plugin swap, PR merge, or README pin fails.
            subprocess.CalledProcessError: A checked repository command fails.
            subprocess.TimeoutExpired: An external command exceeds its timeout.
            OSError: Writing the README pin fails.
        """
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print(f"\n[bold]Phase 4: Release PR v{version}[/bold]")

        root = info.root
        branch = f"release/v{version}"

        # Use committed HEAD for idempotency: a rejected hook can leave a prod-shaped
        # working tree without a swap commit. Reset swap paths before retrying.
        if info.is_hybrid or info.is_plugin:
            release_script = root / "scripts" / "release-plugin.sh"
            if dry_run:
                ops.dry("bash scripts/release-plugin.sh")
            else:
                plugin_swap = PluginSwap(info, ops=ops)
                head_data = plugin_swap.head_state()
                head_name = str(head_data.get("name", ""))
                if head_name.endswith("-dev"):
                    plugin_swap.reset_to_head()
                    swap_result = ops.run(
                        ["bash", str(release_script)],
                        cwd=str(root),
                        capture=False,
                        check=False,
                        # The script commits and runs git hooks.
                        timeout=GIT_HOOK,
                    )
                    if swap_result.returncode != 0:
                        # HEAD is unchanged on failure; resuming resets staged swap
                        # paths and retries.
                        ops.fail(f"{release_script} failed — see output above")
                    ops.ok("Plugin swapped to prod")
                else:
                    ops.ok("Plugin already swapped at HEAD (resume)")

        release_sha = merge(
            cwd=root,
            branch=branch,
            title=f"chore: release v{version}",
            dry_run=dry_run,
        )

        # The README pin needs the merged commit's SHA (see ReadmeShaPin.land).
        # It adds a commit on main, so phase 5 must tag release_sha, not HEAD.
        land_readme_sha_pin(info, version, dry_run=dry_run)

        return release_sha
