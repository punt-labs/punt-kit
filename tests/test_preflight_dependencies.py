"""Reject PyPI-incompatible dependencies before running release operations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from punt_kit.detect import ProjectInfo
from punt_kit.phases.phase01_preflight import Phase1Preflight
from punt_kit.phases.shared.errors import ReleaseError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "dependency",
    [
        "sample @ git+https://example.com/sample.git@abcdef",
        "sample[extra] @ https://example.com/sample.whl",
        "sample @ file:///local/sample",
        "sample @ git+ssh://git@example.com/sample.git",
        "sample @ https://example.com/sample.tar.gz ; python_version < '3.0'",
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_direct_references_fail_before_any_command(
    tmp_path: Path, dependency: str, dry_run: bool
) -> None:
    ops = MagicMock()
    ops.fail.side_effect = ReleaseError
    info = ProjectInfo(
        root=tmp_path,
        language="python",
        pyproject={"project": {"dependencies": ["rich>=13", dependency]}},
    )
    with pytest.raises(ReleaseError):
        Phase1Preflight(info, dry_run=dry_run, ops=ops).run()
    ops.fail.assert_called_once_with(
        "Direct URL dependency: publish sample to PyPI "
        "and pin a version before releasing"
    )
    ops.run.assert_not_called()


@pytest.mark.parametrize(
    "pyproject",
    [
        None,
        {},
        {"project": {}},
        {"project": {"dependencies": []}},
        {
            "project": {
                "dependencies": [
                    "rich>=13",
                    "sample[extra]==1.2; python_version >= '3.13'",
                ]
            }
        },
        {"dependency-groups": {"dev": ["sample @ https://example.com/sample.whl"]}},
    ],
)
def test_registry_and_empty_dependencies_reach_repository_checks(
    tmp_path: Path, pyproject: dict[str, object] | None
) -> None:
    ops = MagicMock()
    ops.run.return_value.stdout = "feature"
    ops.fail.side_effect = ReleaseError
    info = ProjectInfo(root=tmp_path, pyproject=pyproject)
    with pytest.raises(ReleaseError):
        Phase1Preflight(info, dry_run=False, ops=ops).run()
    ops.fail.assert_called_once_with("Must be on main branch (currently on 'feature')")
    ops.run.assert_called_once()


def test_invalid_requirement_fails_with_a_clear_remedy(tmp_path: Path) -> None:
    ops = MagicMock()
    ops.fail.side_effect = ReleaseError
    info = ProjectInfo(
        root=tmp_path, pyproject={"project": {"dependencies": ["not a requirement"]}}
    )
    with pytest.raises(ReleaseError):
        Phase1Preflight(info, dry_run=False, ops=ops).run()
    ops.fail.assert_called_once_with(
        "Invalid project dependency; fix [project].dependencies before releasing"
    )
    ops.run.assert_not_called()
