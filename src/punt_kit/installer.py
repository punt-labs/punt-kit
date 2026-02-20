"""Plugin installation for punt-kit.

Copies bundled plugin files (slash commands, plugin manifest) into the
Claude Code plugin directory and registers the plugin in the Claude Code
settings.  Uninstall reverses all operations.
"""

from __future__ import annotations

import importlib.resources
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Well-known paths ----------------------------------------------------------

PLUGINS_DIR = Path.home() / ".claude" / "plugins" / "punt"
REGISTRY_PATH = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
PLUGIN_KEY = "punt@local"


# Result types --------------------------------------------------------------


@dataclass(frozen=True)
class StepResult:
    """Outcome of a single install/uninstall step."""

    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class InstallResult:
    """Outcome of a full install attempt."""

    installed: bool
    message: str
    steps: list[StepResult] = field(default_factory=list[StepResult])


@dataclass(frozen=True)
class UninstallResult:
    """Outcome of a full uninstall attempt."""

    uninstalled: bool
    message: str
    steps: list[StepResult] = field(default_factory=list[StepResult])


# Plugin source --------------------------------------------------------------


def plugin_source() -> Path:
    """Resolve the bundled plugin directory from package data."""
    return Path(str(importlib.resources.files("punt_kit.plugins").joinpath("punt")))


# Settings helpers -----------------------------------------------------------


def _read_json(path: Path) -> dict[str, object]:
    """Read a JSON file, returning empty dict if absent or corrupt."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, object]) -> None:
    """Write a JSON file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# Plugin files ---------------------------------------------------------------


def _install_plugin_files(target: Path | None = None) -> StepResult:
    """Copy plugin files from package data to the Claude plugins directory."""
    target = target or PLUGINS_DIR
    source = plugin_source()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        return StepResult("Plugin files", True, f"installed to {target}")
    except OSError as exc:
        return StepResult("Plugin files", False, f"copy failed: {exc}")


def _uninstall_plugin_files(target: Path | None = None) -> StepResult:
    """Remove plugin files from the Claude plugins directory."""
    target = target or PLUGINS_DIR
    if not target.exists():
        return StepResult("Plugin files", True, "not installed (nothing to remove)")
    try:
        shutil.rmtree(target)
        return StepResult("Plugin files", True, "removed")
    except OSError as exc:
        return StepResult("Plugin files", False, f"removal failed: {exc}")


# Plugin registry ------------------------------------------------------------


def _register_plugin(
    registry_path: Path | None = None,
    plugins_dir: Path | None = None,
) -> StepResult:
    """Add ``punt@local`` to ``installed_plugins.json``."""
    registry_path = registry_path or REGISTRY_PATH
    plugins_dir = plugins_dir or PLUGINS_DIR

    registry = _read_json(registry_path)
    plugins = registry.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        registry["plugins"] = plugins

    now = datetime.now(UTC).isoformat()
    entry = {
        "scope": "user",
        "installPath": str(plugins_dir),
        "version": "local",
        "installedAt": now,
        "lastUpdated": now,
    }
    plugins[PLUGIN_KEY] = [entry]

    try:
        _write_json(registry_path, registry)
        return StepResult("Plugin registry", True, f"registered {PLUGIN_KEY}")
    except OSError as exc:
        return StepResult("Plugin registry", False, f"write failed: {exc}")


def _unregister_plugin(registry_path: Path | None = None) -> StepResult:
    """Remove ``punt@local`` from ``installed_plugins.json``."""
    registry_path = registry_path or REGISTRY_PATH
    if not registry_path.exists():
        return StepResult("Plugin registry", True, "no registry file")

    registry = _read_json(registry_path)
    plugins = registry.get("plugins")
    if not isinstance(plugins, dict) or PLUGIN_KEY not in plugins:
        return StepResult("Plugin registry", True, f"{PLUGIN_KEY} not registered")

    del plugins[PLUGIN_KEY]
    try:
        _write_json(registry_path, registry)
        return StepResult("Plugin registry", True, f"unregistered {PLUGIN_KEY}")
    except OSError as exc:
        return StepResult("Plugin registry", False, f"write failed: {exc}")


# Plugin enable/disable in settings ------------------------------------------


def _enable_plugin(settings_path: Path | None = None) -> StepResult:
    """Enable ``punt@local`` in ``settings.json``."""
    settings_path = settings_path or SETTINGS_PATH
    settings = _read_json(settings_path)
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict):
        enabled = {}
        settings["enabledPlugins"] = enabled

    enabled[PLUGIN_KEY] = True
    try:
        _write_json(settings_path, settings)
        return StepResult("Plugin enabled", True, f"enabled {PLUGIN_KEY}")
    except OSError as exc:
        return StepResult("Plugin enabled", False, f"write failed: {exc}")


def _disable_plugin(settings_path: Path | None = None) -> StepResult:
    """Disable ``punt@local`` in ``settings.json``."""
    settings_path = settings_path or SETTINGS_PATH
    if not settings_path.exists():
        return StepResult("Plugin enabled", True, "no settings file")

    settings = _read_json(settings_path)
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict) or PLUGIN_KEY not in enabled:
        return StepResult("Plugin enabled", True, f"{PLUGIN_KEY} not enabled")

    del enabled[PLUGIN_KEY]
    try:
        _write_json(settings_path, settings)
        return StepResult("Plugin enabled", True, f"disabled {PLUGIN_KEY}")
    except OSError as exc:
        return StepResult("Plugin enabled", False, f"write failed: {exc}")


# Public API -----------------------------------------------------------------


def install(
    plugins_dir: Path | None = None,
    settings_path: Path | None = None,
    registry_path: Path | None = None,
) -> InstallResult:
    """Install punt plugin for Claude Code.

    Steps (sequential — stops on first failure):
    1. Copy plugin files to ``~/.claude/plugins/punt/``
    2. Register in ``installed_plugins.json``
    3. Enable in ``settings.json``

    Commands are accessed via the plugin namespace (``/punt reconcile``),
    not deployed as top-level user commands.

    Idempotent: safe to run multiple times.
    """
    steps: list[StepResult] = []

    file_step = _install_plugin_files(plugins_dir)
    steps.append(file_step)
    if not file_step.passed:
        return InstallResult(
            installed=False,
            message="Installation failed: plugin files could not be copied.",
            steps=steps,
        )

    steps.append(_register_plugin(registry_path, plugins_dir))
    steps.append(_enable_plugin(settings_path))

    if any(not s.passed for s in steps):
        return InstallResult(
            installed=False,
            message="Installation incomplete (see details above).",
            steps=steps,
        )
    return InstallResult(
        installed=True,
        message="Installed. Restart Claude Code to activate.",
        steps=steps,
    )


def uninstall(
    plugins_dir: Path | None = None,
    settings_path: Path | None = None,
    registry_path: Path | None = None,
) -> UninstallResult:
    """Uninstall punt plugin from Claude Code.

    Steps:
    1. Disable plugin in ``settings.json``
    2. Remove from ``installed_plugins.json``
    3. Remove plugin files
    """
    steps = [
        _disable_plugin(settings_path),
        _unregister_plugin(registry_path),
        _uninstall_plugin_files(plugins_dir),
    ]

    if any(not s.passed for s in steps):
        return UninstallResult(
            uninstalled=False,
            message="Uninstall incomplete (see details above).",
            steps=steps,
        )
    return UninstallResult(
        uninstalled=True,
        message="Uninstalled.",
        steps=steps,
    )
