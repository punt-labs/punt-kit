"""Resolve Punt's product-owned home paths and read user configuration."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Self, cast, final

from punt_observe.telemetry import TelemetryConfig

logger = logging.getLogger(__name__)


@final
class PuntPaths:
    """Own Punt's home namespace and its user configuration boundary."""

    __slots__ = ("_home",)

    _home: Path

    def __new__(cls) -> Self:
        """Bind Punt's home root independently of the checkout.

        Raises:
            RuntimeError: The user home is unavailable or relative.
        """
        home = Path.home()
        if not home.is_absolute():
            raise RuntimeError("user home directory must be absolute")
        self = super().__new__(cls)
        self._home = home / ".punt-labs" / "punt"
        return self

    @property
    def home(self) -> Path:
        """Return the product home root."""
        return self._home

    def telemetry_config(self) -> TelemetryConfig:
        """Load a boolean preference without surfacing configuration contents."""
        try:
            config = tomllib.loads((self._home / "config.toml").read_text())
        except FileNotFoundError:
            return TelemetryConfig()
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            logger.warning("Unreadable or malformed telemetry TOML; using defaults")
            return TelemetryConfig()
        section = config.get("telemetry", {})
        if isinstance(section, dict):
            enabled = cast("dict[str, object]", section).get("enabled", True)
            if isinstance(enabled, bool):
                return TelemetryConfig(enabled=enabled)
        logger.warning("Telemetry enabled must be boolean; using defaults")
        return TelemetryConfig()
