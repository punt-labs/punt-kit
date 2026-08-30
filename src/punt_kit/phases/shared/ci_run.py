"""Selecting and watching the CI run a tag push triggered."""

from __future__ import annotations

import json
import subprocess
import time
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.timeouts import CI_ADVERSE_CONCLUSIONS, CI_RUN_LIST

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class TagRunSelector:
    """Picks the workflow run that one specific tag push triggered.

    Three predicates, each rejecting a distinct kind of wrong run.
    ``headBranch`` rejects a run belonging to a different tag. ``event``
    rejects a manual dispatch rather than the tag push. ``headSha`` rejects a
    run left on the remote by an earlier tag of the same name pointing at a
    different commit, which is what a delete-and-recreate leaves behind. A run
    passing all three either is this push's run or ran against identical code,
    so its verdict is this release's verdict either way.

    There is deliberately no fallback to "some other recent run". A wait that
    cannot find its run has learned nothing about the release, and reporting a
    result the tag never earned is worse than stopping.
    """

    __slots__ = ("_commit", "_tag")

    _commit: str
    _tag: str

    def __new__(cls, tag: str, commit: str) -> Self:
        self = super().__new__(cls)
        self._tag = tag
        self._commit = commit
        return self

    @classmethod
    def list_command(cls, gh: str, tag: str) -> list[str]:
        """The gh invocation listing the runs worth considering for ``tag``.

        ``--branch`` filters by ref server-side, so the list holds only this
        tag's runs. Without it the limit is a truncation risk: enough
        unrelated releases between a failure and a ``--resume-from ci`` retry
        would push the target run off the end, which reads identically to the
        tag never having triggered CI.

        Built here rather than at the call site so the dry run prints the
        command the real run executes, instead of a paraphrase that can drift.
        """
        return [
            gh,
            "run",
            "list",
            "--workflow",
            "release.yml",
            "--branch",
            tag,
            "--limit",
            "20",
            "--json",
            "databaseId,headBranch,event,headSha,conclusion",
        ]

    def describe_misses(self, runs: Sequence[Mapping[str, object]]) -> str:
        """Name the runs that were seen and rejected, and why.

        ``list_command`` filters by ref, so every run offered here already
        belongs to this tag. A non-match therefore means a commit or trigger
        mismatch — never that the tag failed to trigger CI. Reporting what was
        rejected turns the phase's most misleading message into its most
        useful one: a delete-and-recreate leaves a run at the old commit, and
        its conclusion is usually the fact the operator most needs.
        """
        seen: list[str] = []
        for run in runs:
            if self.matches(run):
                continue
            sha = run.get("headSha")
            where = sha[:8] if isinstance(sha, str) else "an unknown commit"
            conclusion = run.get("conclusion") or "still running"
            seen.append(f"a {run.get('event')} run at {where} ({conclusion})")
        if not seen:
            return ""
        return f"{'; '.join(seen)}, but the local tag is at {self._commit[:8]}"

    def matches(self, run: Mapping[str, object]) -> bool:
        """True when ``run`` was triggered by this tag at this commit."""
        return (
            run.get("headBranch") == self._tag
            and run.get("event") == "push"
            and run.get("headSha") == self._commit
        )

    def run_id(self, run: Mapping[str, object]) -> int:
        """Return the run's numeric id, or raise when the payload lacks one."""
        candidate = run.get("databaseId")
        if not isinstance(candidate, int):
            msg = f"CI run for {self._tag} has no usable databaseId: {run!r}"
            raise ReleaseError(msg)
        return candidate

    def poll(
        self,
        list_runs: Callable[[], Sequence[Mapping[str, object]]],
        *,
        attempts: int,
        interval: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Return this tag's run id, waiting for the run to appear.

        Raises ``ReleaseError`` when no run matches within ``attempts`` polls.
        """
        for attempt in range(1, attempts + 1):
            # gh lists runs newest first, so the first match is the most
            # recent attempt for this tag.
            for run in list_runs():
                if self.matches(run):
                    return self.run_id(run)
            if attempt < attempts:
                sleep(interval)
        # The loop sleeps between polls, not after the last one, so the time
        # actually spent waiting is one interval short of attempts * interval.
        # Formatted with :g rather than int() so a sub-second interval is not
        # truncated to a figure smaller than the wait actually performed.
        waited = (attempts - 1) * interval
        msg = (
            f"no release.yml run found for {self._tag} at {self._commit[:8]} "
            f"after {waited:g}s — the tag push may not have triggered CI"
        )
        raise ReleaseError(msg)


@final
class CiRunWatch:
    """Explains a ``gh run watch`` outcome without inventing a CI verdict."""

    __slots__ = ("_ops",)

    _ops: ReleaseOps

    def __new__(cls, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        return self

    def failure_message(self, gh: str, root: Path, run_id: int, returncode: int) -> str:
        """Explain a non-zero ``gh run watch`` without inventing a CI verdict.

        ``gh run watch`` exits non-zero when the run failed, but also when it
        cannot reach the run at all: a deleted run answers 404 and an expired
        token answers 401, both with the same exit code. Reporting either as
        "CI failed" sends the operator to a green run, from which the natural
        recovery is to resume past this phase — publishing to PyPI and
        propagating to the fleet with no CI verdict ever obtained.
        """
        # A verdict query that never answers leaves no conclusion, which is a
        # state this function already models — so None routes into the same
        # "could not confirm" path rather than escaping as TimeoutExpired.
        # The broken connection that made the watch exit non-zero is the
        # likeliest reason this call hangs too, so the failure-reporting
        # path must survive it; dying here would kill the diagnosis it was
        # written to produce.
        verdict: subprocess.CompletedProcess[str] | None
        try:
            verdict = self._ops.run(
                [gh, "run", "view", str(run_id), "--json", "status,conclusion"],
                cwd=str(root),
                check=False,
                timeout=CI_RUN_LIST,
            )
        except subprocess.TimeoutExpired:
            verdict = None
        conclusion = ""
        if verdict is not None and verdict.returncode == 0:
            try:
                parsed = json.loads(verdict.stdout)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                raw = cast("dict[str, object]", parsed).get("conclusion")
                conclusion = raw if isinstance(raw, str) else ""
        if conclusion in CI_ADVERSE_CONCLUSIONS:
            return f"CI run {run_id} concluded {conclusion} — fix before continuing"
        return (
            f"could not confirm CI run {run_id} passed: gh run watch exited "
            f"{returncode} and the run reports {conclusion or 'no conclusion'}. "
            f"Check the run itself — do not resume past this phase until it is green"
        )
