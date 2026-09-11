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

import inspect
import json
import subprocess
from pathlib import Path
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


_PROTECTION_ENDPOINT = "repos/acme/sample/branches/main/protection"
_MERGE_ENDPOINT = "repos/acme/sample/pulls/1/merge"


@pytest.mark.parametrize(
    "cmd",
    [
        ["gh", "--version"],
        ["gh", "pr", "list", "--repo", "acme/sample"],
        ["gh", "pr", "view", "1", "--json", "state"],
        ["gh", "run", "list", "--workflow", "release.yml"],
        ["gh", "run", "view", "1", "--json", "status,conclusion"],
        ["gh", "run", "watch", "1", "--exit-status"],
        ["gh", "release", "view", "v1.0.0"],
        ["gh", "api", _PROTECTION_ENDPOINT],
        ["gh", "api", "repos/acme/sample/rules/branches/main"],
        ["gh", "api", "graphql", "-f", "query={ viewer { login } }"],
        ["/usr/bin/gh", "pr", "list"],  # basename match, absolute path
        # A non-mutating method, in every spelling, must still be accepted —
        # the read-only check keys off the *verb*, not the flag's presence.
        ["gh", "api", _PROTECTION_ENDPOINT, "-X", "GET"],
        ["gh", "api", _PROTECTION_ENDPOINT, "-XGET"],
        ["gh", "api", _PROTECTION_ENDPOINT, "-X=GET"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--method", "GET"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--method=GET"],
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
        ["gh", "api", "orgs/acme/members"],  # not a repos/... or graphql endpoint
        ["not-gh", "pr", "list"],
        # -X/--method, every spelling gh's own pflag parser accepts
        # identically: split, equals-form, and (for -X) attached-form.
        ["gh", "api", _MERGE_ENDPOINT, "-X", "PUT"],
        ["gh", "api", _MERGE_ENDPOINT, "-XPUT"],
        ["gh", "api", _MERGE_ENDPOINT, "-X=PUT"],
        ["gh", "api", _MERGE_ENDPOINT, "--method", "DELETE"],
        ["gh", "api", _MERGE_ENDPOINT, "--method=DELETE"],
        # -f/-F/--field/--raw-field on a REST endpoint, every spelling.
        ["gh", "api", _PROTECTION_ENDPOINT, "-f", "x=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "-fx=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--field", "x=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--field=x=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "-F", "x=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "-Fx=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--raw-field", "x=1"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--raw-field=x=1"],
        # --input supplies an opaque request body this tool cannot inspect —
        # refused unconditionally, on both endpoint shapes, every spelling.
        ["gh", "api", _PROTECTION_ENDPOINT, "--input", "payload.json"],
        ["gh", "api", _PROTECTION_ENDPOINT, "--input=payload.json"],
        ["gh", "api", "graphql", "--input", "payload.json"],
        ["gh", "api", "graphql", "--input=payload.json"],
        # gh's key=@filename field convention is the same opaque-body
        # problem reached through -f/-F instead of --input — a query
        # loaded this way never appears as argv text at all.
        ["gh", "api", "graphql", "-f", "query=@payload.graphql"],
        ["gh", "api", "graphql", "-F", "query=@payload.graphql"],
        ["gh", "api", "graphql", "--field", "query=@payload.graphql"],
        ["gh", "api", "graphql", "-fquery=@payload.graphql"],
        # A GraphQL mutation, split-token query text.
        [
            "gh",
            "api",
            "graphql",
            "-f",
            'query=mutation { resolveReviewThread(input: {threadId: "x"}) '
            "{ thread { isResolved } } }",
        ],
    ],
)
def test_require_read_only_refuses_every_mutating_shape(cmd: list[str]) -> None:
    with pytest.raises(ReadOnlyViolation):
        ReadOnlyGhRunner().require_read_only(cmd)


def test_require_read_only_uses_the_last_of_two_method_flags() -> None:
    """``gh``'s pflag parser applies last-occurrence-wins for a repeated or
    dual-spelled option — a harmless leading ``-X GET`` must not shadow a
    later, real ``--method POST``.
    """
    with pytest.raises(ReadOnlyViolation, match="POST"):
        ReadOnlyGhRunner().require_read_only(
            ["gh", "api", _MERGE_ENDPOINT, "-X", "GET", "--method", "POST"]
        )


