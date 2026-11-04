"""Phase 10e: regenerate the project's Homebrew formula in the homebrew-tap."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.project_remote import ProjectRemote
from punt_kit.phases.shared.siblings import SiblingRepo
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

TAP_SIBLING = "homebrew-tap"
BREW_TARGET = "brew-formula"

_BREW_TARGET = re.compile(rf"^{re.escape(BREW_TARGET)}[ \t]*:", re.MULTILINE)


def has_brew_formula_target(root: Path) -> bool:
    """True when ``root``'s Makefile declares a ``brew-formula`` target."""
    makefile = root / "Makefile"
    return makefile.is_file() and bool(_BREW_TARGET.search(TextFile(makefile).read()))


def tap_sibling(info: ProjectInfo, *, ops: ReleaseOps) -> SiblingRepo | None:
    """The tap checkout, when this project regenerates a formula into it.

    That takes a ``brew-formula`` Makefile target and a sibling tap checkout.
    The tap is optional, like the website: an absent one is not a failure.
    """
    if not has_brew_formula_target(info.root):
        return None
    return SiblingRepo.resolve(info.root, TAP_SIBLING, ops=ops)


def tap_formula(tap: SiblingRepo, formula: str) -> Path | None:
    """``Formula/<formula>.rb`` in ``tap``, when the tap already carries it."""
    path = tap.path / "Formula" / f"{formula}.rb"
    return path if path.is_file() else None


@final
class HomebrewTapPropagator:
    """10e. Regenerates Formula/<name>.rb in homebrew-tap through the project's
    own ``make brew-formula FORMULA_OUT=<path>``, with a CHANGELOG line."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        self._skips = skips
        return self

    def run(
        self,
        version: str,
        *,
        dry_run: bool,
        merge_sibling: Callable[..., bool],
    ) -> None:
        info = self._info
        ops = self._ops
        tap_repo = tap_sibling(info, ops=ops)
        if tap_repo is None:
            ops.info(
                f"No {BREW_TARGET} target or no {TAP_SIBLING} sibling "
                "— skipping homebrew-tap update"
            )
            return
        slug = ProjectRemote(
            info.root, ops=ops, skips=self._skips, step="homebrew-tap propagation"
        ).slug()
        if slug is None:
            return
        name = slug.name
        formula = tap_formula(tap_repo, name)
        if formula is None:
            ops.info(f"{TAP_SIBLING} has no Formula/{name}.rb — skipping")
            return

        tap = tap_repo.path
        out = f"../{TAP_SIBLING}/Formula/{formula.name}"
        if dry_run:
            ops.dry(f"make -C {info.root.name} {BREW_TARGET} FORMULA_OUT={out}")
            ops.dry(f"../{TAP_SIBLING}/CHANGELOG.md: {name}: bump to v{version}")
            return

        tap_repo.validate()

        made = ops.run(
            ["make", "-C", str(info.root), BREW_TARGET, f"FORMULA_OUT={out}"],
            check=False,
            capture=False,
            timeout=UV,
        )
        if made.returncode != 0:
            ops.fail(f"make {BREW_TARGET} failed for {name} — see output above")

        files = [f"Formula/{formula.name}"]
        if (tap / "CHANGELOG.md").is_file():
            if Changelog(tap, ops=ops).add_unreleased_entry(
                f"{name}: bump to v{version}"
            ):
                files.append("CHANGELOG.md")
            else:
                self._skips.record(
                    f"SKIPPED — manual action required: ../{TAP_SIBLING}/CHANGELOG.md "
                    f"has no [Unreleased] section, so '{name}: bump to v{version}' "
                    "was not recorded. Add it manually."
                )

        branch = f"propagate/v{version}-{name}-{TAP_SIBLING}"
        if merge_sibling(
            tap,
            branch,
            files,
            f"chore: bump {name} to v{version}",
            TAP_SIBLING,
            dry_run=dry_run,
        ):
            ops.ok(f"homebrew-tap: {name} v{version}")
        else:
            ops.ok(f"homebrew-tap: {name} already current")
