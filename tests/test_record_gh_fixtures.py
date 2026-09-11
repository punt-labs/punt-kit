"""Tests for the read-only ``gh``-fixture recorder (tools/record_gh_fixtures.py).

The load-bearing property this file exists to prove: the tool is
*structurally* incapable of mutating anything, not merely disciplined about
it. ``ReadOnlyGhRunner`` refuses a command before ``subprocess.run`` is ever
reached (proven here by making a real dispatch a hard test failure), and the
full recording-command inventory ``GhRecordingPlan`` can ever generate is
checked against the same allowlist offline, with no live ``gh`` session
needed to prove it.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from tools.record_gh_fixtures import (
    DiscoveredTargets,
    GhFixtureDriftChecker,
    GhFixtureRecorder,
    GhRecordingPlan,
    GhSanitizer,
    GhTargetDiscovery,
    ReadOnlyGhRunner,
    ReadOnlyViolation,
    RepoContext,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_TARGETS = DiscoveredTargets(
    open_pr=1,
    open_pr_branch="feature/open",
    merged_pr=2,
    merged_pr_branch="feature/merged",
    closed_pr=3,
    closed_pr_branch="feature/closed",
    missing_branch="feature/missing",
    run_id=999,
    tag="v1.2.3",
    missing_tag="v0.0.0-missing",
)


def _never_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test immediately if ``subprocess.run`` is ever reached —
    the read-only check must always run first.
    """

    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run was reached — the read-only guard failed")

    monkeypatch.setattr("subprocess.run", fail)


# ---------------------------------------------------------------------------
# ReadOnlyGhRunner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        ["gh", "--version"],
        ["gh", "pr", "list", "--repo", "acme/sample"],
        ["gh", "pr", "view", "1", "--json", "state"],
        ["gh", "run", "list", "--workflow", "release.yml"],
        ["gh", "run", "view", "1", "--json", "status,conclusion"],
        ["gh", "release", "view", "v1.0.0"],
        ["gh", "api", "repos/acme/sample/branches/main/protection"],
        ["gh", "api", "repos/acme/sample/rules/branches/main"],
        ["gh", "api", "graphql", "-f", "query={ viewer { login } }"],
        ["/usr/bin/gh", "pr", "list"],  # basename match, absolute path
    ],
)
def test_require_read_only_accepts_the_documented_shapes(cmd: list[str]) -> None:
    ReadOnlyGhRunner().require_read_only(cmd)  # must not raise


@pytest.mark.parametrize(
    "cmd",
    [
        ["gh", "pr", "merge", "1", "--squash"],
        ["gh", "pr", "create", "--title", "x"],
        ["gh", "pr", "close", "1"],
        ["gh", "release", "create", "v1.0.0"],
        ["gh", "api", "repos/acme/sample/pulls/1/merge", "-X", "PUT"],
        ["gh", "api", "repos/acme/sample/pulls/1", "--method", "DELETE"],
        [
            "gh",
            "api",
            "graphql",
            "-f",
            'query=mutation { resolveReviewThread(input: {threadId: "x"}) '
            "{ thread { isResolved } } }",
        ],
        ["gh", "api", "orgs/acme/members"],  # not a repos/... or graphql endpoint
        # gh api defaults to POST once a field is present, with no -X
        # required to trigger it — refused outright on a REST endpoint.
        ["gh", "api", "repos/acme/sample/branches/main/protection", "-f", "x=1"],
        ["not-gh", "pr", "list"],
    ],
)
def test_require_read_only_refuses_every_mutating_shape(cmd: list[str]) -> None:
    with pytest.raises(ReadOnlyViolation):
        ReadOnlyGhRunner().require_read_only(cmd)


def test_run_never_dispatches_a_refused_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_dispatch(monkeypatch)

    with pytest.raises(ReadOnlyViolation):
        ReadOnlyGhRunner().run(["gh", "pr", "merge", "1", "--squash"])


def test_run_dispatches_an_allowed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    result = ReadOnlyGhRunner().run(["gh", "pr", "list", "--repo", "acme/sample"])

    assert result.stdout == "ok"


# ---------------------------------------------------------------------------
# GhRecordingPlan — the full command inventory, offline
# ---------------------------------------------------------------------------


def test_every_planned_recording_command_is_read_only() -> None:
    """No network access needed to prove this: ``GhRecordingPlan`` only ever
    builds argv lists from already-discovered targets, so the full
    recording inventory can be validated against the read-only allowlist
    without a live ``gh`` session.
    """
    repo = RepoContext.parse("acme/sample")
    plan = GhRecordingPlan(repo=repo, targets=_TARGETS)
    runner = ReadOnlyGhRunner()

    recordings = plan.recordings()
    assert recordings, "the plan produced no recordings at all"
    for recording in recordings:
        runner.require_read_only(recording.command)  # must not raise


def test_recording_plan_names_are_unique() -> None:
    repo = RepoContext.parse("acme/sample")
    plan = GhRecordingPlan(repo=repo, targets=_TARGETS)

    names = [r.name for r in plan.recordings()]

    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# RepoContext
# ---------------------------------------------------------------------------


def test_repo_context_parses_owner_and_name() -> None:
    repo = RepoContext.parse("acme/sample")

    assert repo.owner == "acme"
    assert repo.name == "sample"
    assert repo.slug == "acme/sample"


@pytest.mark.parametrize("slug", ["", "no-slash", "/missing-owner", "missing-name/"])
def test_repo_context_rejects_a_malformed_slug(slug: str) -> None:
    with pytest.raises(ValueError, match="owner/repo"):
        RepoContext.parse(slug)


# ---------------------------------------------------------------------------
# GhTargetDiscovery — read-only queries, offline via a fake runner
# ---------------------------------------------------------------------------


