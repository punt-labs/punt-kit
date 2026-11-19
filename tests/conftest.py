"""Suite-wide fixtures: output that does not depend on the terminal."""

from __future__ import annotations

import sys

import pytest
from rich.console import Console

# Fix the rendering width so long temporary paths do not wrap asserted messages.
_WIDTH = 10000


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