def test_require_read_only_accepts_a_safe_method_after_a_repeated_flag() -> None:
    """The mirror case: the *last* occurrence is the safe one, so the call
    must be accepted — proving the fix checks the last occurrence
    specifically, not just "any occurrence is mutating."
    """
    ReadOnlyGhRunner().require_read_only(
        [
            "gh",
            "api",
            _PROTECTION_ENDPOINT,
            "--method",
            "POST",
            "--method",
            "GET",
        ]
    )  # must not raise — GET is the effective, last-wins method


def test_read_only_gh_runner_has_no_configurable_allowlist() -> None:
    """The read-only allowlist is not a constructor parameter — an
    injectable allowlist would let a caller construct a
    ``ReadOnlyGhRunner`` that accepts a mutating shape, making the class's
    entire safety claim caller-configurable instead of structural.
    """
    parameters = inspect.signature(ReadOnlyGhRunner).parameters
    assert "allowlist" not in parameters


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


def test_discovery_skips_a_workflow_dispatch_run_for_the_tag_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``release.yml`` commonly also permits ``workflow_dispatch`` — a
    manually re-run entry can be newer than the actual tag push. Recording
    from it would produce a ``gh_run_list_matching_tag`` fixture that fails
    to ``match()`` the ``TagRunSelector`` it exists to feed, since
    ``TagRunSelector.matches`` rejects any non-``push`` event outright.
    """

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "pr" in cmd:
            payload = [
                {"number": 1, "state": "OPEN", "headRefName": "feature/open"},
                {"number": 2, "state": "MERGED", "headRefName": "feature/merged"},
                {"number": 3, "state": "CLOSED", "headRefName": "feature/closed"},
            ]
        else:
            payload = [
                {
                    "databaseId": 111,
                    "headBranch": "main",
                    "event": "workflow_dispatch",
                    "headSha": "b" * 40,
                    "conclusion": "success",
                },
                {
                    "databaseId": 999,
                    "headBranch": "v1.2.3",
                    "event": "push",
                    "headSha": "a" * 40,
                    "conclusion": "success",
                },
            ]
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    discovery = GhTargetDiscovery(
        runner=ReadOnlyGhRunner(), repo=RepoContext.parse("acme/sample")
    )

    targets = discovery.discover()

    assert targets.run_id == 999
    assert targets.tag == "v1.2.3"


def test_discovery_raises_when_only_dispatch_runs_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "pr" in cmd:
            payload = [
                {"number": 1, "state": "OPEN", "headRefName": "feature/open"},
                {"number": 2, "state": "MERGED", "headRefName": "feature/merged"},
                {"number": 3, "state": "CLOSED", "headRefName": "feature/closed"},
            ]
        else:
            payload = [
                {
                    "databaseId": 111,
                    "headBranch": "main",
                    "event": "workflow_dispatch",
                    "headSha": "b" * 40,
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

    with pytest.raises(LookupError, match="push-triggered"):
        discovery.discover()


def test_discovery_skips_a_failed_or_in_progress_push_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The newest push run can itself have failed, or still be running.
    Recording from either would write failure/incomplete data into
    fixtures named and documented as the healthy-run case
    (``gh_run_view_success.json``, ``gh_run_watch_healthy.json``), and
    ``gh run watch`` against a still-running run blocks until it finishes
    rather than a recording pass ever wanting to wait that out.
    """

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "pr" in cmd:
            payload = [
                {"number": 1, "state": "OPEN", "headRefName": "feature/open"},
                {"number": 2, "state": "MERGED", "headRefName": "feature/merged"},
                {"number": 3, "state": "CLOSED", "headRefName": "feature/closed"},
            ]
        else:
            payload = [
                {
                    "databaseId": 222,
                    "headBranch": "v1.2.4",
                    "event": "push",
                    "headSha": "c" * 40,
                    "conclusion": None,  # still running
                },
                {
                    "databaseId": 111,
                    "headBranch": "v1.2.3-rc",
                    "event": "push",
                    "headSha": "b" * 40,
                    "conclusion": "failure",
                },
                {
                    "databaseId": 999,
                    "headBranch": "v1.2.3",
                    "event": "push",
                    "headSha": "a" * 40,
                    "conclusion": "success",
                },
            ]
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    discovery = GhTargetDiscovery(
        runner=ReadOnlyGhRunner(), repo=RepoContext.parse("acme/sample")
    )

    targets = discovery.discover()

    assert targets.run_id == 999
    assert targets.tag == "v1.2.3"


