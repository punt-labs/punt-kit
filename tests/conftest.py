"""Suite-wide fixtures: output that does not depend on the terminal."""

from __future__ import annotations

import sys

import pytest
from rich.console import Console

# Rich wraps at the terminal width, and a long tmp path makes it split a
# message across lines, so assertions on whole messages would pass or fail by
# machine. No test asserts on wrapping.
_WIDTH = 10000


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # A Console built from now on reads COLUMNS; the module-level ones were
    # built at import, so pin each of those directly.
    monkeypatch.setenv("COLUMNS", str(_WIDTH))
    for name, module in list(sys.modules.items()):
        if not name.startswith("punt_kit"):
            continue
        for value in vars(module).values():
            if isinstance(value, Console):
                monkeypatch.setattr(value, "width", _WIDTH)
