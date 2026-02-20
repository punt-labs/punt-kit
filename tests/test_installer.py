"""Tests for the plugin installer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from punt_kit.installer import install, plugin_source, uninstall

if TYPE_CHECKING:
    from pathlib import Path


def test_plugin_source_resolves() -> None:
    """plugin_source() returns a path containing the bundled plugin files."""
    source = plugin_source()
    assert (source / ".claude-plugin" / "plugin.json").exists()
    assert (source / "commands" / "reconcile.md").exists()


def test_install_copies_plugin_files(tmp_path: Path) -> None:
    """Install copies plugin directory to the target location."""
    plugins_dir = tmp_path / "plugins" / "punt"
    registry_path = tmp_path / "plugins" / "installed_plugins.json"
    settings_path = tmp_path / "settings.json"

    result = install(
        plugins_dir=plugins_dir,
        registry_path=registry_path,
        settings_path=settings_path,
    )

    assert result.installed
    assert (plugins_dir / ".claude-plugin" / "plugin.json").exists()
    assert (plugins_dir / "commands" / "reconcile.md").exists()


def test_install_registers_plugin(tmp_path: Path) -> None:
    """Install registers punt@local in the plugin registry."""
    plugins_dir = tmp_path / "plugins" / "punt"
    registry_path = tmp_path / "plugins" / "installed_plugins.json"
    settings_path = tmp_path / "settings.json"

    install(
        plugins_dir=plugins_dir,
        registry_path=registry_path,
        settings_path=settings_path,
    )

    registry = json.loads(registry_path.read_text())
    assert "punt@local" in registry["plugins"]
    entry = registry["plugins"]["punt@local"][0]
    assert entry["scope"] == "user"
    assert entry["installPath"] == str(plugins_dir)


def test_install_enables_plugin(tmp_path: Path) -> None:
    """Install enables punt@local in settings.json."""
    plugins_dir = tmp_path / "plugins" / "punt"
    registry_path = tmp_path / "plugins" / "installed_plugins.json"
    settings_path = tmp_path / "settings.json"

    install(
        plugins_dir=plugins_dir,
        registry_path=registry_path,
        settings_path=settings_path,
    )

    settings = json.loads(settings_path.read_text())
    assert settings["enabledPlugins"]["punt@local"] is True


def test_install_stops_on_file_copy_failure(tmp_path: Path) -> None:
    """Install does not register or enable if file copy fails."""
    # Point to a non-writable path to force copy failure
    plugins_dir = tmp_path / "no-parent" / "deep" / "punt"
    # Create a file where the parent directory should be, making mkdir fail
    (tmp_path / "no-parent").write_text("blocker")

    registry_path = tmp_path / "installed_plugins.json"
    settings_path = tmp_path / "settings.json"

    result = install(
        plugins_dir=plugins_dir,
        registry_path=registry_path,
        settings_path=settings_path,
    )

    assert not result.installed
    assert len(result.steps) == 1  # Only the file copy step ran
    assert not result.steps[0].passed
    # Registry and settings should not have been touched
    assert not registry_path.exists()
    assert not settings_path.exists()


def test_install_idempotent(tmp_path: Path) -> None:
    """Running install twice succeeds both times."""
    plugins_dir = tmp_path / "plugins" / "punt"
    registry_path = tmp_path / "plugins" / "installed_plugins.json"
    settings_path = tmp_path / "settings.json"

    kwargs = dict(
        plugins_dir=plugins_dir,
        registry_path=registry_path,
        settings_path=settings_path,
    )

    result1 = install(**kwargs)
    result2 = install(**kwargs)

    assert result1.installed
    assert result2.installed


def test_uninstall_removes_everything(tmp_path: Path) -> None:
    """Uninstall reverses install: removes files, registry entry, and setting."""
    plugins_dir = tmp_path / "plugins" / "punt"
    registry_path = tmp_path / "plugins" / "installed_plugins.json"
    settings_path = tmp_path / "settings.json"

    kwargs = dict(
        plugins_dir=plugins_dir,
        registry_path=registry_path,
        settings_path=settings_path,
    )

    install(**kwargs)
    result = uninstall(**kwargs)

    assert result.uninstalled
    assert not plugins_dir.exists()

    registry = json.loads(registry_path.read_text())
    assert "punt@local" not in registry.get("plugins", {})

    settings = json.loads(settings_path.read_text())
    assert "punt@local" not in settings.get("enabledPlugins", {})


def test_uninstall_when_not_installed(tmp_path: Path) -> None:
    """Uninstall succeeds even when nothing is installed."""
    result = uninstall(
        plugins_dir=tmp_path / "plugins" / "punt",
        registry_path=tmp_path / "plugins" / "installed_plugins.json",
        settings_path=tmp_path / "settings.json",
    )

    assert result.uninstalled
