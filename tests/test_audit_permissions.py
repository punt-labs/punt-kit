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


def _write_baseline_plus(root: Path, extra: list[str]) -> None:
    info = detect(root)
    _write_settings(
        root,
        {
            "permissions": {
                "allow": [*build_standard_permissions(info), *extra],
                "deny": build_standard_deny_rules(),
            }
        },
    )


def test_missing_settings_json_fails_once(tmp_path: Path) -> None:
    assert _statuses(tmp_path) == [FAIL]


def test_the_baseline_alone_passes(tmp_path: Path) -> None:
    _write_baseline_plus(tmp_path, [])

    assert set(_statuses(tmp_path)) == {PASS}


def test_tool_owned_entries_are_allowed_and_never_required(tmp_path: Path) -> None:
    """vox's enable set may be present; the audit neither requires nor flags it."""
    _write_baseline_plus(tmp_path, ["mcp__plugin_vox_mic__*", "Skill(vox:recap)"])

    assert set(_statuses(tmp_path)) == {PASS}


@pytest.mark.parametrize("value", ["mcp__quarry__*", "mcp__vox__unmute"])
def test_a_direct_server_form_fails_naming_the_value(
    tmp_path: Path, value: str
) -> None:
    """A value starting mcp__ whose next segment is neither plugin_ nor github
    is a direct `claude mcp add` registration: a local choice that belongs in
    settings.local.json, never the checked-in file."""
    _write_baseline_plus(tmp_path, [value])

    failures = [
        detail
        for status, _label, detail in PermissionsAudit(detect(tmp_path)).findings()
        if status == FAIL
    ]

    assert len(failures) == 1
    assert value in failures[0]
    assert "settings.local.json" in failures[0]


def test_the_github_wildcard_is_not_a_direct_server_form(tmp_path: Path) -> None:
    _write_baseline_plus(tmp_path, ["mcp__github__get_me"])

    assert set(_statuses(tmp_path)) == {PASS}


def test_a_missing_github_wildcard_fails(tmp_path: Path) -> None:
    info = detect(tmp_path)
    _write_settings(
        tmp_path,
        {
            "permissions": {
                "allow": [
                    p for p in build_standard_permissions(info) if p != "mcp__github__*"
                ],
                "deny": build_standard_deny_rules(),
            }
        },
    )

    failures = [
        detail
        for status, _label, detail in PermissionsAudit(detect(tmp_path)).findings()
        if status == FAIL
    ]

    assert len(failures) == 1
    assert "mcp__github__*" in failures[0]


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
        "Bash(export -*)",
        "Bash(declare)",
        "Bash(declare -*)",
        "Bash(typeset)",
        "Bash(typeset -*)",
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
