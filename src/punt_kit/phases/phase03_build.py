"""Phase 3: build validation — `uv build` plus a twine check on the
resulting artifacts."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase3Build:
    """Phase 3: build validation."""

    __slots__ = ("_dry_run", "_info", "_ops")

    _info: ProjectInfo
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, dry_run: bool, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._dry_run = dry_run
        self._ops = ops
        return self

    def run(self) -> None:
        info = self._info
        ops = self._ops
        if info.language != "python":
            return

        _console.print("\n[bold]Phase 3: Build validation[/bold]")

        if self._dry_run:
            ops.dry("rm -rf dist/ && uv build && uvx twine check dist/*")
            return

        dist = info.root / "dist"
        if dist.exists():
            shutil.rmtree(dist)

        ops.run(["uv", "build"], cwd=str(info.root), capture=False, timeout=UV)

        # twine check on built artifacts only (.whl and .tar.gz)
        dist_dir = info.root / "dist"
        artifacts = sorted(p for p in dist_dir.iterdir() if p.suffix in {".whl", ".gz"})
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
