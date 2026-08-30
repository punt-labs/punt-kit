"""Phase 11: post-release verification checks across the project and its
propagation siblings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.gh import GithubRepo
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.siblings import GITHUB_ABSENT_SKIP, SiblingRepo
from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.siblings import SkipRecorder

# Separate from Reporter's singleton — phase banners and per-check verdict
# lines use raw console.print() with rich markup, not the _ok/_info/_warn
# vocabulary.
_console = Console()


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    """One named pass/fail verdict with a human-readable detail."""

    name: str
    passed: bool
    detail: str


@final
class MarketplacePinCheck:
    """Verifies the marketplace-pin chain for marketplace-only plugins.

    Used only when a project has no ``install.sh`` — the profile-SHA check
    has no direct install URL to verify against, so the pin chain (profile
    -> install-all.sh's claude-plugins SHA -> that commit's
    marketplace.json) is the equivalent invariant.
    """

    __slots__ = ()

    def run(
        self,
        cp_sibling: Path | None,
        claude_plugins_sha: str,
        candidates: frozenset[str],
        version: str,
        tag: str,
        *,
        ops: ReleaseOps,
    ) -> tuple[bool, str]:
        """Check a pinned claude-plugins commit's marketplace.json for this project.

        ``candidates`` is the set of names to accept for the entry — the caller
        supplies both the PyPI distribution name and the marketplace short
        name (see ``ReleaseProject.marketplace_name``), since marketplace
        entries key on the plugin's short name (``punt``) while the CLI knows
        the project by the pyproject distribution name (``punt-kit``).

        Returns ``(passed, detail)``.
        """
        if cp_sibling is None:
            return False, "claude-plugins sibling not found"
        show = ops.run(
            ["git", "show", f"{claude_plugins_sha}:.claude-plugin/marketplace.json"],
            cwd=str(cp_sibling),
            check=False,
        )
        if show.returncode != 0:
            return False, f"claude-plugins@{claude_plugins_sha} does not resolve"
        data = cast("dict[str, object]", json.loads(show.stdout))
        plugins = cast("list[dict[str, object]]", data.get("plugins", []))
        for p in plugins:
            src = cast("dict[str, str]", p.get("source", {}))
            # marketplace.json uses "url" for keyless HTTPS installs
            # (git-subdir and the earlier plain-url source). "repo" was the
            # pre-migration key that cloned the whole repo to disk and no live
            # entry uses it anymore. See pkit-p328 and claude-plugins commit
            # b77f1ed.
            source_url = str(src.get("url", "")).removesuffix(".git")
            if (
                any(source_url.endswith("/" + n) for n in candidates)
                or str(p.get("name", "")) in candidates
            ):
                ok = (
                    str(p.get("version", "")) == version
                    and str(src.get("ref", "")) == tag
                )
                return (
                    ok,
                    f"claude-plugins@{claude_plugins_sha} version={p.get('version')}, "
                    f"ref={src.get('ref')}",
                )
        names = ",".join(sorted(candidates)) or "?"
        return (
            False,
            f"claude-plugins@{claude_plugins_sha} has no entry for {names}",
        )


@final
class Phase11Verify:
    """Phase 11: run release verification checks."""

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

    def run(self) -> None:
        info = self._info
        version = self._version
        ops = self._ops
        _console.print("\n[bold]Phase 11: Verify[/bold]")

        if self._dry_run:
            ops.dry("Would run release verification checks")
            return

        project = ReleaseProject(info, ops=ops)
        tag = f"v{version}"
        checks: list[VerificationCheck] = []

        # 1. Git tag exists
        result = ops.run(["git", "tag", "--list", tag], cwd=str(info.root), check=False)
        tag_exists = tag in result.stdout.split()
        checks.append(
            VerificationCheck("Git tag", tag_exists, tag if tag_exists else "not found")
        )

        # 2. Version consistency (read fresh from disk — info.pyproject is
        # stale after Phase 2 bumps the version)
        pyproject_path = info.root / "pyproject.toml"
        if pyproject_path.exists():
            content = pyproject_path.read_text(encoding="utf-8")
            match = re.search(r'^version\s*=\s*"([^"]*)"', content, re.MULTILINE)
            current = match.group(1) if match else "not found"
            checks.append(
                VerificationCheck(
                    "pyproject.toml", current == version, f"version={current}"
                )
            )

        pkg_dir = project.package_dir()
        if pkg_dir is not None:
            init_py = pkg_dir / "__init__.py"
            if init_py.exists():
                content = init_py.read_text(encoding="utf-8")
                uses_metadata = (
                    "importlib.metadata" in content or "importlib_metadata" in content
                )
                if not uses_metadata:
                    match = re.search(r'__version__\s*=\s*"([^"]*)"', content)
                    if match:
                        init_ver = match.group(1)
                        checks.append(
                            VerificationCheck(
                                "__init__.py",
                                init_ver == version,
                                f"__version__={init_ver}",
                            )
                        )

        if info.is_plugin:
            pj_data = json.loads(info.plugin_manifest.read_text(encoding="utf-8"))
            pj_ver = pj_data.get("version", "not found")
            checks.append(
                VerificationCheck("plugin.json", pj_ver == version, f"version={pj_ver}")
            )

        install_sh = info.root / "install.sh"
        if install_sh.exists():
            content = install_sh.read_text(encoding="utf-8")
            match = re.search(r'VERSION="([^"]*)"', content)
            if match:
                install_ver = match.group(1)
                checks.append(
                    VerificationCheck(
                        "install.sh", install_ver == version, f"VERSION={install_ver}"
                    )
                )

        # 3. Changelog stamped (must have date: ## [X.Y.Z] - YYYY-MM-DD)
        changelog = Changelog(info.root, ops=ops).text()
        stamped = bool(
            re.search(
                rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}",
                changelog,
                re.MULTILINE,
            )
        )
        checks.append(
            VerificationCheck(
                "CHANGELOG", stamped, "stamped" if stamped else "not stamped"
            )
        )

        # 4. install-all.sh entry (curl SHA for CLI projects, plugin loop for
        # pure plugins)
        repo = GithubRepo(info.root, ops=ops).resolve()
        if repo and (install_sh.exists() or info.is_plugin):
            project_name = repo.split("/")[-1]
            github_sibling = SiblingRepo.resolve(info.root, ".github", ops=ops)
            if github_sibling is None:
                # An absent .github sibling is not a verification failure:
                # Phase 10a already skipped propagation for the same reason
                # (the workspace meta-repo layout has no resolvable .github
                # sibling), and this phase runs after the release has
                # published. Recording the skip surfaces it without
                # flipping all_pass — a False here would exit non-zero on
                # an already-published release and read identically to a
                # real defect.
                self._skips.record(
                    GITHUB_ABSENT_SKIP.format(name=project_name, ver=version)
                )
            else:
                sibling = github_sibling.path
                install_all = sibling / "install-all.sh"
                if not install_all.exists():
                    checks.append(
                        VerificationCheck(
                            "install-all.sh", False, "install-all.sh not found"
                        )
                    )
                else:
                    iac = install_all.read_text(encoding="utf-8")
                    curl_match = re.search(
                        rf"\$GH/{re.escape(project_name)}/"
                        r"([0-9a-fA-F]{7,40})/install\.sh",
                        iac,
                    )
                    if curl_match:
                        sha = curl_match.group(1)
                        vr = ops.run(
                            ["git", "show", f"{sha}:install.sh"],
                            cwd=str(info.root),
                            check=False,
                        )
                        if vr.returncode != 0:
                            sha_ok = False
                        elif f'VERSION="{version}"' in vr.stdout:
                            # Python/hybrid: VERSION pin matches
                            sha_ok = True
                        else:
                            # Go/other: no VERSION pin — SHA resolves
                            sha_ok = 'VERSION="' not in vr.stdout
                        checks.append(
                            VerificationCheck("install-all.sh", sha_ok, f"SHA={sha}")
                        )
                    elif re.search(
                        rf"for plugin in [^;]*\b{re.escape(project_name)}\b",
                        iac,
                    ):
                        # Pure-plugin loop entry (no SHA to verify)
                        checks.append(
                            VerificationCheck("install-all.sh", True, "in plugin loop")
                        )
                    else:
                        checks.append(
                            VerificationCheck(
                                "install-all.sh", False, "entry not found"
                            )
                        )

        # 5. Marketplace
        if info.is_plugin or info.is_hybrid:
            repo = GithubRepo(info.root, ops=ops).resolve()
            if repo:
                project_name = repo.split("/")[-1]
                marketplace_name = ReleaseProject(info, ops=ops).marketplace_name()
                candidates = frozenset(n for n in (marketplace_name, project_name) if n)
                claude_plugins_sibling = SiblingRepo.resolve(
                    info.root, "claude-plugins", ops=ops
                )
                if claude_plugins_sibling is None:
                    checks.append(
                        VerificationCheck(
                            "marketplace", False, "sibling claude-plugins not found"
                        )
                    )
                else:
                    mp = (
                        claude_plugins_sibling.path
                        / ".claude-plugin"
                        / "marketplace.json"
                    )
                    if not mp.exists():
                        checks.append(
                            VerificationCheck(
                                "marketplace", False, "marketplace.json not found"
                            )
                        )
                    else:
                        data = cast(
                            "dict[str, object]",
                            json.loads(mp.read_text(encoding="utf-8")),
                        )
                        plugins = cast(
                            "list[dict[str, object]]", data.get("plugins", [])
                        )
                        mp_found = False
                        for p in plugins:
                            src = cast("dict[str, str]", p.get("source", {}))
                            # marketplace.json uses source.url (keyless HTTPS,
                            # git-subdir). See pkit-p328.
                            source_url = str(src.get("url", "")).removesuffix(".git")
                            if (
                                any(source_url.endswith("/" + n) for n in candidates)
                                or p.get("name") in candidates
                            ):
                                mp_ver = str(p.get("version", ""))
                                mp_ref = str(src.get("ref", ""))
                                ok = mp_ver == version and mp_ref == tag
                                checks.append(
                                    VerificationCheck(
                                        "marketplace",
                                        ok,
                                        f"version={mp_ver}, ref={mp_ref}",
                                    )
                                )
                                mp_found = True
                                break
                        if not mp_found:
                            names = ",".join(sorted(candidates))
                            checks.append(
                                VerificationCheck(
                                    "marketplace",
                                    False,
                                    f"no entry for {names}",
                                )
                            )

        # 6. Profile SHA (install-all.sh URL resolves)
        repo = GithubRepo(info.root, ops=ops).resolve()
        if repo and (install_sh.exists() or info.is_plugin):
            github_sibling = SiblingRepo.resolve(info.root, ".github", ops=ops)
            if github_sibling is None:
                # Absent sibling — same tolerated case as the install-all.sh
                # check above. The shared message deduplicates in _skips, so
                # the two checks collapse to one recap line rather than
                # double-reporting.
                self._skips.record(
                    GITHUB_ABSENT_SKIP.format(name=repo.split("/")[-1], ver=version)
                )
            else:
                sibling = github_sibling.path
                readme = sibling / "profile" / "README.md"
                if not readme.exists():
                    checks.append(
                        VerificationCheck(
                            "profile SHA", False, "profile/README.md not found"
                        )
                    )
                else:
                    content = readme.read_text(encoding="utf-8")
                    sha_match = re.search(
                        r"punt-labs/\.github/([0-9a-fA-F]{7,40})/install-all\.sh",
                        content,
                    )
                    if not sha_match:
                        checks.append(
                            VerificationCheck(
                                "profile SHA",
                                False,
                                "no .github install-all.sh URL in profile",
                            )
                        )
                    else:
                        profile_sha = sha_match.group(1)
                        # The pinned SHA must resolve AND its content must
                        # carry this project's current install SHA — a
                        # resolvable pin that predates the propagation merge
                        # is stale and serves the previous installer.
                        show_result = ops.run(
                            ["git", "show", f"{profile_sha}:install-all.sh"],
                            cwd=str(sibling),
                            check=False,
                        )
                        if show_result.returncode != 0:
                            checks.append(
                                VerificationCheck(
                                    "profile SHA",
                                    False,
                                    f"SHA={profile_sha} (does not resolve)",
                                )
                            )
                        elif install_sh.exists():
                            project_name = repo.split("/")[-1]
                            install_sha = project.install_sh_sha()
                            current_entry = re.search(
                                rf"\$GH/{re.escape(project_name)}/"
                                rf"{re.escape(install_sha)}[0-9a-fA-F]*/install\.sh",
                                show_result.stdout,
                            )
                            checks.append(
                                VerificationCheck(
                                    "profile SHA",
                                    current_entry is not None,
                                    f"SHA={profile_sha}"
                                    + (
                                        ""
                                        if current_entry
                                        else (
                                            " (stale — lacks "
                                            f"{project_name}@{install_sha})"
                                        )
                                    ),
                                )
                            )
                        else:
                            # Marketplace-only plugin: no install.sh, so
                            # there is no direct curl URL to verify. The
                            # equivalent invariant is the marketplace-pin
                            # chain — the profile-pinned install-all.sh
                            # names a claude-plugins SHA, and that commit's
                            # marketplace.json must carry this project's
                            # current version/ref.
                            project_name = repo.split("/")[-1]
                            mp_pin = re.search(
                                r"\$GH/claude-plugins/([0-9a-fA-F]{7,40})/install\.sh",
                                show_result.stdout,
                            )
                            if mp_pin is None:
                                checks.append(
                                    VerificationCheck(
                                        "profile SHA",
                                        False,
                                        f"SHA={profile_sha} "
                                        "(no claude-plugins pin in install-all.sh)",
                                    )
                                )
                            else:
                                cp_sibling_repo = SiblingRepo.resolve(
                                    info.root, "claude-plugins", ops=ops
                                )
                                cp_sibling = (
                                    cp_sibling_repo.path
                                    if cp_sibling_repo is not None
                                    else None
                                )
                                marketplace_name = ReleaseProject(
                                    info, ops=ops
                                ).marketplace_name()
                                candidates = frozenset(
                                    n for n in (marketplace_name, project_name) if n
                                )
                                ok, detail = MarketplacePinCheck().run(
                                    cp_sibling,
                                    mp_pin.group(1),
                                    candidates,
                                    version,
                                    tag,
                                    ops=ops,
                                )
                                checks.append(
                                    VerificationCheck(
                                        "profile SHA",
                                        ok,
                                        f"SHA={profile_sha} ({detail})",
                                    )
                                )

        # 7. Website (optional — sibling may not exist)
        if repo:
            project_name = repo.split("/")[-1]
            website_sibling = SiblingRepo.resolve(info.root, "public-website", ops=ops)
            if website_sibling is not None:
                pj = website_sibling.path / "src" / "data" / "projects.json"
                if pj.exists():
                    data = json.loads(pj.read_text(encoding="utf-8"))
                    web_found = False
                    for entry in data:
                        github_url = entry.get("githubUrl") or ""
                        if entry.get("id") == project_name or github_url.endswith(
                            "/" + project_name
                        ):
                            web_ver = entry.get("version")
                            checks.append(
                                VerificationCheck(
                                    "website",
                                    web_ver == version,
                                    f"version={web_ver}",
                                )
                            )
                            web_found = True
                            break
                    if not web_found:
                        checks.append(
                            VerificationCheck(
                                "website", False, f"no entry for {project_name}"
                            )
                        )

        # 8. PyPI — confirm the exact published version resolves from the
        # INDEX. `uv pip install --dry-run` uses uv's own resolver, so it
        # needs no `pip` binary (uv-managed project venvs do not ship one —
        # `uv run pip` fails with "Failed to spawn: pip"). This must assert
        # index presence, not mere local resolvability: by this phase the
        # wheel was built locally (Phase 3) and installed from PyPI (Phase
        # 8), so `<pkg>==<version>` is almost certainly in uv's cache and
        # the environment. `--no-cache` forbids satisfying the resolve from
        # the download cache, and `--reinstall` forbids satisfying it from
        # the already-installed environment — together they force a fresh
        # index query, so a green result can only mean the version is
        # actually published. `--no-deps` isolates the signal to this one
        # package==version, so a transiently unresolvable transitive
        # dependency cannot mask a successful publish. `--dry-run` installs
        # nothing. Resolvable → exit 0; absent → non-zero ("unsatisfiable").
        # Run in the project dir so uv resolves against the project's
        # environment.
        if info.language == "python":
            package_name = project.package_name()
            result = ops.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--dry-run",
                    "--no-deps",
                    "--no-cache",
                    "--reinstall",
                    f"{package_name}=={version}",
                ],
                cwd=str(info.root),
                check=False,
                timeout=UV,
            )
            pypi_ok = result.returncode == 0
            checks.append(
                VerificationCheck("PyPI", pypi_ok, f"{package_name}=={version}")
            )

        # Print results
        all_pass = True
        for check in checks:
            if check.passed:
                ops.ok(f"{check.name}: {check.detail}")
            else:
                _console.print(f"  [red]✗[/red] {check.name}: {check.detail}")
                all_pass = False

        if not all_pass:
            ops.fail("Some verification checks failed — see above")
