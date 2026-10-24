"""A profile pin Phase 10 cannot update is a recorded skip, matching Phase 11."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_kit.detect import detect
from punt_kit.phases.phase10_propagate import InstallAllPropagator
from punt_kit.phases.shared.skips import SkipRecorder
from tests.helpers import (
    fault_ops,
    git_out,
    make_sibling,
    project_with_origin,
)

if TYPE_CHECKING:
    from pathlib import Path


def _never_merge(*_args: object, **_kwargs: object) -> bool:
    raise AssertionError("a pin that is already current opens no PR")


def _install_all_sibling(tmp_path: Path, files: dict[str, str]) -> None:
    """A project whose .github sibling pins the project install.sh."""
    info = project_with_origin(tmp_path)
    install_sha = git_out(
        ["log", "-1", "--format=%h", "--", "install.sh"], cwd=str(info.root)
    )
    make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/proj/{install_sha}/install.sh" | sh\n'
            ),
            **files,
        },
    )


def _run(tmp_path: Path) -> tuple[str, ...]:
    ops = fault_ops()
    skips = SkipRecorder(ops=ops)
    InstallAllPropagator(detect(tmp_path / "proj"), ops=ops, skips=skips).run(
        "0.2.0", dry_run=False, merge_sibling=_never_merge
    )
    return tuple(skips.drain())


def test_a_missing_profile_readme_is_a_skip_with_the_manual_fix(
    tmp_path: Path,
) -> None:
    _install_all_sibling(tmp_path, {})

    (notice,) = _run(tmp_path)

    assert "profile/README.md" in notice
    assert "manual action required" in notice


def test_a_profile_without_an_install_all_reference_is_a_skip(
    tmp_path: Path,
) -> None:
    _install_all_sibling(tmp_path, {"profile/README.md": "no pin here\n"})

    (notice,) = _run(tmp_path)

    assert "no install-all.sh SHA reference" in notice
    assert "manual action required" in notice
