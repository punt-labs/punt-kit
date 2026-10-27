"""Tests for the permissions findings of `punt audit`."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from punt_kit.audit_permissions import PermissionsAudit
from punt_kit.audit_verdict import FAIL, INFO, PASS
from punt_kit.detect import detect
from punt_kit.init import build_standard_deny_rules, build_standard_permissions

if TYPE_CHECKING:
    from pathlib import Path


def _write_settings(root: Path, settings: object) -> None:
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(settings))


def _statuses(root: Path) -> list[str]:
    return [
        status for status, _label, _detail in PermissionsAudit(detect(root)).findings()
    ]


def test_missing_settings_json_fails_once(tmp_path: Path) -> None:
    assert _statuses(tmp_path) == [FAIL]


def test_standard_permissions_pass(tmp_path: Path) -> None:
    info = detect(tmp_path)
    _write_settings(
        tmp_path,
        {
            "permissions": {
                "allow": build_standard_permissions(info),
                "deny": build_standard_deny_rules(),
            }
        },
    )

    assert set(_statuses(tmp_path)) == {PASS}


@pytest.mark.parametrize(
    "rule",
    [
        "Bash(env)",
        "Bash(env:*)",
        "Bash(printenv)",
        "Bash(printenv:*)",
        "Bash(set)",
        "Bash(export)",
        "Bash(export -:*)",
        "Bash(declare)",
        "Bash(declare -:*)",
        "Bash(typeset)",
        "Bash(typeset -:*)",
    ],
)
def test_a_missing_env_dump_deny_rule_fails(tmp_path: Path, rule: str) -> None:
    info = detect(tmp_path)
    _write_settings(
        tmp_path,
        {
            "permissions": {
                "allow": build_standard_permissions(info),
                "deny": [r for r in build_standard_deny_rules() if r != rule],
            }
        },
    )

    assert FAIL in _statuses(tmp_path)


def test_a_dead_rule_fails_and_an_unreadable_local_file_is_info(tmp_path: Path) -> None:
    info = detect(tmp_path)
    _write_settings(
        tmp_path,
        {
            "permissions": {
                "allow": build_standard_permissions(info),
                "deny": [*build_standard_deny_rules(), "Write(.env)"],
            }
        },
    )
    (tmp_path / ".claude" / "settings.local.json").write_text("{broken")

    statuses = _statuses(tmp_path)

    assert FAIL in statuses
    assert INFO in statuses