def test_discovery_reads_pr_and_run_state_via_read_only_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        if "pr" in cmd:
            payload = [
                {"number": 1, "state": "OPEN", "headRefName": "feature/open"},
                {"number": 2, "state": "MERGED", "headRefName": "feature/merged"},
                {"number": 3, "state": "CLOSED", "headRefName": "feature/closed"},
            ]
        else:
            payload = [
                {
                    "databaseId": 999,
                    "headBranch": "v1.2.3",
                    "event": "push",
                    "headSha": "a" * 40,
                    "conclusion": "success",
                }
            ]
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    discovery = GhTargetDiscovery(
        runner=ReadOnlyGhRunner(), repo=RepoContext.parse("acme/sample")
    )

    targets = discovery.discover()

    assert targets.open_pr == 1
    assert targets.merged_pr == 2
    assert targets.closed_pr == 3
    assert targets.run_id == 999
    assert targets.tag == "v1.2.3"
    assert len(calls) == 2  # exactly the two listing calls, nothing else
    for call in calls:
        ReadOnlyGhRunner().require_read_only(call)  # must not raise


def test_discovery_raises_when_a_required_state_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout="[]", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    discovery = GhTargetDiscovery(
        runner=ReadOnlyGhRunner(), repo=RepoContext.parse("acme/sample")
    )

    with pytest.raises(LookupError, match="OPEN"):
        discovery.discover()


# ---------------------------------------------------------------------------
# GhSanitizer
# ---------------------------------------------------------------------------


def test_sanitizer_redacts_a_github_token() -> None:
    sanitizer = GhSanitizer()

    out = sanitizer.sanitize("token ghp_" + "a" * 36 + " end")

    assert "ghp_" not in out
    assert "REDACTED_TOKEN" in out


def test_sanitizer_redacts_an_email_address() -> None:
    sanitizer = GhSanitizer()

    out = sanitizer.sanitize("contact operator@example.org for help")

    assert "operator@example.org" not in out
    assert "user@example.com" in out


def test_sanitizer_scrubs_identity_fields_in_json() -> None:
    sanitizer = GhSanitizer()
    raw = json.dumps({"login": "realuser123", "count": 3})

    out = json.loads(sanitizer.sanitize(raw))

    assert out["login"] == "redacted-user"
    assert out["count"] == 3


def test_sanitizer_leaves_non_json_text_alone_after_redaction() -> None:
    sanitizer = GhSanitizer()

    out = sanitizer.sanitize("release not found\n")

    assert out == "release not found\n"


# ---------------------------------------------------------------------------
# GhFixtureRecorder — writes a sanitized envelope
# ---------------------------------------------------------------------------


def test_recorder_writes_a_sanitized_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.record_gh_fixtures import FixtureRecording

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["gh", "--version"]:
            return subprocess.CompletedProcess(
                args=list(cmd), returncode=0, stdout="gh version 2.100.0\n", stderr=""
            )
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=json.dumps([{"login": "realuser", "state": "OPEN"}]),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    recorder = GhFixtureRecorder(
        runner=ReadOnlyGhRunner(), sanitizer=GhSanitizer(), dest=tmp_path
    )
    recording = FixtureRecording(
        name="example.json", command=("gh", "pr", "list"), note="a test recording"
    )

    written = recorder.record_all((recording,))

    assert written == [tmp_path / "example.json"]
    envelope = json.loads((tmp_path / "example.json").read_text())
    assert envelope["returncode"] == 0
    assert json.loads(envelope["stdout"]) == [
        {"login": "redacted-user", "state": "OPEN"}
    ]
    assert envelope["_meta"]["hand_authored"] is False
    assert envelope["_meta"]["command"] == ["gh", "pr", "list"]
    assert envelope["_meta"]["gh_version"] == "gh version 2.100.0"


# ---------------------------------------------------------------------------
# GhFixtureDriftChecker
# ---------------------------------------------------------------------------


def _write_envelope(
    path: Path, *, hand_authored: bool, command: list[str] | None, stdout: str
) -> None:
    envelope = {
        "returncode": 0,
        "stdout": stdout,
        "stderr": "",
        "_meta": {
            "gh_version": "gh version 2.100.0",
            "recorded_at": "2026-01-01",
            "command": command,
            "hand_authored": hand_authored,
            "note": "",
        },
    }
    path.write_text(json.dumps(envelope))


def test_drift_checker_skips_hand_authored_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _never_dispatch(monkeypatch)
    _write_envelope(
        tmp_path / "hand.json", hand_authored=True, command=None, stdout="{}"
    )

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert mismatches == []


def test_drift_checker_reports_no_mismatch_when_shape_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_envelope(
        tmp_path / "rec.json",
        hand_authored=False,
        command=["gh", "pr", "list"],
        stdout=json.dumps([{"number": 1, "state": "OPEN"}]),
    )

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=json.dumps([{"number": 99, "state": "MERGED"}]),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert mismatches == []


def test_drift_checker_reports_a_shape_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_envelope(
        tmp_path / "rec.json",
        hand_authored=False,
        command=["gh", "pr", "list"],
        stdout=json.dumps([{"number": 1, "state": "OPEN"}]),
    )

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        # A field was renamed live — this is the drift the check exists to
        # catch.
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=json.dumps([{"id": 1, "state": "OPEN"}]),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert len(mismatches) == 1
    assert "shape drifted" in mismatches[0]


def test_drift_checker_reports_a_success_failure_disagreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_envelope(
        tmp_path / "rec.json",
        hand_authored=False,
        command=["gh", "release", "view", "v1"],
        stdout="",
    )

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=1, stdout="", stderr="release not found\n"
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert len(mismatches) == 1
    assert "disagreement" in mismatches[0]
