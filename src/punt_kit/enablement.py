"""``punt enable`` / ``punt disable``: punt turning itself on in one repo.

Per ``tool-enable-disable.md`` §2.3 and §2.10, ``enable`` grants punt's
permission rules, deposits punt's user guide at ``.punt-labs/punt/CLAUDE.md``,
writes the ``enabled`` marker and adds the ``@.punt-labs/punt/CLAUDE.md`` line
to the repo ``CLAUDE.md``. ``disable`` reverses the rules, the import line and
the marker, and leaves the guide in place, dormant (§2.9).
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, final

from punt_kit.claude_md import ClaudeMdImport
from punt_kit.claude_permissions import ProjectPermissions

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["EnablementReport", "PuntEnablement"]

_GUIDE: Final = importlib.resources.files("punt_kit") / "templates" / "punt-guide.md"
_SUBTREE: Final = ".punt-labs/punt"
IMPORT_LINE: Final = f"@{_SUBTREE}/CLAUDE.md"


@dataclass(frozen=True, slots=True)
class EnablementReport:
    """What ``enable`` or ``disable`` changed, or why it refused."""

    changes: tuple[str, ...] = ()
    error: str = ""


@final
class PuntEnablement:
    """Enable or disable punt in the repo rooted at ``root``."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    @property
    def _subtree(self) -> Path:
        return self._root / _SUBTREE

    @property
    def _import(self) -> ClaudeMdImport:
        return ClaudeMdImport(self._root / "CLAUDE.md", IMPORT_LINE)

    def enable(self) -> EnablementReport:
        """Grant the rules first, so a refused settings file changes nothing."""
        granted = ProjectPermissions(self._root).grant()
        if granted.error:
            return EnablementReport(error=granted.error)
        changes = granted.lines("added to")
        guide = self._subtree / "CLAUDE.md"
        text = _GUIDE.read_text(encoding="utf-8")
        if not guide.is_file() or guide.read_text(encoding="utf-8") != text:
            guide.parent.mkdir(parents=True, exist_ok=True)
            guide.write_text(text, encoding="utf-8")
            changes.append(f"Deposited {_SUBTREE}/CLAUDE.md")
        marker = self._subtree / "enabled"
        if not marker.exists():
            marker.touch()
            changes.append(f"Wrote {_SUBTREE}/enabled")
        if self._import.register():
            changes.append(f"Added {IMPORT_LINE} to CLAUDE.md")
        return EnablementReport(changes=tuple(changes))

    def disable(self) -> EnablementReport:
        """Revoke the rules first, so a refused settings file changes nothing."""
        revoked = ProjectPermissions(self._root).revoke()
        if revoked.error:
            return EnablementReport(error=revoked.error)
        changes = revoked.lines("removed from")
        if self._import.prune():
            changes.append(f"Removed {IMPORT_LINE} from CLAUDE.md")
        marker = self._subtree / "enabled"
        if marker.exists():
            marker.unlink()
            changes.append(f"Deleted {_SUBTREE}/enabled")
        return EnablementReport(changes=tuple(changes))
