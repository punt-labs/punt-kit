"""A project's per-user daemon service: find it, restart it, prove it was replaced."""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, cast, final

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

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

    @property
    def is_declared(self) -> bool:
        """True when the project names a service under at least one manager."""
        return self.systemd is not None or self.launchd is not None

    @classmethod
    def for_project(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        """The service the project declares in ``pyproject.toml``, else none::

            [tool.punt-kit.release.service]
            systemd = "quarry"
            launchd = "com.punt-labs.quarry"

        Only a declaration names a service: guessing one from the CLI name
        could restart a daemon the project never registered. A declaration
        that is present but unusable (not a table, a non-string name, or no
        name at all) fails: it must not silently degrade to "no service".
        A mistyped parent key is indistinguishable from no declaration.
        """
        table: dict[str, object] = info.pyproject or {}
        for key in ("tool", "punt-kit", "release"):
            child = table.get(key)
            if not isinstance(child, dict):
                return cls()
            table = cast("dict[str, object]", child)
        if "service" not in table:
            return cls()
        declared = table["service"]
        if not isinstance(declared, dict):
            ops.fail(
                "[tool.punt-kit.release.service] in pyproject.toml must be a table "
                f"of strings, got {type(declared).__name__}"
            )
        names = cast("dict[str, object]", declared)
        for manager in ("systemd", "launchd"):
            if manager in names and not isinstance(names[manager], str):
                ops.fail(
                    f"[tool.punt-kit.release.service] {manager} must be a string, "
                    f"got {names[manager]!r}"
                )
        systemd, launchd = names.get("systemd"), names.get("launchd")
        spec = cls(
            systemd=systemd if isinstance(systemd, str) else None,
            launchd=launchd if isinstance(launchd, str) else None,
        )
        if not spec.is_declared:
            ops.fail(
                "[tool.punt-kit.release.service] in pyproject.toml names no "
                "service: set systemd and/or launchd"
            )
        return spec


@final
class UserService:
    """Restarts a project's user service and confirms the process was replaced."""

    __slots__ = ("_ops", "_skips", "_spec")

    _spec: ServiceSpec
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, spec: ServiceSpec, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._ops = ops
        self._skips = skips
        return self

    def restart(self) -> None:
        """Restart the declared service; fail unless its PID changed.

        Nothing declared is a no-op. A declared service whose manager cannot
        be queried fails the phase. One the host simply has not loaded is
        recorded as a manual-action skip: the release was verified, but not
        against a restarted daemon. A daemon started before the install keeps
        the old code in memory, so an unchanged PID means the release was
        verified against the wrong process.
        """
        if not self._spec.is_declared:
            self._ops.info("No user service declared — nothing to restart")
            return
        manager = self._manager()
        name = self._spec.systemd if manager == "systemd" else self._spec.launchd
        if name is None or not self._is_loaded(manager, name):
            self._skips.record(
                "SKIPPED — manual action required: declared service "
                f"{name or self._declared_name()} is not loaded on this host; "
                "release verified without a restart"
            )
            return
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

    def _declared_name(self) -> str:
        return self._spec.systemd or self._spec.launchd or ""

    def _manager(self) -> Manager:
        """The manager to use: declared AND present; the native one if both are."""
        available: list[Manager] = []
        if self._spec.systemd is not None and shutil.which("systemctl"):
            available.append("systemd")
        if self._spec.launchd is not None and shutil.which("launchctl"):
            available.append("launchd")
        if not available:
            self._ops.fail(
                f"service {self._declared_name()} is declared but its manager "
                "(systemctl for systemd, launchctl for launchd) is not available "
                "to restart it"
            )
        native: Manager = "launchd" if sys.platform == "darwin" else "systemd"
        return native if native in available else available[0]

    def _is_loaded(self, manager: Manager, name: str) -> bool:
        """Whether the manager has ``name`` loaded; a failed query fails the phase."""
        if manager == "systemd":
            shown = self._ops.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    name,
                    "--property=LoadState",
                    "--value",
                ],
                check=False,
            )
            if shown.returncode != 0:
                self._ops.fail(
                    f"Cannot query the systemd service {name} (is the user session "
                    f"bus available?): {shown.stderr.strip()}"
                )
            return shown.stdout.strip() == "loaded"
        printed = self._ops.run(
            ["launchctl", "print", self._launchd_target(name)], check=False
        )
        if printed.returncode == 0:
            return True
        detail = f"{printed.stdout}\n{printed.stderr}"
        if "could not find service" in detail.lower():
            return False
        self._ops.fail(
            f"Cannot query the launchd service {name}: {printed.stderr.strip()}"
        )

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
