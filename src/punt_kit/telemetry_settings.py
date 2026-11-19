"""Read the user's persistent telemetry capture preference."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Self, cast, final

from punt_observe.telemetry import TelemetryConfig

logger = logging.getLogger(__name__)


@final
class TelemetrySettings:
    """Own the user configuration location and safe capture defaults."""

    __slots__ = ("_path",)

    _path: Path

    def __new__(cls) -> Self:
        """Bind settings to punt's per-user configuration file."""
        self = super().__new__(cls)
        self._path = Path.home() / ".punt-labs/punt/config.toml"
        return self

    def load(self) -> TelemetryConfig:
        """Load a boolean preference without surfacing configuration contents."""
        try:
            config = tomllib.loads(self._path.read_text())
        except FileNotFoundError:
            return TelemetryConfig()
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            logger.warning(
                "Check telemetry configuration: "
                "unreadable or malformed TOML; using defaults"
            )
            return TelemetryConfig()
        section = config.get("telemetry", {})
        if isinstance(section, dict):
            enabled = cast("dict[str, object]", section).get("enabled", True)
            if isinstance(enabled, bool):
                return TelemetryConfig(enabled=enabled)
        logger.warning(
            "Check telemetry configuration: enabled must be boolean; using defaults"
        )
        return TelemetryConfig()
