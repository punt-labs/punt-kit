"""Propagate release pins to sibling repositories through PRs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.entry_matcher import EntryMatcher
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.pin_currency import PinCurrency
from punt_kit.phases.shared.pin_rules import ShaPin
from punt_kit.phases.shared.pipeline import ThreadedStep
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.project_remote import ProjectRemote
from punt_kit.phases.shared.siblings import SiblingRepo
from punt_kit.phases.shared.skips import GITHUB_ABSENT_SKIP
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from concurrent.futures import Future
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

_console = Console()


@final
class InstallAllPropagator:
    """Update the installer and org profile pins in the .github repository."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
        """Bind the propagator to the project, reporting through ``ops``."""
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        self._skips = skips
        return self

    def run(
        self,
        version: str,
        *,
        dry_run: bool,
        merge_sibling: Callable[..., bool],
    ) -> None:
        """Repin install-all.sh, then the org profile README, for ``version``.

        When the ``.github`` sibling is absent (does not resolve as a git
        repo root), propagation is skipped with a loud warning and a clean
        return rather than a failure: this phase runs after the release has
        already published, and the workspace meta-repo layout legitimately
        has no resolvable ``.github`` sibling.

        Args:
            merge_sibling: Commits ``files`` on a branch in the sibling and
                merges them through a PR; returns False when nothing changed.

        Raises:
            ReleaseError: A present ``.github`` sibling lacks install-all.sh or
                is not ready, a git read or file read fails, or a merge fails.
        """
        info = self._info
        ops = self._ops
        if not (info.root / "install.sh").exists():
            return

        slug = ProjectRemote(
            info.root, ops=ops, skips=self._skips, step="install-all.sh propagation"
        ).slug()
        if slug is None:
            return
        project_name = slug.name

        github_sibling = SiblingRepo.resolve(info.root, ".github", ops=ops)
        if github_sibling is None:
            # Absence is allowed after publication. Match the verify skip so
            # the final summary reports the missing checkout only once.
            self._skips.record(
                GITHUB_ABSENT_SKIP.format(name=project_name, ver=version)
            )
            return

        sibling = github_sibling.path
        install_all = sibling / "install-all.sh"
        if not install_all.exists():
            ops.fail("install-all.sh not found in .github — required for propagation")

        tag = f"v{version}"
        install_sha = ReleaseProject(info, ops=ops).install_sh_sha()

        content = TextFile(install_all).read()
        currency = PinCurrency(install_sha, cwd=info.root, ops=ops)
        new_content, count = ShaPin.install_all_entry(project_name).repinned(
            content, install_sha, is_current=currency.is_current
        )

        if count == 0:
            # The profile pin is independent of the installer entry.
            self._skips.record(
                f"SKIPPED — manual action required: ../.github/install-all.sh has no "
                f"entry for {project_name}, so its install SHA was not propagated "
                f"for {tag}. Add the entry, pinned to {install_sha}, manually."
            )
            if not dry_run:
                github_sibling.validate()
                self._sync_profile_readme(sibling, version, project_name, merge_sibling)
            return

        if dry_run:
            if new_content != content:
                ops.dry(
                    f"../.github/install-all.sh: {project_name} SHA → "
                    f"{install_sha} ({tag})"
                )
            ops.dry("../.github/profile/README.md: pin post-merge install-all.sh SHA")
            return

        github_sibling.validate()

        if new_content == content:
            ops.ok(f"install-all.sh: {project_name} SHA already current")
        else:
            TextFile(install_all).write(new_content)
            branch = f"propagate/v{version}-{project_name}-github"
            if merge_sibling(
                sibling,
                branch,
                ["install-all.sh"],
                f"chore: update {project_name} install SHA to {tag}",
                ".github",
                dry_run=False,
            ):
                ops.ok(f"install-all.sh: {project_name} SHA → {install_sha} ({tag})")

        # Pin the merged installer; the pre-merge commit serves stale content.
        self._sync_profile_readme(sibling, version, project_name, merge_sibling)

    def _sync_profile_readme(
        self,
        sibling: Path,
        version: str,
        project_name: str,
        merge_sibling: Callable[..., bool],
    ) -> None:
        """Pin the org profile README to the install-all.sh commit on main.

        Must run after the install-all.sh PR merges: the profile references
        install-all.sh by commit SHA, and only the merged commit contains
        the just-propagated content. Also repairs a stale pin left by an
        earlier interrupted release even when install-all.sh itself needs
        no update.
        """
        ops = self._ops
        readme = sibling / "profile" / "README.md"
        tag = f"v{version}"
        if not readme.exists():
            self._skips.record(
                f"SKIPPED — manual action required: ../.github/profile/README.md "
                f"not found, so the org profile's install-all.sh SHA pin was not "
                f"propagated for {tag}. Restore the profile README and pin it to "
                "the .github commit that last touched install-all.sh, manually."
            )
            return

        log_result = ops.run(
            ["git", "log", "-1", "--format=%h", "--", "install-all.sh"],
            cwd=str(sibling),
            check=False,
        )
        if log_result.returncode != 0:
            # Unlike a genuinely empty result (no commit has ever touched
            # install-all.sh — handled below), a non-zero exit means the
            # command itself failed against this less-controlled sibling
            # checkout (corrupted repo, missing ref) and must not be
            # silently treated as "no commits yet."
            ops.fail(
                f"git log on sibling {sibling} (install-all.sh) failed:\n"
                f"{log_result.stderr.strip()}"
            )
        github_sha = log_result.stdout.strip()
        if not github_sha:
            ops.info(
                "profile/README.md: no commits touch install-all.sh yet — "
                "skipping SHA update"
            )
            return

        readme_content = TextFile(readme).read()
        currency = PinCurrency(github_sha, cwd=sibling, ops=ops)
        new_readme, readme_count = ShaPin.profile().repinned(
            readme_content, github_sha, is_current=currency.is_current
        )
        if readme_count == 0:
            self._skips.record(
                f"SKIPPED — manual action required: ../.github/profile/README.md "
                f"has no install-all.sh SHA reference, so its pin was not "
                f"propagated for {tag}. Add the reference, pinned to "
                f"{github_sha}, manually."
            )
            return
        if new_readme == readme_content:
            ops.ok(
                f"profile/README.md: install-all.sh SHA already current ({github_sha})"
            )
            return

        TextFile(readme).write(new_readme)
        branch = f"propagate/v{version}-{project_name}-github-profile"
        if merge_sibling(
            sibling,
            branch,
            ["profile/README.md"],
            f"chore: pin profile install-all.sh SHA to {github_sha}",
            ".github",
            dry_run=False,
        ):
            ops.ok(f"profile/README.md: install-all.sh SHA → {github_sha}")


