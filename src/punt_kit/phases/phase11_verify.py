"""Phase 11: post-release verification checks across the project and its
propagation siblings."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.phase11_checks import MarketplacePinCheck, VerificationCheck
from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.entry_matcher import EntryMatcher
from punt_kit.phases.shared.errors import RemoteLookupError
from punt_kit.phases.shared.github_repo import GithubRepo
from punt_kit.phases.shared.install_urls import InstallUrlRecognizer
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.pin_currency import PinCurrency
from punt_kit.phases.shared.pin_rules import ShaPin
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.siblings import SiblingRepo
from punt_kit.phases.shared.skips import GITHUB_ABSENT_SKIP
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.phases.shared.timeouts import UV
from punt_kit.phases.shared.version_assignment import VersionAssignment

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.repo_slug import RepoSlug
    from punt_kit.phases.shared.skips import SkipRecorder

# Separate from Reporter's singleton: the phase banner prints with rich
# markup; the per-check verdict lines go through ``ops``.
_console = Console()


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

    @property
    def _tag(self) -> str:
        return f"v{self._version}"

    def run(self) -> None:
        ops = self._ops
        _console.print("\n[bold]Phase 11: Verify[/bold]")

        if self._dry_run:
            ops.dry("Would run release verification checks")
            return

        checks = self._local_checks()
        repo, remote_checks = self._remote_slug()
        checks.extend(remote_checks)
        if repo is None and not remote_checks:
            self._skips.record(
                "SKIPPED — manual action required: the install-all.sh, marketplace, "
                "README and website checks did not run because the project has no "
                "github.com origin remote."
            )
        if repo is not None:
            checks.extend(self._install_all_checks(repo))
            checks.extend(self._marketplace_checks(repo))
            checks.extend(self._profile_checks(repo))
            checks.extend(self._readme_checks(repo))
            checks.extend(self._website_checks(repo))
        checks.extend(self._pypi_checks())

        all_pass = True
        for check in checks:
            if check.passed:
                ops.ok(f"{check.name}: {check.detail}")
            else:
                ops.error(f"{check.name}: {check.detail}")
                all_pass = False

        if not all_pass:
            ops.fail("Some verification checks failed — see above")

    def _local_checks(self) -> list[VerificationCheck]:
        """The tag, the version in every file that pins it, and the changelog."""
        info = self._info
        ops = self._ops
        tag = self._tag
        listing = ops.run(
            ["git", "tag", "--list", tag], cwd=str(info.root), check=False
        )
        tag_exists = tag in listing.stdout.split()
        checks = [
            VerificationCheck("Git tag", tag_exists, tag if tag_exists else "not found")
        ]
        checks.extend(self._version_pin_checks())
        # Stamped means dated: ## [X.Y.Z] - YYYY-MM-DD
        stamped = Changelog(info.root, ops=ops).is_stamped(self._version)
        checks.append(
            VerificationCheck(
                "CHANGELOG", stamped, "stamped" if stamped else "not stamped"
            )
        )
        return checks

    def _version_pin_checks(self) -> list[VerificationCheck]:
        """Version consistency, read fresh from disk (``info.pyproject`` is stale
        after Phase 2 bumps the version)."""
        info = self._info
        version = self._version
        checks: list[VerificationCheck] = []

        pyproject_path = info.root / "pyproject.toml"
        if pyproject_path.exists():
            content = TextFile(pyproject_path).read()
            current = VersionAssignment("version").read(content) or "not found"
            checks.append(
                VerificationCheck(
                    "pyproject.toml", current == version, f"version={current}"
                )
            )

        pkg_dir = ReleaseProject(info, ops=self._ops).package_dir()
        if pkg_dir is not None and (pkg_dir / "__init__.py").exists():
            content = TextFile(pkg_dir / "__init__.py").read()
            uses_metadata = (
                "importlib.metadata" in content or "importlib_metadata" in content
            )
            assignment = VersionAssignment("__version__")
            if assignment.is_assigned(content) and not uses_metadata:
                init_ver = assignment.read(content)
                if init_ver is None:
                    checks.append(
                        VerificationCheck(
                            "__init__.py",
                            False,
                            "__version__ is assigned but not as a plain quoted "
                            "string, so it cannot be verified",
                        )
                    )
                else:
                    checks.append(
                        VerificationCheck(
                            "__init__.py",
                            init_ver == version,
                            f"__version__={init_ver}",
                        )
                    )

        if info.is_plugin:
            pj_data = cast("dict[str, object]", JsonFile(info.plugin_manifest).load())
            pj_ver = pj_data.get("version", "not found")
            checks.append(
                VerificationCheck("plugin.json", pj_ver == version, f"version={pj_ver}")
            )

        install_sh = info.root / "install.sh"
        if install_sh.exists():
            match = re.search(r'VERSION="([^"]*)"', TextFile(install_sh).read())
            if match:
                install_ver = match.group(1)
                checks.append(
                    VerificationCheck(
                        "install.sh", install_ver == version, f"VERSION={install_ver}"
                    )
                )
        return checks

    def _remote_slug(self) -> tuple[RepoSlug | None, list[VerificationCheck]]:
        """The project's GitHub slug (``None`` when there is nothing to verify),
        and the failed checks resolving it produced.

        A remote that names GitHub but is not ``owner/repo``, a lookup git
        could not answer, and a missing github.com origin on a project that
        installs or publishes through GitHub are each one failed check here,
        and every slug-dependent check below is skipped: they must not
        vanish silently.
        """
        info = self._info
        try:
            slug = GithubRepo(info.root, ops=self._ops).slug()
        except (ValueError, RemoteLookupError) as exc:
            return None, [VerificationCheck("GitHub remote", False, str(exc))]
        if slug is None and (self._installs_from_github() or info.is_hybrid):
            detail = (
                "no github.com origin remote — the install-all.sh, marketplace, "
                "README, and website checks could not run"
            )
            return None, [VerificationCheck("GitHub remote", False, detail)]
        return slug, []

    def _installs_from_github(self) -> bool:
        """True for a project with an ``install.sh`` or a plugin manifest."""
        return (self._info.root / "install.sh").exists() or self._info.is_plugin

    def _github_sibling(self, repo: RepoSlug) -> Path | None:
        """The ``.github`` sibling's path; an absent one is recorded as a skip.

        An absent .github sibling is not a verification failure: Phase 10a
        already skipped propagation for the same reason (the workspace
        meta-repo layout has no resolvable .github sibling), and this phase
        runs after the release has published. Recording the skip surfaces it
        without flipping the verdict — a failed check here would exit non-zero
        on an already-published release and read identically to a real
        defect. The shared message deduplicates, so the install-all.sh and
        profile checks collapse to one recap line.
        """
        sibling = SiblingRepo.resolve(self._info.root, ".github", ops=self._ops)
        if sibling is None:
            self._skips.record(
                GITHUB_ABSENT_SKIP.format(name=repo.name, ver=self._version)
            )
            return None
        return sibling.path

    def _entry_matcher(self, repo: RepoSlug) -> EntryMatcher:
        """Matches marketplace entries by the plugin's short name or its repo."""
        marketplace_name = ReleaseProject(self._info, ops=self._ops).marketplace_name()
        return EntryMatcher(
            repo.owner,
            repo.name,
            frozenset(n for n in (marketplace_name, repo.name) if n),
        )

    def _install_all_checks(self, repo: RepoSlug) -> list[VerificationCheck]:
        """The install-all.sh entry: a curl SHA for CLI projects, a plugin loop
        entry for pure plugins."""
        if not self._installs_from_github():
            return []
        sibling = self._github_sibling(repo)
        if sibling is None:
            return []
        install_all = sibling / "install-all.sh"
        if not install_all.exists():
            return [
                VerificationCheck("install-all.sh", False, "install-all.sh not found")
            ]
        content = TextFile(install_all).read()
        # Every pin line is verified, not the first: a second, stale line is
        # exactly what a partial propagation leaves behind.
        shas = self._distinct(ShaPin.install_all_entry(repo.name).all_shas(content))
        if shas:
            return [self._install_all_sha_check(sha) for sha in shas]
        if re.search(rf"for plugin in [^;]*\b{re.escape(repo.name)}\b", content):
            # Pure-plugin loop entry (no SHA to verify)
            return [VerificationCheck("install-all.sh", True, "in plugin loop")]
        return [VerificationCheck("install-all.sh", False, "entry not found")]

    @staticmethod
    def _distinct(shas: list[str]) -> list[str]:
        """``shas`` without repeats, in first-seen order."""
        return list(dict.fromkeys(shas))

    def _install_all_sha_check(self, sha: str) -> VerificationCheck:
        """A pinned install-all.sh SHA must be current and part of this release."""
        ops = self._ops
        root = str(self._info.root)
        shown = ops.run(["git", "show", f"{sha}:install.sh"], cwd=root, check=False)
        if shown.returncode != 0:
            return VerificationCheck(
                "install-all.sh", False, f"SHA={sha} (does not resolve)"
            )
        # A resolvable SHA whose content happens to match is not enough — the
        # pin has to actually be part of this release. Without this, a SHA on
        # an unmerged or superseded branch (never reachable from the tag) can
        # carry the right VERSION string by coincidence and pass a
        # content-only check while installing an untagged commit.
        ancestor = ops.run(
            ["git", "merge-base", "--is-ancestor", sha, self._tag],
            cwd=root,
            check=False,
        )
        if ancestor.returncode == 1:
            return VerificationCheck(
                "install-all.sh", False, f"SHA={sha} (not an ancestor of {self._tag})"
            )
        if ancestor.returncode != 0:
            # merge-base --is-ancestor exits 1 for "not an ancestor" and >=128
            # for a genuine git error (e.g. a missing ref) — the latter is not
            # a stale pin and must not be reported as one, or the operator
            # debugs the wrong problem.
            return VerificationCheck(
                "install-all.sh",
                False,
                f"SHA={sha} (git error verifying ancestry: {ancestor.stderr.strip()})",
            )
        # The same test the propagator rewrites with: the pin names the commit
        # that last touched install.sh. Ancestry and VERSION below are
        # necessary, not sufficient: a Go project has no VERSION pin, so an
        # older install.sh commit on the tag's history would pass both.
        currency = PinCurrency(
            ReleaseProject(self._info, ops=ops).install_sh_sha(),
            cwd=self._info.root,
            ops=ops,
        ).verdict(sha)
        if not currency.is_current:
            return VerificationCheck("install-all.sh", False, currency.detail)
        # Python/hybrid: the VERSION pin matches. Go/other: there is no VERSION
        # pin, and a SHA that resolves and is on the tag's history is enough.
        ok = f'VERSION="{self._version}"' in shown.stdout or 'VERSION="' not in (
            shown.stdout
        )
        return VerificationCheck("install-all.sh", ok, f"SHA={sha}")

    def _marketplace_checks(self, repo: RepoSlug) -> list[VerificationCheck]:
        """The marketplace entry's version and ref, for plugin and hybrid projects."""
        info = self._info
        if not (info.is_plugin or info.is_hybrid):
            return []
        matcher = self._entry_matcher(repo)
        sibling = SiblingRepo.resolve(info.root, "claude-plugins", ops=self._ops)
        if sibling is None:
            return [
                VerificationCheck(
                    "marketplace", False, "sibling claude-plugins not found"
                )
            ]
        marketplace = sibling.path / ".claude-plugin" / "marketplace.json"
        if not marketplace.exists():
            return [
                VerificationCheck("marketplace", False, "marketplace.json not found")
            ]
        data = cast("dict[str, object]", JsonFile(marketplace).load())
        plugins = cast("list[dict[str, object]]", data.get("plugins", []))
        entry = next((p for p in plugins if matcher.claims_plugin(p)), None)
        if entry is None:
            names = ",".join(sorted(matcher.names))
            return [VerificationCheck("marketplace", False, f"no entry for {names}")]
        source = cast("dict[str, str]", entry.get("source", {}))
        entry_version = str(entry.get("version", ""))
        entry_ref = str(source.get("ref", ""))
        ok = entry_version == self._version and entry_ref == self._tag
        return [
            VerificationCheck(
                "marketplace", ok, f"version={entry_version}, ref={entry_ref}"
            )
        ]

    def _profile_checks(self, repo: RepoSlug) -> list[VerificationCheck]:
        """The org profile's install-all.sh pin: resolves, is on main, is current."""
        if not self._installs_from_github():
            return []
        sibling = self._github_sibling(repo)
        if sibling is None:
            return []
        readme = sibling / "profile" / "README.md"
        if not readme.exists():
            return [
                VerificationCheck("profile SHA", False, "profile/README.md not found")
            ]
        profile_shas = self._distinct(
            ShaPin.profile().all_shas(TextFile(readme).read())
        )
        if not profile_shas:
            return [
                VerificationCheck(
                    "profile SHA", False, "no .github install-all.sh URL in profile"
                )
            ]
        return [self._profile_pin_check(repo, sibling, sha) for sha in profile_shas]

    def _profile_pin_check(
        self, repo: RepoSlug, sibling: Path, profile_sha: str
    ) -> VerificationCheck:
        """One profile pin: it resolves, is on main, and carries the current SHA."""
        # The pinned SHA must resolve AND its content must carry this
        # project's current install SHA — a resolvable pin that predates the
        # propagation merge is stale and serves the previous installer.
        shown = self._ops.run(
            ["git", "show", f"{profile_sha}:install-all.sh"],
            cwd=str(sibling),
            check=False,
        )
        if shown.returncode != 0:
            return VerificationCheck(
                "profile SHA", False, f"SHA={profile_sha} (does not resolve)"
            )
        ancestor = self._ops.run(
            ["git", "merge-base", "--is-ancestor", profile_sha, "main"],
            cwd=str(sibling),
            check=False,
        )
        if ancestor.returncode != 0:
            # git show resolves any object still in the local DB, merged or
            # not — a commit from an abandoned or reverted PR branch resolves
            # for a while after it stops being reachable from main.
            # Reachability is the property CI's checkout of main actually
            # depends on. Distinguish "not an ancestor" (exit 1) from a
            # genuine git error (exit >=128, e.g. a missing main ref) so a
            # git failure doesn't get misreported as a stale pin.
            detail = (
                f"SHA={profile_sha} (not an ancestor of .github main)"
                if ancestor.returncode == 1
                else (
                    f"SHA={profile_sha} (git error verifying "
                    f"ancestry: {ancestor.stderr.strip()})"
                )
            )
            return VerificationCheck("profile SHA", False, detail)
        if (self._info.root / "install.sh").exists():
            return self._profile_entry_check(repo, profile_sha, shown.stdout)
        return self._profile_marketplace_chain(repo, profile_sha, shown.stdout)

    def _profile_entry_check(
        self, repo: RepoSlug, profile_sha: str, install_all: str
    ) -> VerificationCheck:
        """The pinned install-all.sh must carry this project's current install SHA."""
        install_sha = ReleaseProject(self._info, ops=self._ops).install_sh_sha()
        currency = PinCurrency(install_sha, cwd=self._info.root, ops=self._ops)
        is_current = any(
            currency.is_current(pin)
            for pin in ShaPin.install_all_entry(repo.name).all_shas(install_all)
        )
        detail = f"SHA={profile_sha}"
        if not is_current:
            detail += f" (stale — lacks {repo.name}@{install_sha})"
        return VerificationCheck("profile SHA", is_current, detail)

    def _profile_marketplace_chain(
        self, repo: RepoSlug, profile_sha: str, install_all: str
    ) -> VerificationCheck:
        """The marketplace-pin chain, for a marketplace-only plugin.

        With no install.sh there is no direct curl URL to verify. The
        equivalent invariant is the chain: the profile-pinned install-all.sh
        names a claude-plugins SHA, and that commit's marketplace.json must
        carry this project's current version/ref.
        """
        mp_pins = self._distinct(
            ShaPin.install_all_entry("claude-plugins").all_shas(install_all)
        )
        if not mp_pins:
            return VerificationCheck(
                "profile SHA",
                False,
                f"SHA={profile_sha} (no claude-plugins pin in install-all.sh)",
            )
        cp_sibling = SiblingRepo.resolve(
            self._info.root, "claude-plugins", ops=self._ops
        )
        check = MarketplacePinCheck(
            self._entry_matcher(repo), self._version, self._tag, ops=self._ops
        )
        cp_path = cp_sibling.path if cp_sibling is not None else None
        # The first pin that fails is the verdict; all passing, the last one's.
        results = [check.run(cp_path, mp_pin) for mp_pin in mp_pins]
        ok, detail = next((r for r in results if not r[0]), results[-1])
        return VerificationCheck("profile SHA", ok, f"SHA={profile_sha} ({detail})")

    def _readme_checks(self, repo: RepoSlug) -> list[VerificationCheck]:
        """The product README's own install URLs against the current install.sh.

        See ``InstallShaCheck`` for why ancestry alone would miss the realistic
        rot. Pins are recognized by the same ``InstallUrlRecognizer``
        ``ReadmeShaPin.bump`` rewrites and verifies with, so the two can never
        disagree about what a pin is. A README with no pin at all (no install
        snippet, or a branch URL) has nothing to go stale.
        """
        readme = self._info.root / "README.md"
        if not (self._info.root / "install.sh").exists() or not readme.exists():
            return []
        return self._pin_checks(
            "README pin",
            TextFile(readme).read(),
            repo,
            all_urls_relevant=False,
        )

    def _website_checks(self, repo: RepoSlug) -> list[VerificationCheck]:
        """The website entry's version and install command (the sibling is optional)."""
        sibling = SiblingRepo.resolve(self._info.root, "public-website", ops=self._ops)
        if sibling is None:
            return []
        projects = sibling.path / "src" / "data" / "projects.json"
        if not projects.exists():
            return []
        entries = cast("list[dict[str, object]]", JsonFile(projects).load())
        matcher = EntryMatcher(repo.owner, repo.name, frozenset({repo.name}))
        entry = next((e for e in entries if matcher.claims_website(e)), None)
        if entry is None:
            return [VerificationCheck("website", False, f"no entry for {repo.name}")]
        web_version = entry.get("version")
        checks = [
            VerificationCheck(
                "website", web_version == self._version, f"version={web_version}"
            )
        ]
        install_command = str(entry.get("installCommand") or "")
        if install_command and (self._info.root / "install.sh").exists():
            # The same recognizer the README check uses, so README and website
            # validate identically — except this entry is ALREADY matched to
            # this project, so unlike a README (which legitimately documents
            # other tools' install one-liners too), EVERY install.sh URL in
            # this field is claimed to install this project.
            # all_urls_relevant=True drops the repo-name reference filter so a
            # URL pointing at a different repo — wrong owner, wrong name,
            # untrusted host, or a stale entry left over from a rename — is
            # flagged instead of silently ignored. Trusted and untrusted pins
            # are still reported independently. A branch pin or no install.sh
            # reference has no pin to go stale: no check.
            checks.extend(
                self._pin_checks(
                    "website SHA", install_command, repo, all_urls_relevant=True
                )
            )
        return checks

    def _pypi_checks(self) -> list[VerificationCheck]:
        """Confirm the exact published version resolves from the INDEX.

        `uv pip install --dry-run` uses uv's own resolver, so it needs no
        `pip` binary (uv-managed project venvs do not ship one — `uv run pip`
        fails with "Failed to spawn: pip"). This must assert index presence,
        not mere local resolvability: by this phase the wheel was built
        locally (Phase 3) and installed from PyPI (Phase 8), so
        `<pkg>==<version>` is almost certainly in uv's cache and the
        environment. `--no-cache` forbids satisfying the resolve from the
        download cache, and `--reinstall` forbids satisfying it from the
        already-installed environment — together they force a fresh index
        query, so a green result can only mean the version is actually
        published. `--no-deps` isolates the signal to this one
        package==version, so a transiently unresolvable transitive dependency
        cannot mask a successful publish. `--dry-run` installs nothing.
        Resolvable → exit 0; absent → non-zero ("unsatisfiable"). Run in the
        project dir so uv resolves against the project's environment.
        """
        info = self._info
        if info.language != "python":
            return []
        package_name = ReleaseProject(info, ops=self._ops).package_name()
        result = self._ops.run(
            [
                "uv",
                "pip",
                "install",
                "--dry-run",
                "--no-deps",
                "--no-cache",
                "--reinstall",
                f"{package_name}=={self._version}",
            ],
            cwd=str(info.root),
            check=False,
            timeout=UV,
        )
        return [
            VerificationCheck(
                "PyPI", result.returncode == 0, f"{package_name}=={self._version}"
            )
        ]

    def _pin_checks(
        self,
        label: str,
        text: str,
        slug: RepoSlug,
        *,
        all_urls_relevant: bool,
    ) -> list[VerificationCheck]:
        """One verdict per pinned install URL ``slug``'s recognizer finds in ``text``.

        Trusted and untrusted pins are detected and reported independently —
        a text can carry one trusted current-SHA pin AND one untrusted-host
        or owner pin (e.g. an injected line), and the untrusted one must
        never be skipped just because a trusted pin was also found.
        """
        recognizer = InstallUrlRecognizer(slug.owner, slug.name)
        trusted_pins, has_untrusted = recognizer.classify(
            text, all_urls_relevant=all_urls_relevant
        )
        checks: list[VerificationCheck] = []
        if trusted_pins:
            install_sha = ReleaseProject(self._info, ops=self._ops).install_sh_sha()
            currency = PinCurrency(install_sha, cwd=self._info.root, ops=self._ops)
            # A release tag is still a pin: the bump rewrites it to the install
            # SHA, so currency calls one left behind stale.
            for pin in sorted(set(trusted_pins)):
                verdict = currency.verdict(pin)
                checks.append(
                    VerificationCheck(label, verdict.is_current, verdict.detail)
                )
        if has_untrusted:
            checks.append(
                VerificationCheck(
                    label,
                    False,
                    "SHA-pinned install URL is not on the trusted "
                    f"raw.githubusercontent.com/{recognizer.slug}/ host",
                )
            )
        return checks
