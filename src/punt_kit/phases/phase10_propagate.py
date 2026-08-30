"""Phase 10: local cross-repo propagation via PRs — install-all.sh SHA,
marketplace.json, and public-website projects.json."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.gh import GithubRepo
from punt_kit.phases.shared.pipeline import ThreadedStep
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.siblings import GITHUB_ABSENT_SKIP, SiblingRepo

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from concurrent.futures import Future
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.siblings import SkipRecorder

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

        repo = GithubRepo(info.root, ops=ops).resolve()
        if repo is None:
            return
        project_name = repo.split("/")[-1]

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
            return  # unreachable

        tag = f"v{version}"
        install_sha = ReleaseProject(info, ops=ops).install_sh_sha()

        content = install_all.read_text(encoding="utf-8")
        esc = re.escape(project_name)
        pattern = rf"(\$GH/{esc}/)[0-9a-fA-F]{{7,40}}(/install\.sh)"
        new_content, count = re.subn(pattern, rf"\g<1>{install_sha}\2", content)

        if count == 0:
            ops.info(f"install-all.sh: no entry for {project_name} — skipping")
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
            install_all.write_text(new_content, encoding="utf-8")
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

        github_sha = ops.run(
            ["git", "log", "-1", "--format=%h", "--", "install-all.sh"],
            cwd=str(sibling),
        ).stdout.strip()
        if not github_sha:
            ops.info(
                "profile/README.md: no commits touch install-all.sh yet — "
                "skipping SHA update"
            )
            return

        readme_content = readme.read_text(encoding="utf-8")
        new_readme, readme_count = re.subn(
            r"(punt-labs/\.github/)[0-9a-fA-F]{7,40}(/install-all\.sh)",
            rf"\g<1>{github_sha}\2",
            readme_content,
        )
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

        readme.write_text(new_readme, encoding="utf-8")
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

    __slots__ = ("_info", "_ops")

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
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

        repo = GithubRepo(info.root, ops=ops).resolve()
        if repo is None:
            return
        project_name = repo.split("/")[-1]
        tag = f"v{version}"

        claude_plugins_sibling = SiblingRepo.resolve(
            info.root, "claude-plugins", ops=ops
        )
        if claude_plugins_sibling is None:
            ops.fail(
                "Sibling claude-plugins not found — required for marketplace "
                "propagation"
            )
            return

        sibling = claude_plugins_sibling.path
        marketplace_path = sibling / ".claude-plugin" / "marketplace.json"
        if not marketplace_path.exists():
            ops.fail("marketplace.json not found in claude-plugins")
            return

        if dry_run:
            ops.dry(
                f"../claude-plugins/marketplace.json: "
                f"{project_name} version={version}, ref={tag}"
            )
            return

        claude_plugins_sibling.validate()

        raw = json.loads(marketplace_path.read_text(encoding="utf-8"))
        data = cast("dict[str, object]", raw)
        plugins = cast("list[dict[str, object]]", data.get("plugins", []))

        # Marketplace entries key on the plugin's SHORT name (e.g. "punt"),
        # not the PyPI distribution name (e.g. "punt-kit") — read it from the
        # project's own plugin.json (post -dev-strip).
        marketplace_name = ReleaseProject(info, ops=ops).marketplace_name()
        candidates = {n for n in (marketplace_name, project_name) if n}

        found = False
        for plugin in plugins:
            src = cast("dict[str, str]", plugin.get("source", {}))
            # marketplace.json uses "url" for keyless HTTPS installs (git-subdir
            # and the earlier plain-url source) — "repo" was the pre-migration
            # key that pulled the whole repo to disk, and no live entry uses it
            # anymore. See pkit-p328 and claude-plugins commit b77f1ed.
            source_url = str(src.get("url", "")).removesuffix(".git")
            if (
                any(source_url.endswith("/" + n) for n in candidates)
                or plugin.get("name") in candidates
            ):
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

        marketplace_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

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

    __slots__ = ("_info", "_ops")

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
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
        repo = GithubRepo(info.root, ops=ops).resolve()
        if repo is None:
            return
        project_name = repo.split("/")[-1]

        website_sibling = SiblingRepo.resolve(info.root, "public-website", ops=ops)
        if website_sibling is None:
            ops.info("Sibling public-website not found — skipping website update")
            return

        sibling = website_sibling.path
        projects_json = sibling / "src" / "data" / "projects.json"
        if not projects_json.exists():
            ops.info("projects.json not found in public-website — skipping")
            return

        if dry_run:
            ops.dry(
                f"../public-website/projects.json: {project_name} version={version}"
            )
            return

        website_sibling.validate()

        data = json.loads(projects_json.read_text(encoding="utf-8"))

        found = False
        for project in data:
            github_url = project.get("githubUrl") or ""
            if project.get("id") == project_name or github_url.endswith(
                "/" + project_name
            ):
                project["version"] = version
                # Update installCommand SHA if present
                install_cmd = project.get("installCommand") or ""
                if install_cmd and f"/{project_name}/" in install_cmd:
                    install_sha = ReleaseProject(info, ops=ops).install_sh_sha()
                    project["installCommand"] = re.sub(
                        rf"({re.escape(project_name)}/)[0-9a-fA-F]{{7,40}}"
                        r"(/install\.sh)",
                        rf"\g<1>{install_sha}\2",
                        install_cmd,
                    )
                found = True
                break

        if not found:
            ops.info(f"No website entry for {project_name} — skipping")
            return

        projects_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

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

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls,
        info: ProjectInfo,
        version: str,
        *,
        dry_run: bool,
        ops: ReleaseOps,
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
        reset_propagation_siblings: Callable[[ProjectInfo], None],
        propagate_install_all: Callable[..., None],
        propagate_marketplace: Callable[..., None],
        propagate_website: Callable[..., None],
        interrupted: threading.Event,
    ) -> None:
        """Run the three propagators concurrently.

        Every collaborator here is injected rather than composed directly:
        ``test_phase10_propagate_runs_concurrently`` and
        ``test_phase10_propagate_collects_errors`` monkeypatch
        ``punt_kit.release._propagate_install_all``/``_propagate_marketplace``/
        ``_propagate_website``/``_reset_propagation_siblings`` and call
        ``punt_kit.release._phase10_propagate`` expecting every patch to be
        observed. ``interrupted`` is release.py's own ``threading.Event``,
        which stays unmoved in release.py per §1a and so must be passed in.
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
            ThreadedStep(ops=ops).collect(futures, interrupted=interrupted)
