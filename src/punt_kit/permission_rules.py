"""Classification of Claude Code permission rules.

Claude Code matches path-scoped permission rules under two tool names only:
``Read(path)`` and ``Edit(path)``. ``Edit`` covers every file-editing tool
(Write, Edit, MultiEdit, NotebookEdit) and ``Read`` covers every file-reading
tool (Read, Glob). A rule written as ``Write(.env)`` therefore matches nothing
and emits a startup warning once per session, in every project that carries it:

    Permission allow rule (...): `Write(.env)` is not matched by file
    permission checks — only `Edit(path)` rules are. Use `Edit(.env)` instead
    (Edit rules cover all file-editing tools).

The warning is the whole cost — a dead rule grants nothing and blocks nothing,
so a dead ``deny`` rule is noise rather than an unenforced guard. The mapping
below mirrors the check in the Claude Code binary: the tool name selects the
live form, and a rule whose content carries the Bash prefix marker ``:*`` is
left alone because it is not a path rule at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import final

__all__ = ["PermissionRule", "RuleSet", "Tier"]

# Dead path-scoped tool name -> the tool name that actually matches.
_LIVE_FORM = {
    "Write": "Edit",
    "MultiEdit": "Edit",
    "NotebookEdit": "Edit",
    "Glob": "Read",
}

_RULE_PATTERN = re.compile(r"^(?P<tool>[A-Za-z_][A-Za-z0-9_]*)\((?P<content>.*)\)$")

# Bash prefix marker. A rule containing it is a command rule, not a path rule.
_BASH_PREFIX_MARKER = ":*"


class Tier(StrEnum):
    """A permission list in ``settings.json``.

    The tier decides what happens to a dead rule with no live twin, and the
    rule is the same one a careful operator would apply by hand: cleaning up
    dead config must never grant anything that was not already granted.
    """

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"

    @property
    def rewrites_orphans(self) -> bool:
        """Whether an orphan dead rule is rewritten rather than dropped.

        A dead ``allow`` rule grants nothing today. Rewriting it to the live
        form would *activate* a grant the user believes they already have —
        a silent widening of permissions during a cleanup. So allow-tier
        orphans are dropped and reported, and the user re-adds the live form
        if they meant it.

        A dead ``deny`` or ``ask`` rule blocks or prompts for nothing today,
        so rewriting it can only tighten. That direction is safe to repair
        automatically.
        """
        return self is not Tier.ALLOW


@final
@dataclass(frozen=True, slots=True)
class PermissionRule:
    """One entry from a ``permissions.allow`` / ``.deny`` / ``.ask`` list."""

    text: str

    @property
    def tool(self) -> str:
        """The tool name, or ``""`` for a bare rule such as ``WebSearch``."""
        match = _RULE_PATTERN.match(self.text)
        return match.group("tool") if match else ""

    @property
    def content(self) -> str:
        """The parenthesised pattern, or ``""`` for a bare rule."""
        match = _RULE_PATTERN.match(self.text)
        return match.group("content") if match else ""

    @property
    def is_dead(self) -> bool:
        """True when Claude Code will never match this rule.

        A bare tool name (``Write``) is live — it gates the tool itself. Only
        the path-scoped form of a non-matching tool is dead.
        """
        match = _RULE_PATTERN.match(self.text)
        if match is None:
            return False
        if match.group("tool") not in _LIVE_FORM:
            return False
        return _BASH_PREFIX_MARKER not in match.group("content")

    @property
    def live_equivalent(self) -> PermissionRule:
        """The rule Claude Code would actually match.

        Returns ``self`` when the rule is already live, so callers can map over
        a mixed list without branching.
        """
        if not self.is_dead:
            return self
        return PermissionRule(f"{_LIVE_FORM[self.tool]}({self.content})")

    def __str__(self) -> str:
        return self.text


@final
@dataclass(frozen=True, slots=True)
class RuleSet:
    """An ordered permission list, as it appears in ``settings.json``."""

    rules: tuple[PermissionRule, ...]

    @classmethod
    def from_strings(cls, raw: list[str]) -> RuleSet:
        """Build a rule set from the raw JSON string list."""
        return cls(tuple(PermissionRule(text) for text in raw))

    @property
    def dead(self) -> tuple[PermissionRule, ...]:
        """Every rule that matches nothing, in list order."""
        return tuple(rule for rule in self.rules if rule.is_dead)

    def pruned(self, tier: Tier) -> RuleSet:
        """Remove every rule Claude Code cannot match.

        A dead rule whose live twin is already present is always dropped —
        the twin already carries its meaning. An orphan is dropped or
        rewritten according to ``tier.rewrites_orphans``, so the result is
        never more permissive than the input.
        """
        live_texts = {rule.text for rule in self.rules if not rule.is_dead}
        kept: list[PermissionRule] = []
        for rule in self.rules:
            if not rule.is_dead:
                kept.append(rule)
                continue
            replacement = rule.live_equivalent
            if replacement.text in live_texts or not tier.rewrites_orphans:
                continue
            live_texts.add(replacement.text)
            kept.append(replacement)
        return RuleSet(tuple(kept))

    def to_strings(self) -> list[str]:
        """Render back to the raw JSON string list."""
        return [rule.text for rule in self.rules]
