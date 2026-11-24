"""Suite-wide fixtures: output that does not depend on the terminal."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from tools.test_quarantine import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# Fix the rendering width so long temporary paths do not wrap asserted messages.
_WIDTH = 10000


_AMBIENT_GIT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG")


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
