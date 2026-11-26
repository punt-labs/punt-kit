"""Check the Linear workflow guide for `punt repo audit`.

The guide is deposited at ``.punt-labs/punt/CLAUDE.md`` and the repo's
``CLAUDE.md`` must import it, so every agent session reads how work is tracked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.audit_verdict import FAIL, PASS
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo

    Finding = tuple[str, str, str]

GUIDE = ".punt-labs/punt/CLAUDE.md"
LABEL = "Linear workflow guide imported"


@final
class PuntGuideAudit:
    """Checks that the Linear workflow guide is deposited and imported."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, info: ProjectInfo) -> Self:
        """Create an audit of the repository at ``info.root``."""
        self = super().__new__(cls)
        self._root = info.root
        return self

    def findings(self) -> list[Finding]:
        """Return the single guide finding: missing, not imported, or present."""
        if not (self._root / GUIDE).exists():
            return [(FAIL, LABEL, f"Missing {GUIDE} — run punt enable")]
        claude_md = self._root / "CLAUDE.md"
        if not (claude_md.exists() and f"@{GUIDE}" in TextFile(claude_md).read()):
            detail = f"CLAUDE.md does not import @{GUIDE}"
            return [(FAIL, LABEL, f"{detail} — run punt enable")]
        return [(PASS, LABEL, GUIDE)]
