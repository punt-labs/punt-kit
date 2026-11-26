"""Prepare Git settings for the Claude Code marketplace checkout."""

from __future__ import annotations

import os
import subprocess
from typing import Self


class InstallError(Exception):
    """Signal that Claude Code setup did not complete."""


class MarketplaceGitEnvironment:
    """Keep inherited Git settings except command-scoped URL rewrites."""

    _inherited: dict[str, str]

    def __new__(cls) -> Self:
        """Capture environment settings for a plugin installation."""
        self = super().__new__(cls)
        self._inherited = os.environ.copy()
        return self

    def prepare(self) -> dict[str, str]:
        """Return the marketplace subprocess environment."""
        command = self._command_settings()
        env = {key: self._inherited[key] for key in self._inherited.keys() - command}
        pairs = self._git_settings(command) if command else []
        pairs = [pair for pair in pairs if not self._exclude_setting(pair[0])]
        pairs.append(
            ("url.https://github.com/punt-labs/.insteadOf", "git@github.com:punt-labs/")
        )
        for index, (key, value) in enumerate(pairs):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        env["GIT_CONFIG_COUNT"] = str(len(pairs))
        return env

    def _command_settings(self) -> dict[str, str]:
        return {
            key: self._inherited[key]
            for key in self._inherited
            if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
            or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
        }

    def _git_settings(self, command: dict[str, str]) -> list[tuple[str, str]]:
        """Expand command-scoped includes without loading normal config files."""
        env = {
            **command,
            "PATH": self._inherited.get("PATH", os.defpath),
            "HOME": self._inherited.get("HOME", os.path.expanduser("~")),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_DIR": os.devnull,
        }
        try:
            result = subprocess.run(
                ["git", "config", "--null", "--list", "--includes"],
                env=env,
                capture_output=True,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallError(
                "Could not read inherited Git command settings; "
                "check Git options and include paths"
            ) from exc
        return [
            self._decode_setting(entry)
            for entry in os.fsdecode(result.stdout).split("\0")
            if entry
        ]

    @staticmethod
    def _decode_setting(entry: str) -> tuple[str, str]:
        key, separator, value = entry.partition("\n")
        return key, value if separator else "true"

    @staticmethod
    def _exclude_setting(key: str) -> bool:
        normalized = key.lower()
        if normalized.startswith("includeif.") and normalized.endswith(".path"):
            raise InstallError(
                "Move conditional Git command includes to your Git config "
                "before running punt install"
            )
        return normalized == "include.path" or (
            normalized.startswith("url.")
            and normalized.endswith((".insteadof", ".pushinsteadof"))
        )
