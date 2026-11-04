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

from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.release_tag_file import (
    CONSTRAINTS_FILENAME,
    OVERRIDES_FILENAME,
    ReleaseTagFile,
)
from punt_kit.phases.shared.timeouts import CLI_DOCTOR, UV
from punt_kit.phases.shared.user_service import ServiceSpec, UserService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

_console = Console()

# The uv flag each optional install-pin file feeds.
_PIN_FLAGS = {
    CONSTRAINTS_FILENAME: "--constraints",
    OVERRIDES_FILENAME: "--overrides",
}


@final
class Phase8VerifyPypi:
    """Phase 8: verify PyPI install."""

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
        version = self._version
        ops = self._ops
        if info.language != "python":
            return

        _console.print("\n[bold]Phase 8: Verify PyPI install[/bold]")

        package_name = ReleaseProject(info, ops=ops).package_name()

        if self._dry_run:
            self._dry_run_plan(package_name)
            return

        pins: dict[str, str] = {}
        for filename in _PIN_FLAGS:
            text = ReleaseTagFile(info.root, f"v{version}", filename, ops=ops).text()
            if text is not None:
                pins[filename] = text
                ops.info(f"Installing with {filename} from v{version}")
        if CONSTRAINTS_FILENAME not in pins:
            ops.info(
                f"No {CONSTRAINTS_FILENAME} at v{version} — installing unpinned "
                "(the project's lock is not applied)"
            )

        # The editable install is the operator's dev environment. Whatever
        # happens from the first PyPI install on, it is put back.
        primary: BaseException | None = None
        try:
            self._verify_published(package_name, pins)
        except BaseException as exc:
            primary = exc
            raise
        finally:
            self._restore_editable(primary)

    def _dry_run_plan(self, package_name: str) -> None:
        info = self._info
        ops = self._ops
        tag = f"v{self._version}"
        flags = ""
        for filename, flag in _PIN_FLAGS.items():
            if (info.root / filename).exists():
                flags += f"{flag} <{filename} from {tag}> "
            else:
                ops.dry(f"would read {filename} from {tag}; used if present")
        pinned = flags
        ops.dry(
            f"uv tool install --force --refresh {pinned}{package_name}=={self._version}"
        )
        ops.dry("restart the project's declared user service, confirm the PID changed")
        if info.cli_commands:
            ops.dry(f"{info.cli_commands[0]} doctor (if available)")
        ops.dry("uv tool install --force --editable .")

    def _verify_published(self, package_name: str, pins: dict[str, str]) -> None:
        ops = self._ops
        ops.info(f"Installing {package_name}=={self._version} from PyPI...")

        with tempfile.TemporaryDirectory(prefix="punt-pins-") as scratch:
            flags: list[str] = []
            for filename, text in pins.items():
                path = Path(scratch) / filename
                path.write_text(text, encoding="utf-8")
                flags += [_PIN_FLAGS[filename], str(path)]
            self._install_with_retries(package_name, flags)

        ops.ok(f"Installed {package_name}=={self._version} from PyPI")

        spec = ServiceSpec.for_project(self._info, ops=ops)
        UserService(spec, ops=ops, skips=self._skips).restart()

        self._run_doctor()

    def _restore_editable(self, primary: BaseException | None) -> None:
        """Put the editable install back; never mask the error already in flight.

        Convention for external commands: run with check=False, and turn a
        non-zero exit into a diagnosed fail. With another error in flight the
        restore failure is reported as secondary instead, so the operator
        sees the original cause.
        """
        ops = self._ops
        ops.info("Restoring editable install...")
        failure = "uv tool install --editable . failed — see output above"
        try:
            result = ops.run(
                ["uv", "tool", "install", "--force", "--editable", "."],
                cwd=str(self._info.root),
                capture=False,
                check=False,
                timeout=UV,
            )
        except subprocess.TimeoutExpired:
            if primary is None:
                raise
            ops.error(f"{failure} (timed out) after {primary!r}")
            return
        if result.returncode != 0:
            if primary is not None:
                ops.error(f"{failure} (secondary to: {primary})")
                return
            ops.fail(failure)
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
