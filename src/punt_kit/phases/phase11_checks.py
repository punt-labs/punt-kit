"""Phase 11's verdict type and the marketplace pin-chain check."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.phases.shared.entry_matcher import EntryMatcher
    from punt_kit.phases.shared.ops import ReleaseOps


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    """One named pass/fail verdict with a human-readable detail."""

    name: str
    passed: bool
    detail: str


@final
class MarketplacePinCheck:
    """Verifies the marketplace-pin chain for marketplace-only plugins.

    Used only when a project has no ``install.sh`` — the profile-SHA check
    has no direct install URL to verify against, so the pin chain (profile
    -> install-all.sh's claude-plugins SHA -> that commit's
    marketplace.json) is the equivalent invariant.

    ``matcher`` accepts the entry by its name or by a source URL for the
    same owner and repository. The caller builds it from the repository name
    (from the origin slug) and the marketplace short name (see
    ``ReleaseProject.marketplace_name``), not the PyPI distribution name:
    marketplace entries key on the plugin's short name (``punt``) while the
    CLI knows the project by the distribution name (``punt-kit``).
    """

    __slots__ = ("_matcher", "_ops", "_tag", "_version")

    _matcher: EntryMatcher
    _version: str
    _tag: str
    _ops: ReleaseOps

    def __new__(
        cls, matcher: EntryMatcher, version: str, tag: str, *, ops: ReleaseOps
    ) -> Self:
        self = super().__new__(cls)
        self._matcher = matcher
        self._version = version
        self._tag = tag
        self._ops = ops
        return self

    def run(
        self,
        # Absent is a real answer: the claude-plugins sibling is not checked out.
        cp_sibling: Path | None,
        claude_plugins_sha: str,
    ) -> tuple[bool, str]:
        """Check a pinned claude-plugins commit's marketplace.json for this project.

        Returns ``(passed, detail)``.
        """
        if cp_sibling is None:
            return False, "claude-plugins sibling not found"
        show = self._ops.run(
            ["git", "show", f"{claude_plugins_sha}:.claude-plugin/marketplace.json"],
            cwd=str(cp_sibling),
            check=False,
        )
        if show.returncode != 0:
            return False, f"claude-plugins@{claude_plugins_sha} does not resolve"
        data = cast("dict[str, object]", json.loads(show.stdout.removeprefix("\ufeff")))
        plugins = cast("list[dict[str, object]]", data.get("plugins", []))
        for p in plugins:
            if self._matcher.claims_plugin(p):
                src = cast("dict[str, str]", p.get("source", {}))
                ok = (
                    str(p.get("version", "")) == self._version
                    and str(src.get("ref", "")) == self._tag
                )
                return (
                    ok,
                    f"claude-plugins@{claude_plugins_sha} version={p.get('version')}, "
                    f"ref={src.get('ref')}",
                )
        names = ",".join(sorted(self._matcher.names)) or "?"
        return (
            False,
            f"claude-plugins@{claude_plugins_sha} has no entry for {names}",
        )
