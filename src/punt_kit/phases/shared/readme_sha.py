"""Pinning README's install-URL SHA to the commit that last touched
install.sh, and landing that pin via its own PR right after the release
squash-merge lands on main."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

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

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        return self

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
        esc_owner = re.escape(owner)
        esc_repo = re.escape(repo_name)

        # Replace SHA-pinned install URLs: <owner>/<repo>/<hex-sha>/install.sh
        new_content = re.sub(
            rf"(raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/)"
            r"[0-9a-fA-F]{7,40}(/install\.sh)",
            rf"\g<1>{short_sha}\2",
            content,
        )

        # Also replace version-tag install URLs: <owner>/<repo>/v1.2.3/install.sh
        new_content = re.sub(
            rf"(raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/)"
            r"v[0-9]+\.[0-9]+\.[0-9]+(/install\.sh)",
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
                self._ops.run(
                    ["git", "checkout", "main"], cwd=str(root), timeout=GIT_HOOK
                )
                self._ops.run(["git", "branch", "-D", branch], cwd=str(root))
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
