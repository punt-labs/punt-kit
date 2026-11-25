"""Set up the installed punt binary's user-level Claude Code integration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Self, cast

from punt_kit.phases.shared.errors import ReleaseError

_MARKETPLACE = "punt-labs"
_SOURCE = "punt-labs/claude-plugins"
_PLUGIN = "punt@punt-labs"


@dataclass(frozen=True, slots=True)
class InstallReport:
    """Report completed setup operations and any failure."""

    changes: tuple[str, ...]
    error: str = ""


class PluginInstaller:
    """Manage Punt's user-level Claude Code plugin installation."""

    _binary: str

    def __new__(cls, binary: str) -> Self:
        """Bind the Claude Code executable for this installation."""
        self = super().__new__(cls)
        self._binary = binary
        return self

    @staticmethod
    def _marketplace_git_env() -> dict[str, str]:
        """Use HTTPS for the public marketplace without changing Git configuration."""
        env = os.environ.copy()
        try:
            index = int(env.get("GIT_CONFIG_COUNT", "0"))
        except ValueError as exc:
            raise ReleaseError(
                "Invalid GIT_CONFIG_COUNT; check the Git environment"
            ) from exc
        env[f"GIT_CONFIG_KEY_{index}"] = "url.https://github.com/punt-labs/.insteadOf"
        env[f"GIT_CONFIG_VALUE_{index}"] = "git@github.com:punt-labs/"
        env["GIT_CONFIG_COUNT"] = str(index + 1)
        return env

    def _claude(self, *args: str) -> str:
        """Run a non-interactive Claude plugin operation."""
        try:
            result = subprocess.run(
                [self._binary, "plugin", *args],
                env=self._marketplace_git_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReleaseError(
                f"Claude Code plugin {' '.join(args)} timed out after 120 seconds"
            ) from exc
        except OSError as exc:
            raise ReleaseError(
                f"Claude Code could not run plugin {' '.join(args)}: {exc.strerror}"
            ) from exc
        if result.returncode:
            raise ReleaseError(
                f"Claude Code plugin {' '.join(args)} failed (exit {result.returncode})"
                "; run that command directly for Claude's diagnostics"
            )
        try:
            return result.stdout.decode()
        except UnicodeDecodeError as exc:
            raise ReleaseError(
                f"Claude Code returned invalid UTF-8 for plugin {' '.join(args)}"
            ) from exc

    def _entries(self, *args: str) -> list[dict[str, object]]:
        """Read the JSON list from a Claude discovery command."""
        try:
            raw: object = json.loads(self._claude(*args, "--json"))
            if isinstance(raw, list) and all(
                isinstance(entry, dict) for entry in cast("list[object]", raw)
            ):
                return cast("list[dict[str, object]]", raw)
        except json.JSONDecodeError:
            pass
        raise ReleaseError(
            f"Claude Code returned invalid JSON for plugin {' '.join(args)}"
        )

    def _plugin_installed(self) -> bool:
        return any(
            entry.get("id") == _PLUGIN and entry.get("scope") == "user"
            for entry in self._entries("list")
        )

    def run(self) -> InstallReport:
        """Ensure punt is registered in Claude Code at user scope.

        Returns:
            Changes made, in execution order. Refresh and update an existing
            user plugin without reinstalling the punt binary or touching other scopes.
        """
        marketplace = self._ensure_marketplace()
        try:
            plugin = self._ensure_plugin()
        except ReleaseError as exc:
            return InstallReport((marketplace,), str(exc))
        return InstallReport((marketplace, plugin))

    def _ensure_marketplace(self) -> str:
        marketplace = next(
            (
                entry
                for entry in self._entries("marketplace", "list")
                if entry.get("name") == _MARKETPLACE
            ),
            None,
        )
        if marketplace is not None:
            if (marketplace.get("source"), marketplace.get("repo")) != (
                "github",
                _SOURCE,
            ):
                raise ReleaseError(
                    f"The {_MARKETPLACE} marketplace is not registered from {_SOURCE}"
                    "; check 'claude plugin marketplace list --json'"
                )
            self._claude("marketplace", "update", _MARKETPLACE)
            return f"Refreshed the {_MARKETPLACE} marketplace"
        self._claude("marketplace", "add", _SOURCE)
        return f"Registered the {_MARKETPLACE} marketplace"

    def _ensure_plugin(self) -> str:
        action = "update" if self._plugin_installed() else "install"
        self._claude(action, _PLUGIN, "--scope", "user")
        if not self._plugin_installed():
            raise ReleaseError(
                f"Claude Code did not report {_PLUGIN} installed at user scope"
            )
        past = "Updated" if action == "update" else "Installed"
        return f"{past} {_PLUGIN} at user scope"


def run_install() -> InstallReport:
    """Find Claude Code and configure Punt at user scope."""
    binary = shutil.which("claude")
    if not binary:
        raise ReleaseError(
            "Claude Code is not on PATH; install it and rerun punt install"
        )
    if not shutil.which("git"):
        raise ReleaseError("git is not on PATH; install it and rerun punt install")
    return PluginInstaller(binary).run()
