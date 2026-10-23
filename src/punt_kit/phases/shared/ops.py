"""The primitives every release phase and shared collaborator needs.

``ReleaseOps`` is a structural interface, not a shared implementation — every
phase and shared class receives one at construction and calls ``self._ops.*``
instead of a bare module-level helper. The concrete implementation
(``_ReleaseOpsAdapter``) lives in ``punt_kit.release`` itself, so that
``monkeypatch.setattr(release_mod, "_run", ...)`` reaches every collaborator
built on top of it — see ``punt_kit.release`` for the mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn, Protocol, runtime_checkable

from punt_kit.phases.shared.timeouts import DEFAULT_RUN

if TYPE_CHECKING:
    import subprocess


@runtime_checkable
class ReleaseOps(Protocol):
    """Subprocess execution and console reporting, as an injectable seam.

    ``run``'s ``check`` default of ``True`` is deliberately caller-set, not
    changed here — individual call sites opt into ``check=False`` plus a
    diagnosed ``fail(...)`` message, rather than flipping the shared
    default, because a silently-flipped default would hide which sites were
    actually reviewed. The convention's boundary: a call site opts in when
    it can plausibly fail *operationally* — a network op
    (fetch/push/pull/ls-remote), an external tool (uv, gh, a
    release/restore script), a hook-firing mutation (checkout, commit,
    branch delete), or a read against a sibling repo (a checkout this
    process does not fully control). A call site is left at ``check=True``
    when it is a local, read-only metadata query (``git branch
    --show-current``, ``status --porcelain``, ``rev-parse``, ``tag
    --list``, ``log``, ``diff --cached``, ``show``) or a local index-stage
    (``git add``) against the *project's own* repo, whose cleanliness an
    earlier phase (or, for a sibling, that sibling's own ``validate()``)
    already established — a failure there indicates the repo itself is
    corrupt beyond any single call's control, not an independent
    operational failure mode the diagnosis convention targets.
    """

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...

    def ok(self, msg: str) -> None: ...

    def info(self, msg: str) -> None: ...

    def dry(self, msg: str) -> None: ...

    def warn(self, msg: str) -> None: ...

    def fail(self, msg: str) -> NoReturn: ...
