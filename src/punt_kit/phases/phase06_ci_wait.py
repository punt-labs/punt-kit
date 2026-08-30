"""Phase 6: wait for the tag-triggered CI run to pass."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.ci_run import CiRunWatch, TagRunSelector
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.timeouts import CI_RUN_LIST, CI_WATCH

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase6CiWait:
    """Phase 6: wait for CI."""

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls, info: ProjectInfo, version: str, *, dry_run: bool, ops: ReleaseOps
    ) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        return self

    def run(self, *, poll_attempts: int, poll_interval: float) -> None:
        """``poll_attempts``/``poll_interval`` are injected rather than read
        from ``phases.shared.timeouts`` directly — many tests monkeypatch
        ``punt_kit.release._CI_RUN_POLL_ATTEMPTS``/``_CI_RUN_POLL_INTERVAL``
        and call ``punt_kit.release._phase6_ci_wait`` expecting the patch to
        shrink the poll window to a test-speed budget.
        """
        info = self._info
        version = self._version
        ops = self._ops
        _console.print("\n[bold]Phase 6: Wait for CI[/bold]")

        if "release.yml" not in info.workflow_files:
            if info.is_plugin and not info.is_hybrid:
                ops.ok("No release.yml workflow — pure plugin, nothing to wait for")
                return
            ops.fail(
                "Expected .github/workflows/release.yml for this project but none "
                "was found — this is a misconfiguration, not a plugin-only skip "
                f"(workflows present: {info.workflow_files or 'none'})"
            )

        tag = f"v{version}"

        if self._dry_run:
            ops.dry(" ".join(TagRunSelector.list_command("gh", tag)))
            ops.dry(f"gh run watch <run-id matching {tag}> --exit-status")
            return

        gh = shutil.which("gh")
        if gh is None:
            ops.fail("gh CLI not found — install from https://cli.github.com")

        # Resolve the tag to a commit so the run's headSha can be checked
        # against it. Annotated tags need the ^{commit} peel; lightweight
        # tags ignore it.
        peel = ops.run(
            ["git", "rev-parse", f"{tag}^{{commit}}"], cwd=str(info.root), check=False
        )
        if peel.returncode != 0:
            ops.fail(f"Cannot resolve {tag} to a commit — is the tag fetched locally?")
        commit = peel.stdout.strip()

        selector = TagRunSelector(tag, commit)
        ops.info(f"Looking for the release.yml run for {tag} ({commit[:8]})...")

        list_cmd = TagRunSelector.list_command(gh, tag)
        # A gh failure must not masquerade as "no run yet", and a lookup
        # that never happened must not be silently dropped from the
        # account. Counting both outcomes keeps the two facts separable: a
        # blip after clean polls is not "gh never worked", and 23 failures
        # after one success is not "no run".
        gh_ok = 0
        gh_failed = 0
        last_gh_error = ""
        latest: Sequence[Mapping[str, object]] = ()

        def list_runs() -> Sequence[Mapping[str, object]]:
            nonlocal gh_ok, gh_failed, last_gh_error, latest
            try:
                result = ops.run(
                    list_cmd,
                    cwd=str(info.root),
                    check=False,
                    timeout=CI_RUN_LIST,
                )
            except subprocess.TimeoutExpired:
                # A listing that hangs is a lookup that did not happen, not
                # a reason to end the release in a traceback. Polling
                # already tolerates a failed lookup, so route it there.
                gh_failed += 1
                last_gh_error = f"gh run list timed out after {CI_RUN_LIST}s"
                return ()
            if result.returncode != 0:
                gh_failed += 1
                last_gh_error = result.stderr.strip() or "gh run list failed"
                return ()
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                # A zero exit with unparseable stdout is still a failed
                # lookup. Letting the decode error escape would bypass both
                # fail sites and end the release in a traceback instead of
                # a diagnosis.
                gh_failed += 1
                last_gh_error = f"gh run list returned unparseable JSON: {exc}"
                return ()
            # Valid JSON of the wrong shape is the same problem one step
            # later: gh reports errors as an object, and casting one to a
            # run sequence would surface as a TypeError from inside poll
            # rather than a diagnosis.
            if not isinstance(parsed, list) or not all(
                isinstance(run, dict) for run in cast("list[object]", parsed)
            ):
                gh_failed += 1
                last_gh_error = (
                    f"gh run list returned an unexpected JSON shape: "
                    f"{result.stdout.strip()[:200]}"
                )
                return ()
            gh_ok += 1
            latest = cast("Sequence[Mapping[str, object]]", parsed)
            return latest

        try:
            run_id = selector.poll(
                list_runs,
                attempts=poll_attempts,
                interval=poll_interval,
            )
        except ReleaseError as exc:
            if gh_ok == 0:
                ops.fail(f"gh run list never succeeded: {last_gh_error}")
            reasons = [str(exc)]
            # Failed lookups shrink the real search budget, so say how many
            # there were. Silence here reads as "we looked 24 times and
            # found nothing".
            if gh_failed:
                reasons.append(
                    f"{gh_failed} of {gh_ok + gh_failed} lookups failed "
                    f"({last_gh_error})"
                )
            # Every run in the list is already this tag's, so a near-miss
            # is the most useful thing phase 6 knows — and the thing that
            # contradicts "the tag push may not have triggered CI".
            if misses := selector.describe_misses(latest):
                reasons.append(f"saw {misses}")
            ops.fail("; ".join(reasons))

        ops.info(f"Watching run {run_id}...")

        try:
            result = ops.run(
                [gh, "run", "watch", str(run_id), "--exit-status"],
                cwd=str(info.root),
                check=False,
                capture=False,
                timeout=CI_WATCH,
            )
        except subprocess.TimeoutExpired:
            # The pypi job gates on a manually-approved environment, so a
            # release left overnight can outlast the watch while the run
            # is perfectly healthy. Dying in a traceback here tells the
            # operator nothing about which of those two happened.
            ops.fail(
                f"stopped watching run {run_id} after "
                f"{CI_WATCH // 3600}h — it may still be waiting for the "
                f"release environment approval. Check the run, then "
                f"--resume-from github-release once it is green"
            )
        if result.returncode != 0:
            ops.fail(
                CiRunWatch(ops=ops).failure_message(
                    gh, info.root, run_id, result.returncode
                )
            )
        ops.ok("CI passed")
