"""Pinning README's install-URL SHA to the commit that last touched
install.sh, and landing that pin via its own PR right after the release
squash-merge lands on main."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.errors import RemoteLookupError
from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.install_urls import InstallUrlRecognizer
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.siblings import SkipRecorder


@dataclass(frozen=True, slots=True)
class PinResult:
    """What ``ReadmeShaPin.bump`` did, and what it could not fix."""

    changed: bool
    # One line per install pin (or reason) still not current after the bump.
    stale: tuple[str, ...]


@final
class ReadmeShaPin:
    """Keeps README's SHA-pinned install URL current with install.sh's commit."""

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

    def _skip(self, reason: str) -> PinResult:
        """Record that the README pin was not updated, and why."""
        message = f"README pin not updated: {reason}"
        self._skips.record(message)
        return PinResult(changed=False, stale=(message,))

    def _recognizer(
        self, resolve_repo: Callable[[Path], str | None]
    ) -> InstallUrlRecognizer | PinResult:
        """The recognizer for this repo, or the skip when its slug is unknown.

        No slug is guessed from the directory name: a pin recognized under a
        guessed owner would rewrite, or miss, the wrong URLs.
        """
        try:
            slug = resolve_repo(self._info.root)
            if not slug:
                return self._skip("no github.com origin remote names this repository")
            return InstallUrlRecognizer.for_slug(slug)
        except (ValueError, RemoteLookupError) as exc:
            return self._skip(str(exc))

    def bump(
        self,
        version: str,
        *,
        dry_run: bool,
        resolve_repo: Callable[[Path], str | None],
    ) -> PinResult:
        """Move README's pinned install URLs to the install.sh commit.

        The result says whether the README changed (or, for a dry run, would
        change) and which pins are still not current. Pins are recognized by
        ``InstallUrlRecognizer`` — the same definition Phase 11 verifies with
        — and the result is verified with it too: any pin it would trust
        whose SHA still differs from the new one, and any install URL for
        this repo it does not trust, is reported by URL rather than left
        stale in silence. A repository that cannot be named is a skip, not a
        guess.

        ``resolve_repo`` is injected rather than composing ``GithubRepo``
        directly, so a caller's patched resolver is observed here.
        """
        root = self._info.root
        readme_path = root / "README.md"
        if not readme_path.exists() or not (root / "install.sh").exists():
            return PinResult(changed=False, stale=())

        tag = f"v{version}"
        recognizer = self._recognizer(resolve_repo)
        if isinstance(recognizer, PinResult):
            return recognizer
        # A read-only git query, so a dry run can tell a no-op from a rewrite.
        short_sha = ReleaseProject(self._info, ops=self._ops).install_sh_sha()

        content = readme_path.read_text(encoding="utf-8")
        new_content = recognizer.repinned(content, short_sha)
        stale = self._warn_about_unrewritten_urls(recognizer, new_content, short_sha)

        if new_content == content:
            return PinResult(changed=False, stale=stale)

        if dry_run:
            self._ops.dry(f"README.md: install URLs → {short_sha} ({tag})")
            return PinResult(changed=True, stale=stale)

        readme_path.write_text(new_content, encoding="utf-8")
        self._ops.ok(f"README.md: install URLs → {short_sha} ({tag})")
        return PinResult(changed=True, stale=stale)

    def _warn_about_unrewritten_urls(
        self, recognizer: InstallUrlRecognizer, content: str, short_sha: str
    ) -> tuple[str, ...]:
        """Warn about, and return, every install URL ``content`` has that is stale."""
        slug = recognizer.slug
        stale: list[str] = []
        for ref in recognizer.scan(content):
            if not ref.is_trusted:
                stale.append(
                    f"README.md pins {slug}'s install.sh at {ref.url}, which is not "
                    f"{slug} on raw.githubusercontent.com (different owner or host) "
                    "— the install SHA pin was not updated"
                )
            elif ref.is_pin and not ref.is_pinned_to(short_sha):
                stale.append(
                    f"README.md pins {ref.url}, which is not the current install SHA "
                    f"{short_sha} and could not be rewritten in place"
                )
        for line in stale:
            self._ops.warn(line)
        return tuple(stale)

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

        ``merge`` is injected rather than composing ``PrMerger`` directly,
        so a caller's patched merger is observed here.
        """
        root = self._info.root
        branch = self._branch_name(version)

        # No README or no install.sh means there is nothing to pin — the
        # subsequent bump() would be a no-op. Skip the whole branch/checkout/
        # PR dance rather than churn git and print a misleading "README
        # already pins..." line for a repo where pinning is not even
        # possible.
        if not (root / "README.md").exists() or not (root / "install.sh").exists():
            self._ops.ok("No README.md or install.sh — nothing to pin")
            return

        if dry_run:
            self._preview_land(version, resolve_repo)
            return

        workspace = GitWorkspace(root, ops=self._ops)
        workspace.ensure_on_main()

        if workspace.checkout_or_create(branch):
            self._ops.info(f"Checked out existing branch {branch}")

        result = self.bump(version, dry_run=False, resolve_repo=resolve_repo)
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
                self._discard_branch(branch)
                self._report_nothing_to_land(result)
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
        if result.stale:
            self._warn_stale(result)

    def _report_nothing_to_land(self, result: PinResult) -> None:
        """Say the README is current only when the bump verified that."""
        if result.stale:
            self._warn_stale(result)
        else:
            self._ops.ok("README already pins the current install SHA")

    def _warn_stale(self, result: PinResult) -> None:
        self._ops.warn(
            f"README still carries {len(result.stale)} stale install pin(s) "
            "that were not updated"
        )

    @staticmethod
    def _branch_name(version: str) -> str:
        """The branch a version's README pin lands from."""
        return f"release-readme-pin/v{version}"

    def _preview_land(
        self, version: str, resolve_repo: Callable[[Path], str | None]
    ) -> None:
        """Print what ``land`` would commit and merge, or say nothing is needed."""
        result = self.bump(version, dry_run=True, resolve_repo=resolve_repo)
        if not result.changed:
            self._report_nothing_to_land(result)
            return
        self._ops.dry(f'git commit -m "chore: update README install SHA to v{version}"')
        self._ops.dry(
            f"merge(branch={self._branch_name(version)}, "
            f'title="chore: update README install SHA v{version}")'
        )

    def _discard_branch(self, branch: str) -> None:
        """Return to main and delete ``branch``, which has nothing to land.

        Hook-firing checkout + local branch delete — the same diagnosed
        convention as Phase 9's identical cleanup path.
        """
        root = str(self._info.root)
        checkout = self._ops.run(
            ["git", "checkout", "main"], cwd=root, check=False, timeout=GIT_HOOK
        )
        if checkout.returncode != 0:
            self._ops.fail(f"git checkout main failed:\n{checkout.stderr.strip()}")
        delete = self._ops.run(["git", "branch", "-D", branch], cwd=root, check=False)
        if delete.returncode != 0:
            self._ops.fail(f"git branch -D {branch} failed:\n{delete.stderr.strip()}")
