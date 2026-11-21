"""Manage punt activation in a repository.

Enablement writes the permission rules, guide, marker, and import line.
Disabling removes everything except the guide.
"""

from __future__ import annotations

import importlib.resources
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, final

from punt_kit.claude_md import UNCLOSED_FENCE, ClaudeMdImport, write_atomically
from punt_kit.claude_permissions import ProjectPermissions

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["EnablementReport", "PuntEnablement"]

logger = logging.getLogger(__name__)

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
        """Bind enablement operations to the repository at ``root``."""
        self = super().__new__(cls)
        self._root = root
        return self

    @property
    def _subtree(self) -> Path:
        return self._root / _SUBTREE

    @property
    def _import(self) -> ClaudeMdImport:
        return ClaudeMdImport(self._root / "CLAUDE.md", IMPORT_LINE)

    def _refusal(self, *files: Path) -> str:
        """Name a path that would make the toggle misfire or write elsewhere.

        A symlinked subtree path would redirect writes, and anything other
        than a regular file at the marker would fail its unlink only after
        the rules were already revoked.
        """
        for path in (self._root / ".punt-labs", self._subtree, *files):
            if path.is_symlink():
                name = path.relative_to(self._root)
                return f"{name} is a symlink; refusing to write through it"
        marker = self._marker
        if marker.exists() and not marker.is_symlink() and not marker.is_file():
            return f"{_SUBTREE}/enabled is not a regular file; remove it first"
        return ""

    @property
    def _guide(self) -> Path:
        return self._subtree / "CLAUDE.md"

    @property
    def _marker(self) -> Path:
        return self._subtree / "enabled"

    def enable(self) -> EnablementReport:
        """Enable punt and record the configuration outcome."""
        return self._toggle(on=True)

    def disable(self) -> EnablementReport:
        """Disable punt and record the configuration outcome."""
        return self._toggle(on=False)

    def _toggle(self, *, on: bool) -> EnablementReport:
        verb = "enable" if on else "disable"
        try:
            return self._enable() if on else self._disable()
        except (OSError, ValueError) as exc:
            logger.info(
                "Punt %s failed during configuration inspection: %s",
                verb,
                type(exc).__name__,
            )
            raise

    def _report(
        self,
        verb: str,
        changes: tuple[str, ...] = (),
        *,
        error: str = "",
        reason: str = "none",
    ) -> EnablementReport:
        outcome = "failed" if error else "changed" if changes else "no-op"
        logger.info(
            "Punt %s outcome=%s; skill permissions changed=%d, guide updated=%s, "
            "activation marker changed=%s, guide import changed=%s; reason=%s",
            verb,
            outcome,
            sum(line.startswith("Permission ") for line in changes),
            any(line.startswith("Deposited ") for line in changes),
            any(line.startswith(("Wrote ", "Deleted ")) for line in changes),
            any(line.startswith(("Added ", "Removed ")) for line in changes),
            reason,
        )
        return EnablementReport(changes=changes, error=error)

    def _enable(self) -> EnablementReport:
        """Grant punt's rules, then deposit the guide, marker and import line.

        The rules go first, so a refused settings file changes nothing.
        """
        if refusal := self._refusal(self._guide, self._marker):
            return self._report(
                "enable", error=refusal, reason="unsafe activation target"
            )
        if self._import.append_would_be_fenced():
            return self._report(
                "enable", error=UNCLOSED_FENCE, reason="unclosed guide fence"
            )
        granted = ProjectPermissions(self._root).grant()
        if granted.error:
            return self._report(
                "enable",
                error=granted.error,
                reason="permission settings rejected or inaccessible",
            )
        changes = granted.lines("added to")
        try:
            self._deposit(changes)
        except (OSError, ValueError) as exc:
            return self._report(
                "enable", tuple(changes), error=str(exc), reason=type(exc).__name__
            )
        return self._report("enable", tuple(changes))

    def _deposit(self, changes: list[str]) -> None:
        """Write the guide, marker and import, recording each as it lands."""
        text = _GUIDE.read_text(encoding="utf-8")
        if not self._guide.is_file() or self._guide.read_bytes() != text.encode():
            write_atomically(self._guide, text)
            changes.append(f"Deposited {_SUBTREE}/CLAUDE.md")
        if not self._marker.exists():
            self._marker.touch()
            changes.append(f"Wrote {_SUBTREE}/enabled")
        if self._import.register():
            changes.append(f"Added {IMPORT_LINE} to CLAUDE.md")

    def _disable(self) -> EnablementReport:
        """Revoke punt's rules, then remove the import line and marker.

        A refused settings file changes nothing. The guide stays in place.
        """
        if refusal := self._refusal():
            return self._report(
                "disable", error=refusal, reason="unsafe activation target"
            )
        revoked = ProjectPermissions(self._root).revoke()
        if revoked.error:
            return self._report(
                "disable",
                error=revoked.error,
                reason="permission settings rejected or inaccessible",
            )
        changes = revoked.lines("removed from")
        try:
            if self._import.prune():
                changes.append(f"Removed {IMPORT_LINE} from CLAUDE.md")
            if self._marker.exists():
                self._marker.unlink()
                changes.append(f"Deleted {_SUBTREE}/enabled")
        except OSError as exc:
            return self._report(
                "disable", tuple(changes), error=str(exc), reason=type(exc).__name__
            )
        return self._report("disable", tuple(changes))
