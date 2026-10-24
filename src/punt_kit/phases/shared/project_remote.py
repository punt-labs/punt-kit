"""The project's GitHub slug under one skip-or-fail policy for propagation steps."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.errors import RemoteLookupError
from punt_kit.phases.shared.github_repo import GithubRepo

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.repo_slug import RepoSlug
    from punt_kit.phases.shared.skips import SkipRecorder


@final
class ProjectRemote:
    """Resolves the project's slug for a named step, never silently.

    These steps run after the release has published, so an absent GitHub
    remote is recorded as a skip the operator must act on; a remote that is
    malformed, or that git could not be asked about, is a failure with the
    cause in the message.
    """

    __slots__ = ("_ops", "_repo", "_skips", "_step")

    _repo: GithubRepo
    _ops: ReleaseOps
    _skips: SkipRecorder
    _step: str

    def __new__(
        cls, root: Path, *, ops: ReleaseOps, skips: SkipRecorder, step: str
    ) -> Self:
        self = super().__new__(cls)
        self._repo = GithubRepo(root, ops=ops)
        self._ops = ops
        self._skips = skips
        self._step = step
        return self

    def slug(self) -> RepoSlug | None:
        """The slug, or ``None`` after recording that the step is skipped.

        ``None`` is the documented answer for "no github.com origin": the
        caller returns, and the skip is already on the recap. Any other
        failure to name the repository raises.
        """
        try:
            slug = self._repo.slug()
        except (ValueError, RemoteLookupError) as exc:
            self._ops.fail(f"{self._step}: {exc}")
        if slug is None:
            self._skips.record(
                f"SKIPPED — manual action required: {self._step} did not run "
                "because the project has no github.com origin remote."
            )
        return slug
