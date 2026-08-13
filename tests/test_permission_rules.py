"""Tests for permission rule classification."""

from __future__ import annotations

import pytest

from punt_kit.permission_rules import PermissionRule, RuleSet, Tier


class TestPermissionRule:
    @pytest.mark.parametrize(
        "text",
        [
            "Write(.env)",
            "Write(*prfaq*.tex)",
            "MultiEdit(src/**)",
            "NotebookEdit(notebooks/**)",
            "Glob(src/**)",
        ],
    )
    def test_path_scoped_dead_forms(self, text: str) -> None:
        assert PermissionRule(text).is_dead

    @pytest.mark.parametrize(
        "text",
        [
            "Edit(.env)",
            "Read(/tmp/**)",
            "Bash(git:*)",
            "WebSearch",
            "mcp__plugin_biff_tty__*",
            # Bare tool names gate the tool itself — they match.
            "Write",
            "Glob",
        ],
    )
    def test_live_forms(self, text: str) -> None:
        assert not PermissionRule(text).is_dead

    def test_bash_prefix_marker_is_not_a_path_rule(self) -> None:
        """A rule carrying ``:*`` is a command rule; Claude Code leaves it be."""
        assert not PermissionRule("Write(npm run:*)").is_dead

    @pytest.mark.parametrize(
        ("dead", "live"),
        [
            ("Write(.env)", "Edit(.env)"),
            ("MultiEdit(src/**)", "Edit(src/**)"),
            ("NotebookEdit(nb/**)", "Edit(nb/**)"),
            ("Glob(src/**)", "Read(src/**)"),
        ],
    )
    def test_live_equivalent(self, dead: str, live: str) -> None:
        assert PermissionRule(dead).live_equivalent.text == live

    def test_live_equivalent_of_live_rule_is_itself(self) -> None:
        rule = PermissionRule("Edit(.env)")
        assert rule.live_equivalent == rule

    def test_tool_and_content_of_bare_rule(self) -> None:
        rule = PermissionRule("WebSearch")
        assert rule.tool == ""
        assert rule.content == ""

    def test_str_is_the_raw_text(self) -> None:
        assert str(PermissionRule("Edit(.env)")) == "Edit(.env)"


class TestRuleSet:
    def test_dead_lists_only_unmatched_rules(self) -> None:
        rules = RuleSet.from_strings(
            ["Edit(.env)", "Write(.env)", "Bash(git:*)", "Glob(src/**)"]
        )
        assert [str(r) for r in rules.dead] == ["Write(.env)", "Glob(src/**)"]

    def test_pruned_drops_dead_rule_with_live_twin(self) -> None:
        rules = RuleSet.from_strings(["Edit(.env)", "Write(.env)", "Bash(git:*)"])
        assert rules.pruned().to_strings() == ["Edit(.env)", "Bash(git:*)"]

    def test_orphan_is_dropped_never_rewritten(self) -> None:
        """A cleanup must not switch on a rule that has never been in effect."""
        rules = RuleSet.from_strings(["Write(*prfaq*.tex)", "Bash(git:*)"])
        assert rules.pruned().to_strings() == ["Bash(git:*)"]

    def test_pruning_never_changes_policy_in_either_direction(self) -> None:
        """The kept set is exactly the rules that were already live.

        Every rule removed was inert, and nothing live is added, so effective
        permissions are identical before and after — no grant switched on, no
        block switched on.
        """
        raw = ["Write(a.txt)", "Edit(b.txt)", "Glob(c/**)", "Bash(git:*)", "Write(d)"]
        live_before = [r for r in raw if not PermissionRule(r).is_dead]
        assert RuleSet.from_strings(raw).pruned().to_strings() == live_before

    def test_covered_and_orphans_partition_the_dead_set(self) -> None:
        rules = RuleSet.from_strings(["Edit(a)", "Write(a)", "Write(b)", "Bash(git:*)"])
        assert [str(r) for r in rules.covered] == ["Write(a)"]
        assert [str(r) for r in rules.orphans] == ["Write(b)"]
        assert len(rules.covered) + len(rules.orphans) == len(rules.dead)

    def test_pruned_preserves_order(self) -> None:
        rules = RuleSet.from_strings(
            ["Bash(git:*)", "Write(a.txt)", "Read(/tmp/**)", "Edit(b.txt)"]
        )
        assert rules.pruned().to_strings() == [
            "Bash(git:*)",
            "Read(/tmp/**)",
            "Edit(b.txt)",
        ]

    def test_duplicate_orphans_collapse_to_nothing(self) -> None:
        rules = RuleSet.from_strings(["Write(a.txt)", "MultiEdit(a.txt)"])
        assert rules.pruned().to_strings() == []

    def test_pruned_is_idempotent(self) -> None:
        rules = RuleSet.from_strings(["Edit(.env)", "Write(.env)", "Glob(src/**)"])
        once = rules.pruned()
        assert once.pruned().to_strings() == once.to_strings()

    def test_clean_set_is_unchanged(self) -> None:
        raw = ["Edit(.env)", "Read(/tmp/**)", "Bash(git:*)", "WebSearch"]
        rules = RuleSet.from_strings(raw)
        assert rules.dead == ()
        assert rules.pruned().to_strings() == raw

    def test_empty_set(self) -> None:
        rules = RuleSet.from_strings([])
        assert rules.dead == ()
        assert rules.pruned().to_strings() == []


class TestTier:
    def test_values_match_settings_json_keys(self) -> None:
        assert [t.value for t in Tier] == ["allow", "deny", "ask"]
