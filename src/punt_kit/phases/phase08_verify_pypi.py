"""Phase 8: verify the just-published version installs from PyPI, then
restore the editable dev install."""

from __future__ import annotations

import shutil
import time
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase8VerifyPypi:
    """Phase 8: verify PyPI install."""

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls, info: ProjectInfo, version: str, *, dry_run: bool, ops: ReleaseOps
    ) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        return self

    def run(self) -> None:
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        if info.language != "python":
            return

        _console.print("\n[bold]Phase 8: Verify PyPI install[/bold]")

        package_name = ReleaseProject(info, ops=ops).package_name()

        if dry_run:
            ops.dry(f"uv tool install --force --refresh {package_name}=={version}")
            if info.cli_commands:
                ops.dry(f"{info.cli_commands[0]} doctor (if available)")
            ops.dry("uv tool install --force --editable .")
            return

        ops.info(f"Installing {package_name}=={version} from PyPI...")

        # Retry loop — PyPI propagation can take a minute
        for attempt in range(10):
            result = ops.run(
                [
                    "uv",
                    "tool",
                    "install",
                    "--force",
                    "--refresh",
                    f"{package_name}=={version}",
                ],
                cwd=str(info.root),
                check=False,
                capture=False,
                timeout=UV,
            )
            if result.returncode == 0:
                break
            if attempt < 9:
                ops.info(
                    f"Attempt {attempt + 1}/10 — waiting 30s for PyPI propagation..."
                )
                time.sleep(30)
        else:
            ops.fail(
                f"Failed to install {package_name}=={version} from PyPI after "
                "10 attempts"
            )

        ops.ok(f"Installed {package_name}=={version} from PyPI")

        # Run doctor if available
        if info.cli_commands:
            cli_name = info.cli_commands[0]
            cli_path = shutil.which(cli_name)
            if cli_path:
                doctor_result = ops.run(
                    [cli_path, "doctor"], check=False, capture=False
                )
                if doctor_result.returncode == 0:
                    ops.ok(f"{cli_name} doctor passed")

        # Restore editable install
        ops.info("Restoring editable install...")
        ops.run(
            ["uv", "tool", "install", "--force", "--editable", "."],
            cwd=str(info.root),
            capture=False,
            timeout=UV,
        )
        ops.ok("Editable install restored")
