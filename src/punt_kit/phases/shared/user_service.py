"""A project's per-user daemon service: find it, restart it, prove it was replaced."""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, cast, final

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

# kickstart and `systemctl restart` can return before the manager publishes the
# new main PID, so the PID is polled rather than read once.
_PID_POLLS = 10
_PID_POLL_SECONDS = 1

_LAUNCHD_PID = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)

type Manager = Literal["systemd", "launchd"]


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """The names a project's user service is registered under.

    ``None`` means the project does not register one with that manager.
    """

    systemd: str | None = None
    launchd: str | None = None

    @classmethod
    def for_project(cls, info: ProjectInfo) -> Self:
        """The service the project declares in ``pyproject.toml``, else none::

            [tool.punt-kit.release.service]
            systemd = "quarry"
            launchd = "com.punt-labs.quarry"

        Only a declaration names a service: guessing one from the CLI name
        could restart a daemon the project never registered.
        """
        table: dict[str, object] = info.pyproject or {}
        for key in ("tool", "punt-kit", "release", "service"):
            child = table.get(key)
            if not isinstance(child, dict):
                return cls()
            table = cast("dict[str, object]", child)
        systemd, launchd = table.get("systemd"), table.get("launchd")
        return cls(
            systemd=systemd if isinstance(systemd, str) else None,
            launchd=launchd if isinstance(launchd, str) else None,
        )


@final
class UserService:
    """Restarts a project's user service and confirms the process was replaced."""

    __slots__ = ("_ops", "_spec")

    _spec: ServiceSpec
    _ops: ReleaseOps

    def __new__(cls, spec: ServiceSpec, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._ops = ops
        return self

    def restart(self) -> None:
        """Restart the registered service; fail unless its PID changed.

        A project with no registered service is skipped. A daemon started
        before the install keeps the old code in memory, so an unchanged PID
        means the release was verified against the wrong process.
        """
        found = self._registered()
        if found is None:
            self._ops.info("No user service registered — nothing to restart")
            return
        manager, name = found
        before = self._pid(manager, name)
        self._ops.info(f"Restarting {manager} service {name} (PID {before})...")
        self._kick(manager, name)
        after = self._await_new_pid(manager, name, before)
        if after == 0:
            self._ops.fail(
                f"{name} is not running after restart — check the {manager} logs"
            )
        if after == before:
            by_hand = self._restart_cmd(manager, name)
            self._ops.fail(
                f"{name} kept PID {before} across the restart — it is still the "
                f"pre-release process; restart it by hand ({by_hand})"
            )
        self._ops.ok(f"{name} restarted (PID {before} -> {after})")

    def _registered(self) -> tuple[Manager, str] | None:
        spec = self._spec
        if shutil.which("systemctl") and spec.systemd:
            shown = self._ops.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    spec.systemd,
                    "--property=LoadState",
                    "--value",
                ],
                check=False,
            )
            if shown.returncode == 0 and shown.stdout.strip() == "loaded":
                return "systemd", spec.systemd
        elif shutil.which("launchctl") and spec.launchd:
            printed = self._ops.run(
                ["launchctl", "print", self._launchd_target(spec.launchd)],
                check=False,
            )
            if printed.returncode == 0:
                return "launchd", spec.launchd
        return None

    def _pid(self, manager: Manager, name: str) -> int:
        """The service's main PID, 0 when it is not running."""
        if manager == "systemd":
            result = self._ops.run(
                ["systemctl", "--user", "show", name, "--property=MainPID", "--value"],
                check=False,
            )
            raw = result.stdout.strip()
        else:
            result = self._ops.run(
                ["launchctl", "print", self._launchd_target(name)], check=False
            )
            match = _LAUNCHD_PID.search(result.stdout)
            raw = match.group(1) if match else "0"
        if result.returncode != 0 or not raw.isdigit():
            self._ops.fail(
                f"Cannot query the {manager} service {name}: {result.stderr.strip()}"
            )
        return int(raw)

    def _kick(self, manager: Manager, name: str) -> None:
        result = self._ops.run(
            self._restart_argv(manager, name), check=False, capture=True
        )
        if result.returncode != 0:
            self._ops.fail(
                f"Failed to restart {name}: {self._restart_cmd(manager, name)} "
                f"exited {result.returncode}: {result.stderr.strip()}"
            )

    def _await_new_pid(self, manager: Manager, name: str, before: int) -> int:
        after = 0
        for attempt in range(_PID_POLLS):
            after = self._pid(manager, name)
            if after not in (0, before):
                break
            if attempt < _PID_POLLS - 1:
                time.sleep(_PID_POLL_SECONDS)
        return after

    def _restart_argv(self, manager: Manager, name: str) -> list[str]:
        if manager == "systemd":
            return ["systemctl", "--user", "restart", name]
        return ["launchctl", "kickstart", "-k", self._launchd_target(name)]

    def _restart_cmd(self, manager: Manager, name: str) -> str:
        return " ".join(self._restart_argv(manager, name))

    @staticmethod
    def _launchd_target(label: str) -> str:
        return f"gui/{os.getuid()}/{label}"