def test_discovery_raises_when_no_push_run_ever_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "pr" in cmd:
            payload = [
                {"number": 1, "state": "OPEN", "headRefName": "feature/open"},
                {"number": 2, "state": "MERGED", "headRefName": "feature/merged"},
                {"number": 3, "state": "CLOSED", "headRefName": "feature/closed"},
            ]
        else:
            payload = [
                {
                    "databaseId": 222,
                    "headBranch": "v1.2.4",
                    "event": "push",
                    "headSha": "c" * 40,
                    "conclusion": None,
                },
                {
                    "databaseId": 111,
                    "headBranch": "v1.2.3-rc",
                    "event": "push",
                    "headSha": "b" * 40,
                    "conclusion": "failure",
                },
            ]
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    discovery = GhTargetDiscovery(
        runner=ReadOnlyGhRunner(), repo=RepoContext.parse("acme/sample")
    )

    with pytest.raises(LookupError, match="successfully-completed"):
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


def test_sanitizer_recurses_into_a_nested_object_under_an_identity_key() -> None:
    """GitHub sometimes returns a whole object under an identity key
    (``"author": {"login": ..., "id": ...}``) rather than a bare string.
    Blanking the object wholesale would corrupt its shape — a dict
    replaced by a string — which would make ``GhFixtureDriftChecker``
    report a false "drift" the next time a live response happens to carry
    that shape. The nested ``login`` string must still be scrubbed.
    """
    sanitizer = GhSanitizer()
    raw = json.dumps({"author": {"login": "realuser123", "id": 42}, "count": 3})

    out = json.loads(sanitizer.sanitize(raw))

    assert out["author"] == {"login": "redacted-user", "id": 42}
    assert out["count"] == 3


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


def test_recorder_refuses_a_command_needing_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A branch/tag/PR-title argument copied from live GitHub data could in
    principle carry a token- or email-shaped substring. Silently storing a
    *sanitized* ``_meta.command`` would be worse than the leak it prevents:
    ``--check`` executes ``_meta.command`` as the live argv to replay, so a
    redacted branch name would make it target a different, likely
    nonexistent ref — reporting a wrong result instead of no longer
    validating anything real. Refusing to record the fixture at all is the
    only outcome that neither leaks the secret nor corrupts replay.
    """
    from tools.record_gh_fixtures import CommandNotReplayableError, FixtureRecording

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["gh", "--version"]:
            return subprocess.CompletedProcess(
                args=list(cmd), returncode=0, stdout="gh version 2.100.0\n", stderr=""
            )
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=0, stdout="[]", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    recorder = GhFixtureRecorder(
        runner=ReadOnlyGhRunner(), sanitizer=GhSanitizer(), dest=tmp_path
    )
    leaky_branch = "release/" + "ghp_" + "a" * 36
    recording = FixtureRecording(
        name="example.json",
        command=("gh", "pr", "list", "--head", leaky_branch),
        note="",
    )

    # The exception message must never reproduce the raw secret — an
    # operator could paste an uncaught traceback somewhere without
    # noticing what it still contains — so this asserts the *absence* of
    # the leaky substring, not a match against it.
    with pytest.raises(CommandNotReplayableError, match="argv position") as excinfo:
        recorder.record_all((recording,))

    assert "ghp_" not in str(excinfo.value)
    assert not (tmp_path / "example.json").exists()


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


def test_drift_checker_skips_hand_authored_fixtures_alongside_a_real_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-authored fixture contributes no mismatches and triggers no
    live call — proven here alongside a recorded fixture that genuinely is
    replayed live, so the hand-authored one is demonstrably skipped rather
    than the whole check trivially passing because nothing ran at all.
    """
    _write_envelope(
        tmp_path / "hand.json", hand_authored=True, command=None, stdout="{}"
    )
    _write_envelope(
        tmp_path / "rec.json",
        hand_authored=False,
        command=["gh", "pr", "list"],
        stdout=json.dumps([{"number": 1, "state": "OPEN"}]),
    )
    calls: list[list[str]] = []

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=json.dumps([{"number": 1, "state": "OPEN"}]),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert mismatches == []
    assert calls == [["gh", "pr", "list"]]  # only the recorded fixture was replayed


