"""Group the repository-configuration audits for `punt repo audit`.

The workflow guide, Claude permissions and ``.punt-labs`` layout audits read the
same configuration files, so the audit command asks for them as one group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.audit_guide import PuntGuideAudit
from punt_kit.audit_layout import LayoutAudit
from punt_kit.audit_permissions import PermissionsAudit

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_kit.detect import ProjectInfo

    Finding = tuple[str, str, str]


@final
class RepoConfigAudit:
    """Groups the audits of a repository's Claude and ``.punt-labs`` configuration."""

    __slots__ = ("_info",)

    _info: ProjectInfo

    def __new__(cls, info: ProjectInfo) -> Self:
        """Create the audit group for the repository described by ``info``."""
        self = super().__new__(cls)
        self._info = info
        return self

    def checks(self) -> tuple[Callable[[], list[Finding]], ...]:
        """Return each audit separately so one unreadable file fails only its own."""
        return (
            PuntGuideAudit(self._info).findings,
            PermissionsAudit(self._info).findings,
            LayoutAudit(self._info).findings,
        )
