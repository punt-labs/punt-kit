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
        assert rules.pruned(Tier.DENY).to_strings() == ["Edit(.env)", "Bash(git:*)"]

    def test_deny_orphan_is_rewritten(self) -> None:
        """A guard that never worked is repaired — tightening is safe."""
        rules = RuleSet.from_strings(["Write(*prfaq*.tex)", "Bash(git:*)"])
        assert rules.pruned(Tier.DENY).to_strings() == [
            "Edit(*prfaq*.tex)",
            "Bash(git:*)",
        ]

    def test_ask_orphan_is_rewritten(self) -> None:
        rules = RuleSet.from_strings(["Write(docs/**)"])
        assert rules.pruned(Tier.ASK).to_strings() == ["Edit(docs/**)"]

    def test_allow_orphan_is_dropped_not_rewritten(self) -> None:
        """Cleanup must never activate a grant that never worked."""
        rules = RuleSet.from_strings(["Write(*prfaq*.tex)", "Bash(git:*)"])
        assert rules.pruned(Tier.ALLOW).to_strings() == ["Bash(git:*)"]

    def test_allow_dead_rule_with_twin_is_dropped(self) -> None:
        rules = RuleSet.from_strings(["Edit(a.txt)", "Write(a.txt)"])
        assert rules.pruned(Tier.ALLOW).to_strings() == ["Edit(a.txt)"]

    def test_pruning_never_widens_any_tier(self) -> None:
        """No tier may gain a rule that was not already live in the input."""
        raw = ["Write(a.txt)", "Edit(b.txt)", "Glob(c/**)", "Bash(git:*)"]
        live_before = {r for r in raw if not PermissionRule(r).is_dead}
        allow = set(RuleSet.from_strings(raw).pruned(Tier.ALLOW).to_strings())
        assert allow <= live_before

    def test_pruned_preserves_order(self) -> None:
        rules = RuleSet.from_strings(
            ["Bash(git:*)", "Write(a.txt)", "Read(/tmp/**)", "Edit(b.txt)"]
        )
        assert rules.pruned(Tier.DENY).to_strings() == [
            "Bash(git:*)",
            "Edit(a.txt)",
            "Read(/tmp/**)",
            "Edit(b.txt)",
        ]

    def test_pruned_collapses_duplicate_dead_rules(self) -> None:
        rules = RuleSet.from_strings(["Write(a.txt)", "MultiEdit(a.txt)"])
        assert rules.pruned(Tier.DENY).to_strings() == ["Edit(a.txt)"]

    def test_allow_collapses_duplicate_dead_rules_to_nothing(self) -> None:
        rules = RuleSet.from_strings(["Write(a.txt)", "MultiEdit(a.txt)"])
        assert rules.pruned(Tier.ALLOW).to_strings() == []

    def test_pruned_is_idempotent(self) -> None:
        rules = RuleSet.from_strings(["Edit(.env)", "Write(.env)", "Glob(src/**)"])
        once = rules.pruned(Tier.DENY)
        assert once.pruned(Tier.DENY).to_strings() == once.to_strings()

    def test_clean_set_is_unchanged(self) -> None:
        raw = ["Edit(.env)", "Read(/tmp/**)", "Bash(git:*)", "WebSearch"]
        rules = RuleSet.from_strings(raw)
        assert rules.dead == ()
        assert rules.pruned(Tier.DENY).to_strings() == raw

    def test_empty_set(self) -> None:
        rules = RuleSet.from_strings([])
        assert rules.dead == ()
        assert rules.pruned(Tier.DENY).to_strings() == []


class TestTier:
    def test_allow_does_not_rewrite_orphans(self) -> None:
        assert not Tier.ALLOW.rewrites_orphans

    @pytest.mark.parametrize("tier", [Tier.DENY, Tier.ASK])
    def test_restrictive_tiers_rewrite_orphans(self, tier: Tier) -> None:
        assert tier.rewrites_orphans

    def test_values_match_settings_json_keys(self) -> None:
        assert [t.value for t in Tier] == ["allow", "deny", "ask"]
