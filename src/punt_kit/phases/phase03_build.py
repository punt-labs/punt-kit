"""Validate build artifacts before publishing."""

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
    """Validate build artifacts before publishing."""

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
        """Create the phase with its release inputs and operations."""
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        self._skips = skips
        return self

    def run(self) -> None:
        """Validate build artifacts before publishing.

        Skip non-Python projects. Check the wheel version before phase 4 merges.

        Raises:
            ReleaseError: Building, artifact validation, or wheel-version verification
                fails.
            subprocess.TimeoutExpired: An external command exceeds its timeout.
            OSError: Cleaning dist or reading build artifacts fails.
        """
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
