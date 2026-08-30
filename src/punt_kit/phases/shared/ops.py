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

if TYPE_CHECKING:
    import subprocess

# The metadata-call default budget. Kept in sync with, but independent of,
# release.py's own _DEFAULT_RUN_TIMEOUT — the Protocol needs a default so
# `self._ops.run(cmd)` type-checks without an explicit timeout; the real
# default resolution happens inside release.py's `_run`.
_DEFAULT_RUN_TIMEOUT = 60


@runtime_checkable
class ReleaseOps(Protocol):
    """Subprocess execution and console reporting, as an injectable seam."""

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...

    def ok(self, msg: str) -> None: ...

    def info(self, msg: str) -> None: ...

    def dry(self, msg: str) -> None: ...

    def warn(self, msg: str) -> None: ...

    def fail(self, msg: str) -> NoReturn: ...
