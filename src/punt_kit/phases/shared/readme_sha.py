"""Pinning README's install-URL SHA to the commit that last touched
install.sh, and landing that pin via its own PR right after the release
squash-merge lands on main."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, cast, final
from urllib.parse import urlparse

from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps


@final
class ReadmeShaPin:
    """Keeps README's SHA-pinned install URL current with install.sh's commit."""

    __slots__ = ("_info", "_ops")

    # Single source of truth for the SHA charclass in a pinned install URL.
    # bump()'s SHA-refresh substitution and classify_install_urls()'s
    # authority-validated read-back both build their pattern from this
    # constant — neither hand-copies the shape, so the two can never
    # silently diverge.
    _SHA_SHAPE: str = r"[0-9a-fA-F]{7,40}"

    # Every candidate install.sh URL in free-form text (a README, an
    # installCommand string). Matches http OR https, case-insensitively —
    # curl fetches HTTPS://, Https://, and http://, all just as readily as
    # https://, and a candidate filter that misses them lets that URL
    # evade classification entirely (no check at all, worse than
    # "untrusted"). Classification, not this filter, decides trust:
    # each candidate is handed to urlparse() (which normalizes scheme to
    # lowercase) and its authority validated, rather than trusting a bare
    # substring/regex match that can appear inside an attacker host's PATH.
    _INSTALL_URL_CANDIDATE = re.compile(r"https?://\S+/install\.sh", re.IGNORECASE)

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        return self

    @staticmethod
    def _url_prefix(owner: str, repo_name: str) -> str:
        """The regex prefix common to every install URL for this repo.

        ``raw.githubusercontent.com/<owner>/<repo>/`` — everything before the
        SHA-or-tag segment. Used by ``bump()``'s two substitutions, which
        rewrite this project's OWN already-trusted README content, so a
        plain regex prefix is sufficient there. ``classify_install_urls()``
        (the read-back used for verification) does NOT build from this
        prefix — a bare substring/regex match on the trusted host string
        can appear inside an attacker host's PATH (see its docstring), so
        verification parses each candidate URL with ``urlparse`` and checks
        its authority instead.
        """
        esc_owner = re.escape(owner)
        esc_repo = re.escape(repo_name)
        return rf"raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/"

    @classmethod
    def classify_install_urls(
        cls,
        content: str,
        owner: str,
        repo_name: str,
        *,
        require_owner: bool = True,
    ) -> tuple[list[str], bool]:
        """Classify every install.sh URL in ``content`` as trusted or not.

        Returns ``(trusted_shas, has_untrusted)``.

        A candidate is TRUSTED only when its full prefix genuinely resolves
        to ``https://raw.githubusercontent.com/<owner>/<repo>/`` — each
        candidate is parsed with ``urllib.parse.urlparse`` (which
        normalizes scheme case, so ``HTTPS://`` and ``https://`` are
        equivalent) and accepted only when ``scheme == "https"`` and
        ``hostname == "raw.githubusercontent.com"`` EXACTLY (not
        ``endswith``, which would accept the attacker host
        ``raw.githubusercontent.com.evil.com``), with the PATH additionally
        required to start with ``/<owner>/<repo>/``. A bare substring/regex
        match on the trusted host string is not enough:
        ``https://evil.example/raw.githubusercontent.com/<owner>/<repo>/
        <sha>/install.sh`` carries the trusted string inside an attacker
        host's PATH, and curl would download from evil.example, not GitHub.

        A trusted candidate whose final path segment is SHA-shaped is a
        trusted SHA, collected into ``trusted_shas`` for the caller to
        verify currency against. A trusted candidate whose final segment is
        NOT SHA-shaped (a version tag or branch) is tolerated with no
        further check — that shape is not a SHA pin and has nothing to go
        stale, but the host/owner/repo prefix has still been validated.

        A candidate whose prefix is NOT trusted (wrong scheme, wrong host,
        or the right host with the wrong owner/repo) sets ``has_untrusted``
        — independently of whether any trusted pin was also found, and
        regardless of whether the untrusted candidate's final segment is
        SHA-shaped or a version tag/branch. A SHA-pin-to-version-tag
        downgrade onto an untrusted host must fail exactly like an
        untrusted SHA does — checking only SHA-shaped untrusted URLs would
        let a downgraded pin evade the check entirely by no longer looking
        like a SHA. This only fires when the candidate "references this
        project": the path contains ``/<owner>/<repo>/`` when
        ``require_owner`` is True (the README's own install lines always
        embed both), or just ``/<repo_name>/`` when ``require_owner`` is
        False (a website ``installCommand`` embeds only the project slug,
        not necessarily the owner). A candidate that does not reference
        this project at all — some unrelated tool's install.sh URL — is
        ignored.
        """
        esc_owner = re.escape(owner)
        esc_repo = re.escape(repo_name)
        trusted_prefix = re.compile(rf"^/{esc_owner}/{esc_repo}/")
        trusted_sha_path = re.compile(
            rf"^/{esc_owner}/{esc_repo}/({cls._SHA_SHAPE})/install\.sh$"
        )
        reference_pattern = (
            re.compile(rf"/{esc_owner}/{esc_repo}/")
            if require_owner
            else re.compile(rf"/{esc_repo}/")
        )
        trusted_shas: list[str] = []
        has_untrusted = False
        candidates = cast("list[str]", cls._INSTALL_URL_CANDIDATE.findall(content))
        for candidate in candidates:
            parsed = urlparse(candidate)
            is_trusted_prefix = (
                parsed.scheme == "https"
                and parsed.hostname == "raw.githubusercontent.com"
                and trusted_prefix.match(parsed.path) is not None
            )
            if is_trusted_prefix:
                sha_match = trusted_sha_path.match(parsed.path)
                if sha_match is not None:
                    trusted_shas.append(sha_match.group(1))
            elif reference_pattern.search(parsed.path):
                has_untrusted = True
        return trusted_shas, has_untrusted

    @classmethod
    def find_pinned_shas(cls, content: str, owner: str, repo_name: str) -> list[str]:
        """Return every trusted, SHA-pinned install.sh URL's commit SHA.

        Thin wrapper over ``classify_install_urls()`` — catches every pin
        in a README with several separate install snippets (curl | bash,
        curl -o, --no-plugin variants, ...) rather than just the first.
        """
        trusted_shas, _ = cls.classify_install_urls(content, owner, repo_name)
        return trusted_shas

    def bump(
        self,
        version: str,
        *,
        dry_run: bool,
        resolve_repo: Callable[[Path], str | None],
    ) -> None:
        """Update SHA-pinned install.sh URLs in README to the install.sh commit.

        ``resolve_repo`` is injected rather than composing ``GithubRepo``
        directly — ``test_readme_sha_pin_survives_tag`` monkeypatches
        ``punt_kit.release._get_github_repo`` and calls
        ``punt_kit.release._land_readme_sha_pin``/``_bump_readme_install_sha``
        expecting the patch to be observed (§0's mechanism).
        """
        root = self._info.root
        readme_path = root / "README.md"
        install_sh = root / "install.sh"
        if not readme_path.exists() or not install_sh.exists():
            return

        tag = f"v{version}"
        github_repo = resolve_repo(root)
        if github_repo:
            owner, repo_name = github_repo.split("/", 1)
        else:
            owner, repo_name = "punt-labs", root.name

        # Get the short SHA of the commit that last modified install.sh
        short_sha = (
            "<SHA>"
            if dry_run
            else ReleaseProject(self._info, ops=self._ops).install_sh_sha()
        )

        content = readme_path.read_text(encoding="utf-8")
        prefix = self._url_prefix(owner, repo_name)

        # Replace SHA-pinned install URLs: <owner>/<repo>/<hex-sha>/install.sh
        new_content = re.sub(
            rf"({prefix}){self._SHA_SHAPE}(/install\.sh)",
            rf"\g<1>{short_sha}\2",
            content,
        )

        # Also replace version-tag install URLs: <owner>/<repo>/v1.2.3/install.sh
        new_content = re.sub(
            rf"({prefix})v[0-9]+\.[0-9]+\.[0-9]+(/install\.sh)",
            rf"\g<1>{short_sha}\2",
            new_content,
        )

        if new_content == content:
            return

        if dry_run:
            self._ops.dry(f"README.md: install URLs → {short_sha} ({tag})")
            return

        readme_path.write_text(new_content, encoding="utf-8")
        self._ops.ok(f"README.md: install URLs → {short_sha} ({tag})")

    def land(
        self,
        version: str,
        *,
        dry_run: bool,
        merge: Callable[..., str],
        resolve_repo: Callable[[Path], str | None],
    ) -> None:
        """Pin README's install-URL SHA via its own PR, right after the squash-merge.

        Must run after the release PR's squash-merge lands on main, not
        during the version-bump phase on the release branch. ``gh pr merge
        --squash --delete-branch`` makes one new commit on main and deletes
        the release branch — any SHA pinned from a commit that only ever
        existed on that branch becomes unreachable the moment it is
        deleted, and a subsequent CI checkout of the release tag will not
        contain it. Reading ``install.sh``'s SHA here, with the working
        tree on the just-merged main, pins a commit that is main's own
        permanent history.

        ``merge`` is injected rather than composing ``PrMerger`` directly —
        tests monkeypatch ``punt_kit.release._pr_merge`` and call
        ``punt_kit.release._land_readme_sha_pin`` expecting the patch to be
        observed (§0's mechanism, same reasoning as ``PrMerger.merge``'s
        injected ``wait_for_checks``/``resolve_threads``).
        """
        root = self._info.root
        branch = f"release-readme-pin/v{version}"

        # No README or no install.sh means there is nothing to pin — the
        # subsequent bump() would be a no-op. Skip the whole branch/checkout/
        # PR dance rather than churn git and print a misleading "README
        # already pins..." line for a repo where pinning is not even
        # possible.
        if not (root / "README.md").exists() or not (root / "install.sh").exists():
            self._ops.ok("No README.md or install.sh — nothing to pin")
            return

        if dry_run:
            self._ops.dry("bump(...)")
            self._ops.dry(
                f'git commit -m "chore: update README install SHA to v{version}"'
            )
            self._ops.dry(
                f"merge(branch={branch}, "
                f'title="chore: update README install SHA v{version}")'
            )
            return

        workspace = GitWorkspace(root, ops=self._ops)
        workspace.ensure_on_main()

        if workspace.checkout_or_create(branch):
            self._ops.info(f"Checked out existing branch {branch}")

        self.bump(version, dry_run=False, resolve_repo=resolve_repo)
        status = self._ops.run(
            ["git", "status", "--porcelain", "--", "README.md"], cwd=str(root)
        ).stdout.strip()
        if not status:
            # Resume case: a prior run already committed the pin on this
            # branch, or the README already carried the correct SHA —
            # either way there is nothing new to land.
            ahead = self._ops.run(
                ["git", "log", "main..HEAD", "--oneline"], cwd=str(root)
            ).stdout.strip()
            if not ahead:
                # Hook-firing checkout + local branch delete — same
                # diagnosed convention as Phase 9's identical cleanup path
                # (pkit-f85t.7 round 2).
                checkout = self._ops.run(
                    ["git", "checkout", "main"],
                    cwd=str(root),
                    check=False,
                    timeout=GIT_HOOK,
                )
                if checkout.returncode != 0:
                    self._ops.fail(
                        f"git checkout main failed:\n{checkout.stderr.strip()}"
                    )
                delete = self._ops.run(
                    ["git", "branch", "-D", branch], cwd=str(root), check=False
                )
                if delete.returncode != 0:
                    self._ops.fail(
                        f"git branch -D {branch} failed:\n{delete.stderr.strip()}"
                    )
                self._ops.ok("README already pins the current install SHA")
                return
        else:
            workspace.commit_if_staged(
                ["README.md"], f"chore: update README install SHA to v{version}"
            )

        merge(
            cwd=root,
            branch=branch,
            title=f"chore: update README install SHA v{version}",
            dry_run=False,
        )
        self._ops.ok("README SHA pin PR merged")
