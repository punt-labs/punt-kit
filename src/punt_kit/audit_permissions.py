"""The permissions findings of `punt audit`: settings.json against the standard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.audit_verdict import FAIL, INFO, PASS
from punt_kit.init import build_standard_deny_rules, build_standard_permissions
from punt_kit.permission_rules import RuleSet, Tier
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.json_file import JsonFile

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo

    Finding = tuple[str, str, str]


@final
class PermissionsAudit:
    """Checks a project's ``.claude/settings.json`` and ``settings.local.json``."""

    __slots__ = ("_info",)

    _info: ProjectInfo

    def __new__(cls, info: ProjectInfo) -> Self:
        self = super().__new__(cls)
        self._info = info
        return self

    def findings(self) -> list[Finding]:
        """Check settings.json has the standard permissions for this project type."""
        info = self._info
        results: list[Finding] = []
        settings_path = info.root / ".claude" / "settings.json"

        if not settings_path.exists():
            results.append(
                (
                    FAIL,
                    ".claude/settings.json exists",
                    "Missing — run punt init",
                )
            )
            return results

        results.append((PASS, ".claude/settings.json exists", ""))

        try:
            typed_data = JsonFile(settings_path).load_object()
        except ReleaseError as exc:
            results.append((FAIL, "settings.json is valid JSON", str(exc)))
            return results

        perms_raw = typed_data.get("permissions")
        if not isinstance(perms_raw, dict):
            results.append((FAIL, "Standard permissions present", "No permissions key"))
            return results

        perms = cast("dict[str, object]", perms_raw)
        results.extend(self._dead_rule_findings(perms))

        allow_raw = perms.get("allow")
        if not isinstance(allow_raw, list):
            results.append(
                (FAIL, "Standard permissions present", "Missing allow array")
            )
            return results

        allow_strs = [str(x) for x in cast("list[object]", allow_raw)]

        standard = build_standard_permissions(info)
        missing = [p for p in standard if p not in allow_strs]

        if missing:
            results.append(
                (
                    FAIL,
                    "Standard allow rules present",
                    f"Missing {len(missing)}: {', '.join(missing[:5])}"
                    + ("..." if len(missing) > 5 else ""),
                )
            )
        else:
            results.append(
                (
                    PASS,
                    "Standard allow rules present",
                    f"{len(standard)} standard entries",
                )
            )

        # Check deny rules
        deny_raw = perms.get("deny")
        if not isinstance(deny_raw, list):
            results.append(
                (
                    FAIL,
                    "Standard deny rules present",
                    "Missing permissions.deny — run punt init",
                )
            )
            return results

        deny_strs = [str(x) for x in cast("list[object]", deny_raw)]
        standard_deny = build_standard_deny_rules()
        missing_deny = [r for r in standard_deny if r not in deny_strs]

        if missing_deny:
            results.append(
                (
                    FAIL,
                    "Standard deny rules present",
                    f"Missing {len(missing_deny)}: {', '.join(missing_deny[:5])}"
                    + ("..." if len(missing_deny) > 5 else ""),
                )
            )
        else:
            results.append(
                (
                    PASS,
                    "Standard deny rules present",
                    f"{len(standard_deny)} standard entries",
                )
            )

        return results

    @staticmethod
    def _dead_rules_in(perms: dict[str, object]) -> tuple[list[str], list[str]]:
        """Dead rules in a permissions block, split by whether init can fix them.

        ``punt init`` skips a tier holding a non-string entry rather than coerce it
        to its repr, so dead rules in such a tier need a hand edit. Reporting them
        all as "run punt init" would send the user round a loop that never
        converges.
        """
        fixable: list[str] = []
        manual: list[str] = []
        for tier in Tier:
            raw = perms.get(tier.value)
            if not isinstance(raw, list):
                continue
            entries = cast("list[object]", raw)
            texts = [str(x) for x in entries]
            dead = [str(rule) for rule in RuleSet.from_strings(texts).dead]
            if not dead:
                continue
            if all(isinstance(x, str) for x in entries):
                fixable.extend(dead)
            else:
                manual.extend(dead)
        return fixable, manual

    def _dead_rules_in_settings_local(self) -> tuple[list[str], list[str]]:
        """Dead rules in the gitignored local settings file.

        Claude Code warns for this file exactly as it does for the checked-in one,
        so the audit has to read both or it reports clean while the developer sees
        warnings every session. Raises :class:`ReleaseError` when the file exists
        but cannot be read as a JSON object.
        """
        settings_path = self._info.root / ".claude" / "settings.local.json"
        if not settings_path.exists():
            return ([], [])

        perms_raw = JsonFile(settings_path).load_object().get("permissions")
        if not isinstance(perms_raw, dict):
            return ([], [])

        return self._dead_rules_in(cast("dict[str, object]", perms_raw))

    @staticmethod
    def _dead_rule_remedy(fixable: list[str], manual: list[str]) -> str:
        """The advice that actually resolves the reported rules."""
        if not manual:
            return " — run punt init"
        if not fixable:
            return (
                " — edit by hand: the tier holds a non-string entry, so init skips it"
            )
        return (
            f" — run punt init; {len(manual)} sit in a tier with a non-string"
            " entry and need a hand edit"
        )

    def _dead_rule_findings(self, perms: dict[str, object]) -> list[Finding]:
        """Flag path rules Claude Code never matches (permissions.md §1).

        An unreadable ``settings.local.json`` is a personal file, so it does not
        fail the audit; it is reported as INFO so the check is never silently
        narrowed to the one file that parsed.
        """
        settings_fixable, settings_manual = self._dead_rules_in(perms)
        notes: list[Finding] = []
        try:
            local_fixable, local_manual = self._dead_rules_in_settings_local()
        except ReleaseError as exc:
            local_fixable, local_manual = [], []
            notes.append((INFO, "settings.local.json could not be checked", str(exc)))
        fixable = settings_fixable + local_fixable
        manual = settings_manual + local_manual
        dead = fixable + manual

        if not dead:
            return [
                (PASS, "No unmatched path rules", "Edit(path) / Read(path) only"),
                *notes,
            ]

        return [
            (
                FAIL,
                "No unmatched path rules",
                f"{len(dead)} never match: {', '.join(dead[:5])}"
                + ("..." if len(dead) > 5 else "")
                + self._dead_rule_remedy(fixable, manual),
            ),
            *notes,
        ]
