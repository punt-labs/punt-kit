"""Phase 3: build validation — `uv build`, a twine check on the resulting
artifacts, and an isolated import of the wheel to read its `__version__`."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.timeouts import UV
from punt_kit.phases.shared.wheel_version import WheelVersionCheck

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

_console = Console()


@final
class Phase3Build:
    """Phase 3: build validation.

    The last phase before anything leaves this machine: Phase 4 merges the
    release PR and Phase 5 tags it, which publishes. So the wheel's run-time
    ``__version__`` is checked here, on the artifact just built, rather than
    in Phase 11, which verifies after the fact.
    """

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
        ops = self._ops
        if info.language != "python":
            return

        _console.print("\n[bold]Phase 3: Build validation[/bold]")
        wheel_version = WheelVersionCheck(
            info, self._version, ops=ops, skips=self._skips
        )

        if self._dry_run:
            ops.dry("rm -rf dist/ && uv build && uvx twine check dist/*")
            wheel_version.dry_run()
            return

        dist = info.root / "dist"
        if dist.exists():
            shutil.rmtree(dist)

        build_result = ops.run(
            ["uv", "build"],
            cwd=str(info.root),
            capture=False,
            check=False,
            timeout=UV,
        )
        if build_result.returncode != 0:
            ops.fail("uv build failed — see output above")

        # twine check on built artifacts only (.whl and .tar.gz)
        artifacts = sorted(p for p in dist.iterdir() if p.suffix in {".whl", ".gz"})
        if not artifacts:
            ops.fail("No build artifacts found in dist/ for twine check")

        result = ops.run(
            ["uvx", "twine", "check", *[str(p) for p in artifacts]],
            cwd=str(info.root),
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            ops.fail(f"twine check failed:\n{result.stdout}\n{result.stderr}")
        ops.ok("Build artifacts pass twine check")

        wheel_version.verify(dist)
