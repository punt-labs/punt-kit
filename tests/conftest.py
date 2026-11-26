"""Suite-wide fixtures: output that does not depend on the terminal."""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from tools.test_quarantine import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Fix the rendering width so long temporary paths do not wrap asserted messages.
_WIDTH = 10000


_AMBIENT_GIT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
)


@pytest.fixture(autouse=True, scope="session")
def _private_git_config(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    # Global and system git config (url.insteadOf rewrites, signing, hooks)
    # would change what remotes and commits the tests and their git children see.
    config = tmp_path_factory.mktemp("git") / "config"
    config.write_text("[user]\n\tname = punt-kit tests\n\temail = tests@example.com\n")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GIT_CONFIG_GLOBAL", str(config))
        patch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        for name in _AMBIENT_GIT:
            patch.delenv(name, raising=False)
        yield


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # COLUMNS applies to new consoles; patch the import-time consoles directly.
    monkeypatch.setenv("COLUMNS", str(_WIDTH))
    for name, module in list(sys.modules.items()):
        if not name.startswith("punt_kit"):
            continue
        for value in vars(module).values():
            if isinstance(value, Console):
                monkeypatch.setattr(value, "width", _WIDTH)


@pytest.fixture
def isolated_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run real uv subprocesses offline without user settings or credentials."""
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    for name in tuple(os.environ):
        if name.startswith("UV_"):
            monkeypatch.delenv(name)
    home = tmp_path / "uv-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("CACHE", "CONFIG", "DATA", "STATE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(home / name.lower()))
    monkeypatch.setenv("NETRC", str(home / ".netrc"))
    monkeypatch.setenv("UV_CACHE_DIR", str(home / "cache"))
    monkeypatch.setenv("UV_NO_CONFIG", "1")
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_KEYRING_PROVIDER", "disabled")
    monkeypatch.setenv("UV_PYTHON", sys.executable)
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