@final
class MarketplacePropagator:
    """Update version and ref in claude-plugins marketplace.json (phase 10b)."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
        """Bind the propagator to the project, reporting through ``ops``."""
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        self._skips = skips
        return self

    def run(
        self,
        version: str,
        *,
        dry_run: bool,
        merge_sibling: Callable[..., bool],
    ) -> None:
        """Set the plugin's marketplace version and ref to ``version``.

        Projects that are neither plugin nor hybrid are skipped.

        Args:
            merge_sibling: Commits ``files`` on a branch in the sibling and
                merges them through a PR; returns False when nothing changed.

        Raises:
            ReleaseError: The claude-plugins sibling, marketplace.json or the
                project's entry is missing, the sibling is not ready, the file
                cannot be parsed, or the merge fails.
        """
        info = self._info
        ops = self._ops
        if not info.is_plugin and not info.is_hybrid:
            return

        slug = ProjectRemote(
            info.root, ops=ops, skips=self._skips, step="marketplace propagation"
        ).slug()
        if slug is None:
            return
        project_name = slug.name
        tag = f"v{version}"

        claude_plugins_sibling = SiblingRepo.resolve(
            info.root, "claude-plugins", ops=ops
        )
        if claude_plugins_sibling is None:
            ops.fail(
                "Sibling claude-plugins not found — required for marketplace "
                "propagation"
            )

        sibling = claude_plugins_sibling.path
        marketplace_path = sibling / ".claude-plugin" / "marketplace.json"
        if not marketplace_path.exists():
            ops.fail("marketplace.json not found in claude-plugins")

        if dry_run:
            ops.dry(
                f"../claude-plugins/marketplace.json: "
                f"{project_name} version={version}, ref={tag}"
            )
            return

        claude_plugins_sibling.validate()

        marketplace_file = JsonFile(marketplace_path)
        data = cast("dict[str, object]", marketplace_file.load())
        plugins = cast("list[dict[str, object]]", data.get("plugins", []))

        # Marketplace entries key on the plugin's SHORT name (e.g. "punt"),
        # read from the project's own plugin.json (post -dev-strip), or on the
        # repository name from the origin slug (e.g. "punt-kit") — never the
        # PyPI distribution name. An entry's source.url (keyless HTTPS,
        # git-subdir) must name the same owner/repo.
        marketplace_name = ReleaseProject(info, ops=ops).marketplace_name()
        matcher = EntryMatcher.for_marketplace(slug, marketplace_name)

        found = False
        for plugin in plugins:
            if matcher.claims_plugin(plugin):
                src = cast("dict[str, str]", plugin.get("source", {}))
                plugin["version"] = version
                if "source" not in plugin:
                    plugin["source"] = src
                src["ref"] = tag
                found = True
                break

        if not found:
            ops.fail(
                f"No marketplace entry for {project_name} in marketplace.json "
                "— required for plugin/hybrid releases"
            )

        marketplace_file.save(data)

        branch = f"propagate/v{version}-{project_name}-claude-plugins"
        if merge_sibling(
            sibling,
            branch,
            [".claude-plugin/marketplace.json"],
            f"chore: bump {project_name} to {tag} in marketplace",
            "claude-plugins",
            dry_run=dry_run,
        ):
            ops.ok(f"marketplace: {project_name} version={version}, ref={tag}")
        else:
            ops.ok(f"marketplace: {project_name} already current")


@final
class Phase10Propagate:
    """Run the phase 10 propagators concurrently, one per sibling repo."""

    __slots__ = ("_dry_run", "_info", "_ops", "_skips", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls,
        info: ProjectInfo,
        version: str,
        *,
        dry_run: bool,
        ops: ReleaseOps,
        skips: SkipRecorder,
    ) -> Self:
        """Bind phase 10 to the project and the release ``version``."""
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        self._skips = skips
        return self

    def run(
        self,
        *,
        reset_propagation_siblings: Callable[[ProjectInfo], None],
        propagate_install_all: Callable[..., None],
        propagate_marketplace: Callable[..., None],
        propagate_website: Callable[..., None],
        propagate_homebrew: Callable[..., None],
        interrupted: threading.Event,
    ) -> None:
        """Run the four propagators concurrently.

        Every collaborator here is injected rather than composed directly, so
        a caller that rebinds ``punt_kit.release._propagate_install_all``/
        ``_propagate_marketplace``/``_propagate_website``/``_propagate_homebrew``/
        ``_reset_propagation_siblings`` has each observed by
        ``punt_kit.release._phase10_propagate``.

        Args:
            reset_propagation_siblings: Returns siblings left on propagation
                branches by an interrupted run to main.
            interrupted: Set by release.py's signal handler to stop collection.

        Raises:
            ReleaseError: A sibling reset or any propagator fails.
            KeyboardInterrupt: ``interrupted`` is set once the threads drain.
        """
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print("\n[bold]Phase 10: Propagate[/bold]")

        if not dry_run:
            reset_propagation_siblings(info)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures: dict[Future[None], str] = {
                pool.submit(
                    propagate_install_all, info, version, dry_run=dry_run
                ): ".github",
                pool.submit(
                    propagate_marketplace, info, version, dry_run=dry_run
                ): "claude-plugins",
                pool.submit(
                    propagate_website, info, version, dry_run=dry_run
                ): "public-website",
                pool.submit(
                    propagate_homebrew, info, version, dry_run=dry_run
                ): "homebrew-tap",
            }
            ThreadedStep(ops=ops).collect(futures, interrupted=interrupted)
