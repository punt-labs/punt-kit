"""Phase 4: plugin swap, push branch, create PR, merge, then pin README's
install-URL SHA."""

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
    """Phase 4: plugin swap, push branch, create PR, merge."""

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls, info: ProjectInfo, version: str, *, dry_run: bool, ops: ReleaseOps
    ) -> Self:
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
    ) -> None:
        """``merge``/``land_readme_sha_pin`` are injected rather than
        composing ``PrMerger``/``ReadmeShaPin`` directly —
        ``test_phase4_release_pr...`` monkeypatches
        ``punt_kit.release._pr_merge``/``_land_readme_sha_pin`` and calls
        ``punt_kit.release._phase4_release_pr`` expecting both patches
        observed (§0's mechanism).
        """
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print(f"\n[bold]Phase 4: Release PR v{version}[/bold]")

        root = info.root
        branch = f"release/v{version}"

        # 4a. Plugin swap (hybrid/plugin — idempotent: skip if already
        # committed at HEAD). The old shape read plugin.json from the
        # working tree, which is only correct while --no-verify guarantees
        # the commit cannot fail. With hooks live, a failed commit leaves
        # plugin.json prod-shaped on disk without a corresponding commit; a
        # working-tree read then reports the swap done and merge() pushes a
        # release branch whose HEAD still carries the -dev name — the
        # release tag lands on it, silently. Consult HEAD, and reset the
        # swap paths so the script's fresh-run precondition (dev name on
        # disk) holds even on retry.
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
                    ops.run(
                        ["bash", str(release_script)],
                        cwd=str(root),
                        capture=False,
                        # The script commits, and that commit now runs the
                        # repo hooks — the bd pre-commit hook alone allows
                        # itself 300s against a networked Dolt server.
                        # Budgeting the script at the 60s metadata default
                        # would abort a release for hook latency that is
                        # not a fault.
                        timeout=GIT_HOOK,
                    )
                    ops.ok("Plugin swapped to prod")
                else:
                    ops.ok("Plugin already swapped at HEAD (resume)")

        # 4b. Push branch, create PR, wait for CI, squash-merge
        merge(
            cwd=root,
            branch=branch,
            title=f"chore: release v{version}",
            dry_run=dry_run,
        )

        # 4c. Pin README's install-URL SHA now that the squash-merge has
        # landed on main — see ReadmeShaPin.land for why this must happen
        # here and not during phase 2's version bump on the (about to be
        # deleted) branch.
        land_readme_sha_pin(info, version, dry_run=dry_run)
