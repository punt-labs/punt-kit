"""Phase 11's verdict type and the marketplace-pin chain check."""

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

    @classmethod
    def matches_install_sha(
        cls,
        name: str,
        pinned_sha: str,
        install_sha: str,
        *,
        cwd: Path,
        ops: ReleaseOps,
    ) -> Self:
        """Verify a pinned SHA resolves to the CURRENT install.sh commit.

        Ancestry alone (is the pin reachable from the tag?) is not enough: a
        previous release's install.sh commit is itself an ancestor of every
        later tag, so an ancestor-only check would pass the exact rot this
        exists to catch — Phase 9/10 left the pin one release behind.

        A textual prefix match (``pinned_sha.startswith(install_sha)``) is
        not enough either: it treats an unresolved string as commit
        identity, so a fabricated or nonexistent hash that merely starts
        with the right characters — or a real but unrelated commit that
        happens to share the short prefix — would pass without ever being
        resolved. Both ``install_sha`` and ``pinned_sha`` are resolved to
        full commit object IDs via ``git rev-parse <sha>^{commit}`` and
        compared for equality, so a valid abbreviated or full pin of the
        right commit passes, and an arbitrary/nonexistent hash fails.
        """
        expected = ops.run(
            ["git", "rev-parse", f"{install_sha}^{{commit}}"],
            cwd=str(cwd),
            check=False,
        )
        if expected.returncode != 0:
            # install_sha comes from a fresh git log on the caller's own
            # repo, so it always resolves — a failure here is a genuine git
            # error, not a stale pin, and must not be misreported as one.
            return cls(
                name,
                False,
                f"SHA={pinned_sha} (git error resolving expected commit "
                f"{install_sha}: {expected.stderr.strip()})",
            )
        resolved = ops.run(
            ["git", "rev-parse", f"{pinned_sha}^{{commit}}"],
            cwd=str(cwd),
            check=False,
        )
        if resolved.returncode != 0:
            return cls(name, False, f"SHA={pinned_sha} (does not resolve to a commit)")
        current = resolved.stdout.strip() == expected.stdout.strip()
        detail = (
            f"SHA={pinned_sha}"
            if current
            else f"SHA={pinned_sha} (stale — expected {install_sha})"
        )
        return cls(name, current, detail)


@final
class MarketplacePinCheck:
    """Verifies the marketplace-pin chain for marketplace-only plugins.

    Used only when a project has no ``install.sh`` — the profile-SHA check
    has no direct install URL to verify against, so the pin chain (profile
    -> install-all.sh's claude-plugins SHA -> that commit's
    marketplace.json) is the equivalent invariant.
    """

    __slots__ = ()

    def run(
        self,
        cp_sibling: Path | None,
        claude_plugins_sha: str,
        matcher: EntryMatcher,
        version: str,
        tag: str,
        *,
        ops: ReleaseOps,
    ) -> tuple[bool, str]:
        """Check a pinned claude-plugins commit's marketplace.json for this project.

        ``matcher`` accepts the entry by its name or by a source URL for the
        same owner and repository — the caller supplies both the PyPI
        distribution name and the marketplace short name (see
        ``ReleaseProject.marketplace_name``), since marketplace entries key on
        the plugin's short name (``punt``) while the CLI knows the project by
        the pyproject distribution name (``punt-kit``).

        Returns ``(passed, detail)``.
        """
        if cp_sibling is None:
            return False, "claude-plugins sibling not found"
        show = ops.run(
            ["git", "show", f"{claude_plugins_sha}:.claude-plugin/marketplace.json"],
            cwd=str(cp_sibling),
            check=False,
        )
        if show.returncode != 0:
            return False, f"claude-plugins@{claude_plugins_sha} does not resolve"
        data = cast("dict[str, object]", json.loads(show.stdout))
        plugins = cast("list[dict[str, object]]", data.get("plugins", []))
        for p in plugins:
            if matcher.claims_plugin(p):
                src = cast("dict[str, str]", p.get("source", {}))
                ok = (
                    str(p.get("version", "")) == version
                    and str(src.get("ref", "")) == tag
                )
                return (
                    ok,
                    f"claude-plugins@{claude_plugins_sha} version={p.get('version')}, "
                    f"ref={src.get('ref')}",
                )
        names = ",".join(sorted(matcher.names)) or "?"
        return (
            False,
            f"claude-plugins@{claude_plugins_sha} has no entry for {names}",
        )
