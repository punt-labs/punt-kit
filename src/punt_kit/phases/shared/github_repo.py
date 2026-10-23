"""A project's GitHub repository: slug resolution and branch governance probes."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.repo_slug import RepoSlug

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class GithubRepo:
    """A project's GitHub repository, resolved from its git remote."""

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def resolve(self) -> str | None:
        """The remote's clean ``owner/repo`` text; ``None`` if unresolvable."""
        slug = self.resolve_slug()
        return None if slug is None else str(slug)

    def resolve_slug(self) -> RepoSlug | None:
        """The remote's parsed slug; ``None`` if unresolvable or malformed.

        Every consumer that needs a slug comes through here (or ``slug``), so
        none of them re-normalizes. Use ``slug`` to tell a malformed remote
        from an absent one.
        """
        try:
            return self.slug()
        except ValueError:
            return None

    def slug(self) -> RepoSlug | None:
        """The parsed slug of the ``origin`` remote.

        ``None`` when the remote is absent or not on github.com. Raises
        ``ValueError`` when the remote names github.com but its path is not
        ``owner/repo``.
        """
        try:
            result = self._ops.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(self._root),
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0:
            return None
        return RepoSlug.from_remote_url(result.stdout)

    def has_branch_protection(self, gh: str, owner: str, repo_name: str) -> bool:
        """True if ``main`` has a branch protection rule.

        ``gh api .../branches/main/protection`` returns HTTP 404 with the
        message body ``"Branch not protected"`` when no protection rule is
        configured. The SAME endpoint also 404s when the token lacks
        ``admin:repo`` permissions on a repo that DOES have protection —
        with a different error message (typically ``"Not Found"`` or an
        HTTP-401 that gh surfaces as 404). Distinguishing the two requires
        the explicit ``"branch not protected"`` marker: any 404 without
        that marker is ambiguous and falls through as protected=True, along
        with every other failure mode (network, rate limit, timeout, wrong
        scope). Fail-safe direction: the isRequired-only wait behavior is
        preserved for anything we cannot confirm is genuinely unprotected.
        """
        try:
            result = self._ops.run(
                [gh, "api", f"repos/{owner}/{repo_name}/branches/main/protection"],
                cwd=str(self._root),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return True
        if result.returncode == 0:
            return True
        combined = (result.stderr + result.stdout).lower()
        return "branch not protected" not in combined

    def has_ruleset(self, gh: str, owner: str, repo_name: str) -> bool:
        """True if a GitHub ruleset (not the legacy branch-protection API)
        governs ``main``.

        ``gh api repos/{owner}/{repo}/rules/branches/main`` returns the list
        of *active* rules for the branch — a JSON array, empty when no
        ruleset targets it. This is a distinct mechanism from classic branch
        protection: a repo can be fully governed (required status checks,
        required conversation resolution) by a ruleset while
        ``has_branch_protection`` reports "branch not protected", because
        the legacy endpoint only ever sees the legacy feature. ``ethos``
        governs ``main`` this way — 2 required status checks plus
        conversation resolution, entirely via rulesets.

        Fail-safe direction matches ``has_branch_protection``: any failure
        to positively confirm a ruleset (timeout, non-zero exit, unparsable
        body) reports ``False`` rather than risk suppressing the "no branch
        protection" warning on a repo that turns out to be genuinely
        unprotected.
        """
        try:
            result = self._ops.run(
                [gh, "api", f"repos/{owner}/{repo_name}/rules/branches/main"],
                cwd=str(self._root),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0:
            return False
        try:
            rules = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        return isinstance(rules, list) and len(cast("list[object]", rules)) > 0
