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

    @classmethod
    def telemetry_config(cls) -> TelemetryConfig:
        """Load a boolean preference without surfacing configuration contents."""
        try:
            path = cls().home / "config.toml"
        except RuntimeError:
            logger.warning(
                "Check telemetry configuration: home unavailable; capture disabled"
            )
            return TelemetryConfig(enabled=False)

        try:
            config = tomllib.loads(path.read_text())
        except FileNotFoundError:
            return TelemetryConfig()
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            logger.warning(
                "Check telemetry configuration: "
                "unreadable or malformed TOML; using defaults"
            )
            return TelemetryConfig()
        telemetry = config.get("telemetry", {})
        enabled = (
            cast("dict[str, object]", telemetry).get("enabled", True)
            if isinstance(telemetry, dict)
            else None
        )
        if isinstance(enabled, bool):
            return TelemetryConfig(enabled=enabled)
        logger.warning(
            "Check telemetry configuration: enabled must be boolean; using defaults"
        )
        return TelemetryConfig()
