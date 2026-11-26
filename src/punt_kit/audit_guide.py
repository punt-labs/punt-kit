"""Check the Linear workflow guide for `punt repo audit`.

The checks key on the ``enabled`` marker, not on the guide's presence
(tool-enable-disable.md 2.7): a repo that enabled punt must deposit the guide
and import it from ``CLAUDE.md``; a repo where punt is dormant must not import
it. The guide stays on disk after ``punt disable``, so its presence says nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.audit_verdict import FAIL, INFO, PASS
from punt_kit.claude_md import ClaudeMdImport
from punt_kit.errors import ReleaseError

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo

    Finding = tuple[str, str, str]

GUIDE = ".punt-labs/punt/CLAUDE.md"
MARKER = ".punt-labs/punt/enabled"
LABEL = "Linear workflow guide imported"


@final
class PuntGuideAudit:
    """Checks the Linear workflow guide against whether punt is enabled."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, info: ProjectInfo) -> Self:
        """Create an audit of the repository at ``info.root``."""
        self = super().__new__(cls)
        self._root = info.root
        return self

    def findings(self) -> list[Finding]:
        """Return the single guide finding for the repo's enabled or dormant state.

        Raises:
            ReleaseError: ``CLAUDE.md`` exists but cannot be read.
        """
        imported = self._is_imported()
        if not (self._root / MARKER).exists():
            if imported:
                detail = f"CLAUDE.md imports @{GUIDE} but punt is not enabled"
                return [(FAIL, LABEL, f"{detail} — run punt enable or remove it")]
            return [(INFO, LABEL, "punt is not enabled")]
        if not (self._root / GUIDE).exists():
            return [(FAIL, LABEL, f"Missing {GUIDE} — run punt enable")]
        if not imported:
            detail = f"CLAUDE.md does not import @{GUIDE}"
            return [(FAIL, LABEL, f"{detail} — run punt enable")]
        return [(PASS, LABEL, GUIDE)]

    def _is_imported(self) -> bool:
        """Return whether ``CLAUDE.md`` imports the guide at top level."""
        try:
            return ClaudeMdImport(self._root / "CLAUDE.md", f"@{GUIDE}").is_registered()
        except OSError as exc:
            raise ReleaseError(f"Cannot read CLAUDE.md: {exc.strerror}") from exc
