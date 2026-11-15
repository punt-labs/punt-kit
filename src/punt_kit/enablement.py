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

    def _refusal(self) -> str:
        """Name a symlinked subtree path, which would redirect writes elsewhere."""
        punt_labs = self._root / ".punt-labs"
        for path in (punt_labs, self._subtree, self._guide, self._marker):
            if path.is_symlink():
                name = path.relative_to(self._root)
                return f"{name} is a symlink; refusing to write through it"
        return ""

    @property
    def _guide(self) -> Path:
        return self._subtree / "CLAUDE.md"

    @property
    def _marker(self) -> Path:
        return self._subtree / "enabled"

    def enable(self) -> EnablementReport:
        """Grant the rules first, so a refused settings file changes nothing."""
        if refusal := self._refusal():
            return EnablementReport(error=refusal)
        granted = ProjectPermissions(self._root).grant()
        if granted.error:
            return EnablementReport(error=granted.error)
        changes = granted.lines("added to")
        try:
            changes.extend(self._deposit())
        except OSError as exc:
            return EnablementReport(changes=tuple(changes), error=str(exc))
        return EnablementReport(changes=tuple(changes))

    def _deposit(self) -> list[str]:
        changes: list[str] = []
        data = _GUIDE.read_bytes()
        if not self._guide.is_file() or self._guide.read_bytes() != data:
            self._subtree.mkdir(parents=True, exist_ok=True)
            self._guide.write_bytes(data)
            changes.append(f"Deposited {_SUBTREE}/CLAUDE.md")
        if not self._marker.exists():
            self._marker.touch()
            changes.append(f"Wrote {_SUBTREE}/enabled")
        if self._import.register():
            changes.append(f"Added {IMPORT_LINE} to CLAUDE.md")
        return changes

    def disable(self) -> EnablementReport:
        """Revoke the rules first, so a refused settings file changes nothing."""
        if refusal := self._refusal():
            return EnablementReport(error=refusal)
        revoked = ProjectPermissions(self._root).revoke()
        if revoked.error:
            return EnablementReport(error=revoked.error)
        changes = revoked.lines("removed from")
        try:
            if self._import.prune():
                changes.append(f"Removed {IMPORT_LINE} from CLAUDE.md")
            if self._marker.exists():
                self._marker.unlink()
                changes.append(f"Deleted {_SUBTREE}/enabled")
        except OSError as exc:
            return EnablementReport(changes=tuple(changes), error=str(exc))
        return EnablementReport(changes=tuple(changes))
