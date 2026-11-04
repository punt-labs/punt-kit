"""Phase 8: verify the just-published version installs from PyPI, then
restore the editable dev install."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.install_constraints import (
    CONSTRAINTS_FILENAME,
    InstallConstraints,
)
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import CLI_DOCTOR, UV
from punt_kit.phases.shared.user_service import ServiceSpec, UserService

if TYPE_CHECKING:
    from collections.abc import Sequence

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

        constraints = InstallConstraints(info.root, f"v{version}", ops=ops).text()

        if dry_run:
            pinned = "--constraints " if constraints is not None else ""
            ops.dry(
                f"uv tool install --force --refresh {pinned}{package_name}=={version}"
            )
            if constraints is None:
                ops.dry(f"{CONSTRAINTS_FILENAME} absent at v{version}: unpinned")
            ops.dry("restart the project's user service, confirm the PID changed")
            if info.cli_commands:
                ops.dry(f"{info.cli_commands[0]} doctor (if available)")
            ops.dry("uv tool install --force --editable .")
            return

        if constraints is None:
            ops.info(
                f"No {CONSTRAINTS_FILENAME} at v{version} — installing unpinned "
                "(the project's lock is not applied)"
            )
        else:
            ops.info(f"Installing with {CONSTRAINTS_FILENAME} from v{version}")
        ops.info(f"Installing {package_name}=={version} from PyPI...")

        with tempfile.TemporaryDirectory(prefix="punt-constraints-") as scratch:
            flags: Sequence[str] = ()
            if constraints is not None:
                pins = Path(scratch) / CONSTRAINTS_FILENAME
                pins.write_text(constraints, encoding="utf-8")
                flags = ("--constraints", str(pins))
            self._install_with_retries(package_name, flags)

        ops.ok(f"Installed {package_name}=={version} from PyPI")

        UserService(ServiceSpec.for_project(info), ops=ops).restart()

        self._run_doctor()

        # Restore editable install. Convention for external commands: run with
        # check=False, and turn a non-zero exit into a diagnosed fail.
        ops.info("Restoring editable install...")
        restore_result = ops.run(
            ["uv", "tool", "install", "--force", "--editable", "."],
            cwd=str(info.root),
            capture=False,
            check=False,
            timeout=UV,
        )
        if restore_result.returncode != 0:
            ops.fail("uv tool install --editable . failed — see output above")
        ops.ok("Editable install restored")

    def _install_with_retries(self, package_name: str, flags: Sequence[str]) -> None:
        """Install ``package_name==version`` from PyPI, riding out propagation lag."""
        ops = self._ops
        for attempt in range(10):
            result = ops.run(
                [
                    "uv",
                    "tool",
                    "install",
                    "--force",
                    "--refresh",
                    *flags,
                    f"{package_name}=={self._version}",
                ],
                cwd=str(self._info.root),
                check=False,
                capture=False,
                timeout=UV,
            )
            if result.returncode == 0:
                return
            if attempt < 9:
                ops.info(
                    f"Attempt {attempt + 1}/10 — waiting 30s for PyPI propagation..."
                )
                time.sleep(30)
        ops.fail(
            f"Failed to install {package_name}=={self._version} from PyPI after "
            "10 attempts"
        )

    def _run_doctor(self) -> None:
        """Run the freshly installed CLI's ``doctor``, if it has one.

        Informational only, and the release has already published: a hung
        doctor is a warning, not an abort.
        """
        info = self._info
        if not info.cli_commands:
            return
        cli_name = info.cli_commands[0]
        cli_path = shutil.which(cli_name)
        if not cli_path:
            return
        try:
            result = self._ops.run(
                [cli_path, "doctor"],
                check=False,
                capture=False,
                timeout=CLI_DOCTOR,
            )
        except subprocess.TimeoutExpired:
            self._ops.warn(f"{cli_name} doctor did not finish in {CLI_DOCTOR}s")
            return
        if result.returncode == 0:
            self._ops.ok(f"{cli_name} doctor passed")
        else:
            self._ops.warn(
                f"{cli_name} doctor exited {result.returncode} — see output above"
            )
