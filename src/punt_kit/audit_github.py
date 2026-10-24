"""The GitHub-side findings of `punt audit`: rulesets and Dependabot alerts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.audit_verdict import FAIL, INFO, PASS
from punt_kit.git_checkout import GitCheckout

if TYPE_CHECKING:
    from pathlib import Path

    Finding = tuple[str, str, str]

# The status line `gh api --include` prints first: ``HTTP/2.0 204 No Content``.
_HTTP_STATUS = re.compile(r"HTTP/\S+\s+(\d{3})")

# gh reports a failed request on stderr as ``gh: Not Found (HTTP 404)``.
_HTTP_NOT_FOUND = re.compile(r"\(HTTP 404\)")

_RULESET = "Branch protection ruleset exists"


@final
class GithubSettingsAudit:
    """Checks a repository's GitHub settings through the ``gh`` CLI."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    def findings(self) -> list[Finding]:
        """Check GitHub repo settings via gh API. Falls back gracefully."""
        gh = shutil.which("gh")
        if gh is None:
            return [
                (
                    INFO,
                    "GitHub settings (gh CLI not available)",
                    "Install gh to check remote settings",
                )
            ]
        # Detect repo from git remote — verify we're in a git repo rooted here
        try:
            repo = GitCheckout(self._root).github_slug()
        except ValueError as exc:
            return [(INFO, f"GitHub settings ({exc})", "")]
        # Branch protection via the rulesets API (not legacy branch protection)
        return [*self.rulesets(gh, repo), *self.dependabot_alerts(gh, repo)]

    def dependabot_alerts(self, gh: str, repo: str) -> list[Finding]:
        """Check Dependabot / vulnerability alerts from the HTTP status ``gh`` prints.

        ``gh api --include`` puts the status line first on stdout, even for an
        error status: 204 is enabled, 404 is not enabled, and anything else (a
        403, a 5xx, no status line at all) is a check that could not be made.
        """
        label = "Dependabot vulnerability alerts"
        try:
            result = subprocess.run(
                [
                    gh,
                    "api",
                    f"repos/{repo}/vulnerability-alerts",
                    "--include",
                    "-X",
                    "GET",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return [(INFO, label, f"could not check: {exc}")]
        code = status.group(1) if (status := _HTTP_STATUS.match(result.stdout)) else ""
        if code == "204":
            return [(PASS, label, "Enabled")]
        if code == "404":
            return [(FAIL, label, "Not enabled")]
        reason = result.stderr.strip() or f"HTTP status {code or 'unknown'}"
        return [(INFO, label, f"could not check: {reason}")]

    def rulesets(self, gh: str, repo: str) -> list[Finding]:
        """Check branch protection rulesets for the main branch."""
        listing = self._gh_json(
            gh,
            f"repos/{repo}/rulesets",
            not_found=(FAIL, _RULESET, "No rulesets or no access"),
            unreadable_label="Branch protection (could not check)",
        )
        if isinstance(listing, tuple):
            return [listing]
        if not isinstance(listing, list) or not listing:
            return [(FAIL, _RULESET, "No rulesets configured")]
        ruleset_id = self._ruleset_id(cast("list[object]", listing))
        if ruleset_id is None:
            return [(FAIL, _RULESET, "No ruleset found")]
        detail = self._gh_json(
            gh,
            f"repos/{repo}/rulesets/{ruleset_id}",
            not_found=(INFO, "Branch protection (could not read ruleset)", ""),
            unreadable_label="Branch protection (could not read ruleset)",
        )
        if isinstance(detail, tuple):
            return [detail]
        if not isinstance(detail, dict):
            return [(INFO, "Branch protection (unexpected response)", "")]
        ruleset = cast("dict[str, object]", detail)
        # Only an active ruleset protects anything: "evaluate" logs what it
        # would block and "disabled" blocks nothing, whatever rules it lists.
        enforcement = ruleset.get("enforcement")
        if enforcement != "active":
            state = enforcement if isinstance(enforcement, str) else "not reported"
            return [(FAIL, _RULESET, f"Ruleset enforcement is {state}, not active")]
        return [(PASS, _RULESET, ""), *self._rules_findings(ruleset)]

    @staticmethod
    def _gh_json(
        gh: str, endpoint: str, *, not_found: Finding, unreadable_label: str
    ) -> object | Finding:
        """The parsed JSON of ``gh api <endpoint>``, or the finding saying why not.

        ``not_found`` answers a definite HTTP 404. Any other way the answer
        could not be had (another status, a timeout, a missing ``gh``, a body
        that is not JSON) is an INFO finding labelled ``unreadable_label``
        that carries the reason: it says the check was not made, not that the
        repository is misconfigured. A tuple return is the finding (JSON has no
        tuples); any other return is the response.
        """
        try:
            result = subprocess.run(
                [gh, "api", endpoint], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return cast("object", json.loads(result.stdout))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            return (INFO, unreadable_label, f"could not check: {exc}")
        if _HTTP_NOT_FOUND.search(result.stderr):
            return not_found
        reason = result.stderr.strip() or f"gh exited {result.returncode}"
        return (INFO, unreadable_label, f"could not check: {reason}")

    @staticmethod
    def _ruleset_id(rulesets: list[object]) -> int | None:
        """The id of the "Protect main" ruleset (org convention), else the first."""
        entries = [
            cast("dict[str, object]", raw)
            for raw in rulesets
            if isinstance(raw, dict)
            and isinstance(cast("dict[str, object]", raw).get("id"), int)
        ]
        named = [e for e in entries if e.get("name", "") == "Protect main"]
        for entry in named or entries:
            return cast("int", entry["id"])
        return None

    @staticmethod
    def _rules_findings(ruleset: dict[str, object]) -> list[Finding]:
        """Bypass actors, PR rule, thread resolution, deletion and force-push rules."""
        bypass_raw = ruleset.get("bypass_actors", [])
        bypass = (
            cast("list[object]", bypass_raw) if isinstance(bypass_raw, list) else []
        )
        rules_raw = ruleset.get("rules", [])
        rules_list = (
            cast("list[object]", rules_raw) if isinstance(rules_raw, list) else []
        )
        rules = [
            cast("dict[str, object]", r) for r in rules_list if isinstance(r, dict)
        ]
        types = {r.get("type") for r in rules}

        thread_resolution = False
        for rule in rules:
            params = rule.get("parameters", {})
            if rule.get("type") == "pull_request" and isinstance(params, dict):
                thread_resolution = bool(
                    cast("dict[str, object]", params).get(
                        "required_review_thread_resolution"
                    )
                )

        def verdict(ok: bool, label: str, missing: str) -> Finding:
            return (PASS if ok else FAIL, label, "" if ok else missing)

        return [
            verdict(
                not bypass,
                "Ruleset: zero bypass actors",
                f"{len(bypass)} bypass actor(s) configured",
            ),
            verdict(
                "pull_request" in types, "Ruleset: PR required", "No pull_request rule"
            ),
            verdict(
                thread_resolution,
                "Ruleset: conversation resolution required",
                "required_review_thread_resolution is false",
            ),
            verdict(
                "deletion" in types,
                "Ruleset: branch deletion blocked",
                "No deletion rule",
            ),
            verdict(
                "non_fast_forward" in types,
                "Ruleset: force push blocked",
                "No non_fast_forward rule",
            ),
        ]
