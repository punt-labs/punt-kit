"""Phase 9: dev plugin restore via its own PR, right after the release PR
squash-merges."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.plugin_swap import PluginSwap
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase9PostRelease:
    """Phase 9: dev plugin restore via PR."""

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

    def run(self, *, merge: Callable[..., str]) -> None:
        """``merge`` is injected rather than composing ``PrMerger`` directly —
        several tests monkeypatch ``punt_kit.release._pr_merge`` and call
        ``punt_kit.release._phase9_post_release`` expecting the patch to be
        observed (§0's mechanism).
        """
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print(f"\n[bold]Phase 9: Post-release v{version}[/bold]")

        root = info.root
        branch = f"post-release/v{version}"
        has_changes = False

        if dry_run:
            if info.is_hybrid or info.is_plugin:
                ops.dry("bash scripts/restore-dev-plugin.sh")
            ops.dry('git commit -m "chore: restore dev plugin state"')
            ops.dry(f'merge(branch={branch}, title="chore: post-release v{version}")')
            return

        # Create post-release branch — ensure we're on main first
        workspace = GitWorkspace(root, ops=ops)
        workspace.ensure_on_main()

        if workspace.checkout_or_create(branch):
            ops.info(f"Checked out existing branch {branch}")
        else:
            ops.ok(f"Created branch {branch}")

        # Dev restore (hybrid/plugin — idempotent: skip only when the
        # restore commit is already at HEAD). Mirror of the phase 4 check.
        #
        # The restore script stages the reverted files but does not commit
        # (see scripts/restore-dev-plugin.sh CONTRACT). That lets this phase
        # re-stamp the version — the historical dev commit's plugin.json has
        # the old version — and land the restore + re-stamp as one commit
        # with hooks running. The previous shape committed inside the script
        # and then --amend --no-verify'd here to fix up the version; the
        # org bans --no-verify outright and the amend existed only because
        # the script committed too early.
        #
        # Consulting the working tree here has the same failure mode phase
        # 4 does: if the commit fails on a pre-commit hook, the restore is
        # already staged and the tree already shows the dev name — a disk
        # read would report "already in dev state (resume)" and fall
        # through to the README-SHA commit, which would then sweep the
        # staged plugin.json into itself under the wrong commit message.
        # Consult HEAD, and require BOTH the dev name AND the released
        # version at HEAD before treating the restore as done — a partial
        # historical commit with a mismatched version must still re-run.
        if info.is_hybrid or info.is_plugin:
            plugin_swap = PluginSwap(info, ops=ops)
            head_data = plugin_swap.head_state()
            head_name = str(head_data.get("name", ""))
            head_version = str(head_data.get("version", ""))
            restore_done = head_name.endswith("-dev") and head_version == version
            if not restore_done:
                plugin_swap.reset_to_head()
                restore_script = root / "scripts" / "restore-dev-plugin.sh"
                ops.run(
                    ["bash", str(restore_script)],
                    cwd=str(root),
                    capture=False,
                    # git checkout inside the script fires the post-checkout
                    # hook; same reasoning as the phase 4 swap above.
                    timeout=GIT_HOOK,
                )
                # The restore checks plugin.json out of the last dev commit,
                # which reverts the version field along with the name. Put
                # the just-released version back before committing so main
                # advertises the current release, not the previous one.
                plugin_json = info.plugin_manifest
                pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
                if pj_data.get("version") != version:
                    pj_data["version"] = version
                    plugin_json.write_text(
                        json.dumps(pj_data, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    ops.run(["git", "add", str(plugin_json)], cwd=str(root))
                # No [skip ci] marker on this commit: the PR's required
                # status checks (lint/test/docs) run per branch protection,
                # and GitHub Actions honors [skip ci] on pull_request
                # triggers too — so the marker used to make the PR
                # unmergeable. The squash-merge onto main uses the PR
                # title (which never carried the marker), so removing it
                # here also does not add a redundant CI run on main.
                # See pkit-x5j8.
                ops.run(
                    [
                        "git",
                        "commit",
                        "-m",
                        "chore: restore dev plugin state",
                    ],
                    cwd=str(root),
                    timeout=GIT_HOOK,
                )
                ops.ok("Dev plugin state restored")
                has_changes = True
            else:
                ops.ok("Dev restore already at HEAD (resume)")

        if not has_changes:
            # Check if branch has commits ahead of main (resume case)
            ahead = ops.run(
                ["git", "log", "main..HEAD", "--oneline"],
                cwd=str(root),
            ).stdout.strip()
            if ahead:
                has_changes = True
            else:
                ops.run(["git", "checkout", "main"], cwd=str(root), timeout=GIT_HOOK)
                ops.run(["git", "branch", "-D", branch], cwd=str(root))
                ops.ok("No post-release changes needed")
                return

        merge(
            cwd=root,
            branch=branch,
            title=f"chore: post-release v{version}",
            dry_run=False,
        )
        ops.ok("Post-release PR merged")
