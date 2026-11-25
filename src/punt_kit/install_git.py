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
        env = self._inherited.copy()
        parameters = env.pop("GIT_CONFIG_PARAMETERS", "")
        pairs = self._indexed_settings(env)
        if parameters:
            pairs.extend(self._git_parameters(parameters))
        pairs = [pair for pair in pairs if not self._is_url_rewrite(pair[0])]
        pairs.append(
            ("url.https://github.com/punt-labs/.insteadOf", "git@github.com:punt-labs/")
        )
        for index, (key, value) in enumerate(pairs):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        env["GIT_CONFIG_COUNT"] = str(len(pairs))
        return env

    @staticmethod
    def _indexed_settings(env: dict[str, str]) -> list[tuple[str, str]]:
        try:
            count = int(env.get("GIT_CONFIG_COUNT", "0"))
        except ValueError as exc:
            raise InstallError(
                "Invalid GIT_CONFIG_COUNT; check the Git environment"
            ) from exc
        if not 0 <= count <= len(env) // 2:
            raise InstallError("Invalid GIT_CONFIG_COUNT; check the Git environment")
        pairs: list[tuple[str, str]] = []
        for index in range(count):
            key = env.pop(f"GIT_CONFIG_KEY_{index}", "")
            value = env.pop(f"GIT_CONFIG_VALUE_{index}", None)
            if not key or value is None:
                raise InstallError("Incomplete Git configuration in the environment")
            pairs.append((key, value))
        return pairs

    @staticmethod
    def _git_parameters(parameters: str) -> list[tuple[str, str]]:
        """Let Git decode its command settings without loading config files."""
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_CONFIG_PARAMETERS": parameters,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_DIR": os.devnull,
        }
        try:
            result = subprocess.run(
                ["git", "config", "--null", "--list", "--no-includes"],
                env=env,
                capture_output=True,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallError("Could not read inherited Git command settings") from exc
        pairs: list[tuple[str, str]] = []
        for entry in os.fsdecode(result.stdout).split("\0"):
            if entry:
                key, separator, value = entry.partition("\n")
                pairs.append((key, value if separator else "true"))
        return pairs

    @staticmethod
    def _is_url_rewrite(key: str) -> bool:
        normalized = key.lower()
        return normalized.startswith("url.") and normalized.endswith(
            (".insteadof", ".pushinsteadof")
        )