def test_drift_checker_fails_loud_when_every_fixture_is_hand_authored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A destination holding only hand-authored envelopes must not report
    'no drift' — every file is skipped, zero live commands ever run, and
    that is the same vacuous-pass shape as an empty directory.
    """
    _never_dispatch(monkeypatch)
    _write_envelope(
        tmp_path / "hand.json", hand_authored=True, command=None, stdout="{}"
    )

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert len(mismatches) == 1
    assert "none were live-replayable" in mismatches[0]


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


def test_drift_checker_fails_loud_on_an_empty_destination(tmp_path: Path) -> None:
    """A missing or mistyped ``--dest`` makes the fixture-glob loop run
    zero times — the empty ``mismatches`` list this would otherwise
    produce is indistinguishable from a genuinely clean check to `main`'s
    caller, so the check must report a failure explicitly instead.
    """
    empty_dir = tmp_path / "does-not-exist"

    mismatches = GhFixtureDriftChecker(
        runner=ReadOnlyGhRunner(), dest=empty_dir
    ).check()

    assert len(mismatches) == 1
    assert "no fixture files found" in mismatches[0]


def test_drift_checker_preserves_distinct_shapes_in_a_heterogeneous_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GraphQL ``contexts`` list commonly mixes ``CheckRun`` and
    ``StatusContext`` nodes with different fields. Fingerprinting only the
    first element would let a change to the *other* shape go undetected —
    exactly the case this test drives: the recorded fixture's first
    element is unchanged, but the live response's second element gained an
    extra field, and that alone must still be reported as drift.
    """
    _write_envelope(
        tmp_path / "rec.json",
        hand_authored=False,
        command=["gh", "api", "graphql"],
        stdout=json.dumps([{"kind": "a"}, {"kind": "b"}]),
    )

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            # First element's shape is unchanged; the second gained a field.
            stdout=json.dumps([{"kind": "a"}, {"kind": "b", "extra": 1}]),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert len(mismatches) == 1
    assert "shape drifted" in mismatches[0]


def test_drift_checker_list_shape_is_order_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same two distinct element shapes, enumerated in a different
    order between the recorded fixture and the live response, must not
    read as drift — only the *set* of distinct shapes matters.
    """
    _write_envelope(
        tmp_path / "rec.json",
        hand_authored=False,
        command=["gh", "api", "graphql"],
        stdout=json.dumps([{"kind": "a"}, {"kind": "b", "extra": 1}]),
    )

    def fake_run(
        cmd: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=json.dumps([{"kind": "b", "extra": 1}, {"kind": "a"}]),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    mismatches = GhFixtureDriftChecker(runner=ReadOnlyGhRunner(), dest=tmp_path).check()

    assert mismatches == []


# ---------------------------------------------------------------------------
# main() — path display never crashes for a --dest outside the repo root
# ---------------------------------------------------------------------------


def test_display_path_uses_the_relative_form_inside_the_repo() -> None:
    from tools.record_gh_fixtures import (
        _ROOT,  # pyright: ignore[reportPrivateUsage]
        _display_path,  # pyright: ignore[reportPrivateUsage]
    )

    shown = _display_path(_ROOT / "tests" / "fixtures" / "gh" / "example.json")

    assert shown == Path("tests") / "fixtures" / "gh" / "example.json"


def test_display_path_falls_back_to_absolute_outside_the_repo(
    tmp_path: Path,
) -> None:
    from tools.record_gh_fixtures import (
        _display_path,  # pyright: ignore[reportPrivateUsage]
    )

    outside = tmp_path / "example.json"

    assert _display_path(outside) == outside
