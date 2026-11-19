"""Restore dev plugin state and pin deployed workflows via PR."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.plugin_swap import PluginSwap
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase9PostRelease:
    """Restore dev plugin state and pin deployed workflows via PR."""

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

    def run(self, *, merge: Callable[..., str]) -> None:
        """Restore dev plugin state and pin deployed workflows via PR.

        Args:
            merge: Merge the post-release branch using the supplied PR metadata.

        Raises:
            ReleaseError: Restoring, pinning workflows, git operations, or merging
                fails.
            subprocess.CalledProcessError: A checked repository command fails.
            subprocess.TimeoutExpired: An external command exceeds its timeout.
            OSError: Writing a version pin or manifest fails.
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
            ReleaseProject(info, ops=ops).rewrite_deployed_workflow_pins(
                version, dry_run=True
            )
            ops.dry(f'merge(branch={branch}, title="chore: post-release v{version}")')
            return

        workspace = GitWorkspace(root, ops=ops)
        workspace.ensure_on_main()

        if workspace.checkout_or_create(branch):
            ops.info(f"Checked out existing branch {branch}")
        else:
            ops.ok(f"Created branch {branch}")

        # Use committed HEAD for idempotency; a rejected hook can leave staged dev
        # files.
        # The restore script stages without committing, so restore and version stamp
        # land together with hooks. Require both the dev name and released version
        # at HEAD before skipping, to keep partial restores out of workflow-pin commits.
        if info.is_hybrid or info.is_plugin:
            plugin_swap = PluginSwap(info, ops=ops)
            head_data = plugin_swap.head_state()
            head_name = str(head_data.get("name", ""))
            head_version = str(head_data.get("version", ""))
            restore_done = head_name.endswith("-dev") and head_version == version
            if not restore_done:
                plugin_swap.reset_to_head()
                restore_script = root / "scripts" / "restore-dev-plugin.sh"
                restore_result = ops.run(
                    ["bash", str(restore_script)],
                    cwd=str(root),
                    capture=False,
                    check=False,
                    # The restore script's checkout runs post-checkout hooks.
                    timeout=GIT_HOOK,
                )
                if restore_result.returncode != 0:
                    # HEAD is unchanged; resuming resets staged restore paths and
                    # retries.
                    ops.fail(f"{restore_script} failed — see output above")
                # The dev manifest supplies the name, but must retain the released
                # version.
                plugin_json = info.plugin_manifest
                manifest = JsonFile(plugin_json)
                pj_data = cast("dict[str, object]", manifest.load())
                if pj_data.get("version") != version:
                    pj_data["version"] = version
                    manifest.save(pj_data)
                    ops.run(["git", "add", str(plugin_json)], cwd=str(root))
                # Do not use [skip ci]: required pull_request checks would never
                # complete.
                commit_result = ops.run(
                    [
                        "git",
                        "commit",
                        "-m",
                        "chore: restore dev plugin state",
                    ],
                    cwd=str(root),
                    check=False,
                    timeout=GIT_HOOK,
                )
                if commit_result.returncode != 0:
                    # A rejected hook leaves the restore staged, so the HEAD check must
                    # retry it.
                    ops.fail(
                        "git commit (restore dev plugin state) failed — "
                        f"{commit_result.stderr.strip()}"
                    )
                ops.ok("Dev plugin state restored")
                has_changes = True
            else:
                ops.ok("Dev restore already at HEAD (resume)")

        # Pin deployed workflows only after phase 8 verifies publication, so they
        # cannot reference an unpublished version. Matching pins are a no-op on resume.
        project = ReleaseProject(info, ops=ops)
        pinned = project.rewrite_deployed_workflow_pins(version, dry_run=False)
        if pinned:
            own_pkg = project.self_package_name()
            rels = [p.relative_to(root).as_posix() for p in pinned]
            if workspace.commit_if_staged(
                rels, f"chore: pin deployed workflows to {own_pkg} v{version}"
            ):
                has_changes = True

        if not has_changes:
            ahead = ops.run(
                ["git", "log", "main..HEAD", "--oneline"],
                cwd=str(root),
            ).stdout.strip()
            if ahead:
                has_changes = True
            else:
                # Checkout runs hooks and needs the hook timeout budget.
                checkout = ops.run(
                    ["git", "checkout", "main"],
                    cwd=str(root),
                    check=False,
                    timeout=GIT_HOOK,
                )
                if checkout.returncode != 0:
                    ops.fail(f"git checkout main failed:\n{checkout.stderr.strip()}")
                delete = ops.run(
                    ["git", "branch", "-D", branch], cwd=str(root), check=False
                )
                if delete.returncode != 0:
                    ops.fail(f"git branch -D {branch} failed:\n{delete.stderr.strip()}")
                ops.ok("No post-release changes needed")
                return

        merge(
            cwd=root,
            branch=branch,
            title=f"chore: post-release v{version}",
            dry_run=False,
        )
        ops.ok("Post-release PR merged")
