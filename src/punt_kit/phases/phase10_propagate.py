"""Phase 10: local cross-repo propagation via PRs — install-all.sh SHA,
marketplace.json, and public-website projects.json."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.entry_matcher import EntryMatcher
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.install_urls import InstallUrlRecognizer
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
    """10a. Updates project's install.sh SHA in .github/install-all.sh, then
    the org profile README's pin to the commit that lands it."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
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
        """Also updates the org profile README with the install-all.sh
        commit SHA so that both changes land in a single .github PR.

        When the ``.github`` sibling is absent (does not resolve as a git
        repo root), propagation is skipped with a loud warning and a clean
        return rather than a failure: this phase runs after the release has
        already published, and the workspace meta-repo layout legitimately
        has no resolvable ``.github`` sibling. A ``.github`` sibling that
        *is* present but is missing ``install-all.sh`` remains a hard
        failure — that is a genuine misconfiguration, not the expected
        meta-repo case.
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
            # Phase 10a runs *after* the tag, PyPI publish, and GitHub
            # release (phases 5-7) have irreversibly landed, so aborting
            # here would report failure on an already-published release.
            # The absent-sibling case is also legitimate: in the workspace
            # meta-repo layout the ``.github`` path is occupied by the
            # meta-repo's own (non-git-root) folder and can never resolve
            # as a propagation sibling — Phase 1d already tolerates this by
            # skipping siblings that resolve to None. Mirror that here:
            # skip loudly and tell the operator exactly what to do by hand.
            # Recorded through the shared template so the end-of-run
            # summary recaps it even if this line scrolls past among the
            # concurrent Phase 10 output — and so it deduplicates against
            # the identical Phase 11 verify-skip into one line.
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
        new_content, count = ShaPin.install_all_entry(project_name).repinned(
            content, install_sha
        )

        if count == 0:
            # Phase 11 fails an absent entry, so say so now, with the fix. The
            # profile pin is independent of this entry and is still refreshed.
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

        # The sibling is back on main with the merge pulled, so the profile
        # can now pin the commit that actually contains the propagated
        # content. Pinning before the merge would point one commit behind
        # and serve the previous installer on every release.
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
        if not readme.exists():
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
        new_readme, readme_count = ShaPin.profile().repinned(readme_content, github_sha)
        if readme_count == 0:
            ops.info(
                "profile/README.md: no install-all.sh SHA reference found — "
                "skipping update"
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
    """10b. Updates version and ref in claude-plugins marketplace.json."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
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
        # not the PyPI distribution name (e.g. "punt-kit") — read it from the
        # project's own plugin.json (post -dev-strip). An entry's source.url
        # (keyless HTTPS, git-subdir) must name the same owner/repo.
        marketplace_name = ReleaseProject(info, ops=ops).marketplace_name()
        names = frozenset(n for n in (marketplace_name, project_name) if n)
        matcher = EntryMatcher(slug.owner, project_name, names)

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
class WebsitePropagator:
    """10d. Updates version in public-website projects.json."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
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
        info = self._info
        ops = self._ops
        # The website is optional: look for its sibling before asking for the
        # slug, so a missing sibling is not reported as a skipped step needing
        # manual action.
        website_sibling = SiblingRepo.resolve(info.root, "public-website", ops=ops)
        if website_sibling is None:
            ops.info("Sibling public-website not found — skipping website update")
            return

        sibling = website_sibling.path
        projects_json = sibling / "src" / "data" / "projects.json"
        if not projects_json.exists():
            ops.info("projects.json not found in public-website — skipping")
            return

        slug = ProjectRemote(
            info.root, ops=ops, skips=self._skips, step="website propagation"
        ).slug()
        if slug is None:
            return
        project_name = slug.name

        if dry_run:
            ops.dry(
                f"../public-website/projects.json: {project_name} version={version}"
            )
            return

        website_sibling.validate()

        projects_file = JsonFile(projects_json)
        data = cast("list[dict[str, object]]", projects_file.load())
        matcher = EntryMatcher(slug.owner, project_name, frozenset({project_name}))

        found = False
        for project in data:
            if matcher.claims_website(project):
                project["version"] = version
                # The same recognizer Phase 11 verifies the installCommand with.
                install_cmd = str(project.get("installCommand") or "")
                if install_cmd:
                    install_sha = ReleaseProject(info, ops=ops).install_sh_sha()
                    currency = PinCurrency(install_sha, cwd=info.root, ops=ops)
                    project["installCommand"] = InstallUrlRecognizer(
                        slug.owner, project_name
                    ).repinned(install_cmd, install_sha, is_current=currency.is_current)
                found = True
                break

        if not found:
            self._skips.record(
                "SKIPPED — manual action required: public-website projects.json has "
                f"no entry for {project_name}, so its version was not propagated "
                f"for v{version}. Add the entry manually."
            )
            return

        projects_file.save(data)

        branch = f"propagate/v{version}-{project_name}-public-website"
        if merge_sibling(
            sibling,
            branch,
            ["src/data/projects.json"],
            f"chore: bump {project_name} to v{version}",
            "public-website",
            dry_run=dry_run,
        ):
            ops.ok(f"website: {project_name} version={version}")
        else:
            ops.ok(f"website: {project_name} already current")


@final
class Phase10Propagate:
    """Phase 10: local cross-repo propagation via PRs, run concurrently."""

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
        interrupted: threading.Event,
    ) -> None:
        """Run the three propagators concurrently.

        Every collaborator here is injected rather than composed directly, so
        a caller that rebinds ``punt_kit.release._propagate_install_all``/
        ``_propagate_marketplace``/``_propagate_website``/
        ``_reset_propagation_siblings`` has each observed by
        ``punt_kit.release._phase10_propagate``. ``interrupted`` is release.py's
        own ``threading.Event`` (its signal handler sets it), so it is passed
        in.
        """
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print("\n[bold]Phase 10: Propagate[/bold]")

        # Auto-recover siblings left on propagation branches from a prior
        # interrupted run. No-op when all siblings are already on main.
        if not dry_run:
            reset_propagation_siblings(info)

        with ThreadPoolExecutor(max_workers=3) as pool:
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
            }
            try:
                ThreadedStep(ops=ops).collect(futures, interrupted=interrupted)
            except ReleaseError as exc:
                # Recorded before re-raising: the summary drains _skips even
                # when the pipeline stops before reaching a successful
                # pipeline.summarize() call, so a thread failure here still
                # reaches the end-of-run recap — not only recorded skips
                # (an absent sibling, etc.) as before.
                self._skips.record(f"FAILED — Phase 10 propagation: {exc}")
                raise
