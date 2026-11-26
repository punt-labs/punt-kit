"""punt repo scan-pii — scan repository for personally identifiable information."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rich.console import Console

from punt_kit.phases.shared.text_file import TextFile
from punt_kit.pii_matcher import Finding, PiiMatcher, ScanSource
from punt_kit.pii_matcher import PiiConfig as PiiConfig

if TYPE_CHECKING:
    from collections.abc import Callable

console = Console()


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """Locate and decode the PII settings for one checkout."""

    root: Path
    index_blob: Callable[[str], bytes | None] | None = None

    def load(self, config_path: str | None) -> PiiConfig:
        """Load the PII config from the first applicable source.

        An explicit ``config_path`` must exist and wins over other settings.
        Otherwise ``[tool.punt.pii]`` in ``pyproject.toml`` is used,
        then ``.punt-pii.toml``, then the defaults.

        Raises:
            ReleaseError: A config file cannot be read or is not valid TOML.
        """
        if config_path is not None:
            return PiiConfig.from_dict(TextFile(Path(config_path)).toml())

        if (data := self._read_default("pyproject.toml")) is not None:
            pii_section = self._drill(data, "tool", "punt", "pii")
            if pii_section is not None:
                return PiiConfig.from_dict(pii_section)

        if (data := self._read_default(".punt-pii.toml")) is not None:
            return PiiConfig.from_dict(data)

        return PiiConfig()

    def _read_default(self, name: str) -> dict[str, object] | None:
        if self.index_blob is None:
            path = self.root / name
            return TextFile(path).toml() if path.exists() else None
        blob = self.index_blob(name)
        if blob is None:
            return None
        source = f"staged {name}"
        return TextFile.parse_toml(
            TextFile.from_bytes(blob, source=source), source=source
        )

    @staticmethod
    def _drill(data: dict[str, object], *keys: str) -> dict[str, object] | None:
        """Walk nested dicts by key sequence, returning None if any key is missing."""
        current = data
        for key in keys:
            child = current.get(key)
            if not isinstance(child, dict):
                return None
            current = cast("dict[str, object]", child)
        return current


def load_config(root: Path, config_path: str | None = None) -> PiiConfig:
    """Load the PII settings, preferring an explicit config file."""
    return ConfigSource(root).load(config_path)


def is_binary(path: Path) -> bool:
    """Return whether a file has a NUL byte in its first 8 KiB or is unreadable."""
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def scan_file(
    rel_path: str,
    root: Path,
    config: PiiConfig,
) -> list[Finding]:
    """Scan one file for PII.

    A missing, binary or unreadable file yields no findings. An invalid
    ``allow_patterns`` regex is skipped with a warning.
    """
    full_path = root / rel_path

    if not full_path.is_file() or is_binary(full_path):
        return []

    try:
        content = full_path.read_text(errors="replace")
    except (OSError, UnicodeError):
        return []

    return PiiMatcher(config, compile_allow_patterns(config.allow_patterns)).scan(
        ScanSource(rel_path, content)
    )


def compile_allow_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile allow patterns, warning about any invalid patterns."""
    allow_regexes: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            allow_regexes.append(re.compile(p))
        except re.error as exc:
            console.print(
                f"[yellow]Warning:[/yellow] invalid allow_pattern skipped:"
                f" {p!r} ({exc})"
            )
    return allow_regexes
