"""Check the Linear workflow guide for `punt repo audit`.

The guide is deposited at ``.punt-labs/punt/CLAUDE.md`` and the repo's
``CLAUDE.md`` must import it, so every agent session reads how work is tracked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.audit_verdict import FAIL, PASS
from punt_kit.claude_md import ClaudeMdImport
from punt_kit.errors import ReleaseError

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
        """Return the single guide finding: missing, not imported, or present.

        Raises:
            ReleaseError: ``CLAUDE.md`` exists but cannot be read.
        """
        if not (self._root / GUIDE).exists():
            return [(FAIL, LABEL, f"Missing {GUIDE} — run punt enable")]
        if not self._is_imported():
            detail = f"CLAUDE.md does not import @{GUIDE}"
            return [(FAIL, LABEL, f"{detail} — run punt enable")]
        return [(PASS, LABEL, GUIDE)]

    def _is_imported(self) -> bool:
        """Return whether ``CLAUDE.md`` imports the guide at top level."""
        try:
            return ClaudeMdImport(self._root / "CLAUDE.md", f"@{GUIDE}").is_registered()
        except OSError as exc:
            raise ReleaseError(f"Cannot read CLAUDE.md: {exc.strerror}") from exc
