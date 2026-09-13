"""Exhaustive ``--resume-from`` sweep across all 11 release phases.

One parametrized test, one case per resume point: drive ``run_release``
FRESH against a fully scripted release — real git repos for every git
question, ``FaultRule`` responses for every ``gh``/``uv``/PyPI boundary,
and the local GitHub emulation below for the few commands whose outcome
depends on run-time state — stop it during phase N by injecting the
failure a real stop produces on one of phase N's own commands, assert the
incomplete-release report names the phase and the exact ``--resume-from``
string, then re-run ``run_release --resume-from <name>`` against the
exact on-disk state the stopped run left behind and assert it completes
cleanly (docs/design-release-failure-harness.md §5 Wave 5, matrix row 53,
defect #7).

Two stop mechanisms, per the design's corrected two-path interrupt model
(§2c): phases that run synchronously on the main thread are stopped with
a ``KeyboardInterrupt`` whose construction also sets
``release._interrupted`` — exactly what ``run_release``'s signal handler
does atomically on a real Ctrl-C. Phases 9/10 run inside a
``ThreadPoolExecutor``, where a real signal's ``KeyboardInterrupt`` can
never be delivered (signals reach the main thread only), so injecting one
there would model a delivery that cannot physically happen; the realistic
in-worker stop is a raised ``ReleaseError``, and that is what those two
cases inject. The mid-poll interrupt path for a live worker is Wave 3's
coverage, not this sweep's.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast, final

import pytest

from punt_kit import release
from punt_kit.phases.shared.timeouts import DEFAULT_RUN
from punt_kit.release import (
    ReleaseError,
    _run,  # pyright: ignore[reportPrivateUsage]
    run_release,
)
from tests.harness.fault_ops import CompletedProcessSpec, FaultInjectingOps, FaultRule

# Shared scaffolding from the main release-test module — private there by
# test-helper convention, deliberately reused here rather than duplicated.
from tests.test_release import (
    _fake_get_github_repo,  # pyright: ignore[reportPrivateUsage]
    _git,  # pyright: ignore[reportPrivateUsage]
    _git_out,  # pyright: ignore[reportPrivateUsage]
    _make_release_project,  # pyright: ignore[reportPrivateUsage]
    _make_sibling,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import Self

_VERSION = "0.2.0"
_TAG = "v0.2.0"


@pytest.fixture(autouse=True)
def isolate_release_state() -> Iterator[None]:
    """Clear release.py's module-scoped state around every sweep case.

    ``release._skips`` and ``release._interrupted`` persist for the
    process; the fresh-run half of every case deliberately sets the
    interrupt event (or records skips), which must not leak into the next
    case — or into unrelated tests collected after this module.
    """
    release._skips.clear()  # pyright: ignore[reportPrivateUsage]
    release._interrupted.clear()  # pyright: ignore[reportPrivateUsage]
    yield
    release._skips.clear()  # pyright: ignore[reportPrivateUsage]
    release._interrupted.clear()  # pyright: ignore[reportPrivateUsage]


@final
class _SignalInterrupt(KeyboardInterrupt):
    """A ``KeyboardInterrupt`` that models ``run_release``'s signal handler.

    The real SIGINT handler does two things atomically: it sets
    ``release._interrupted`` and raises ``KeyboardInterrupt``. A
    ``FaultRule(raises=...)`` given this *type* (not an instance)
    reproduces both, because ``raise <class>`` instantiates the class at
    the raise site — ``__new__`` sets the event, then the raise proceeds
    with the event already set, exactly the state a phase observes when a
    real Ctrl-C lands mid-command.
    """

    def __new__(cls, *args: object) -> Self:
        release._interrupted.set()  # pyright: ignore[reportPrivateUsage]
        return super().__new__(cls, *args)


@dataclass(slots=True)
class _PrRecord:
    """One emulated pull request: its head branch, title, lifecycle state,
    and (once merged) the squash-merge commit's real sha. ``title`` backs
    the squash commit message in ``_pr_merge`` — real ``gh pr merge
    --squash`` (no ``--subject`` override) defaults the commit subject to
    the PR title plus a `` (#<number>)`` suffix, and Phase 5's
    release-commit fallback (phase05_tag.py) matches on exactly that
    shape. ``merge_sha`` backs ``gh pr view --json mergeCommit`` —
    ``PrMerger._merge_commit_oid``'s source of truth, independent of
    whatever local main HEAD becomes after later commits land."""

    branch: str
    state: str
    title: str
    merge_sha: str | None = None


@final
class _GithubSim:
    """Emulates GitHub's side of a release against the local git repos.

    Installed as ``FaultInjectingOps``'s ``real_run`` behind the explicit
    ``passthrough`` allowlist below — deny-by-default stays intact for
    everything else. A static ``FaultRule`` response cannot model these
    commands because their outcomes depend on state that only exists at
    run time:

    - ``gh pr list`` / ``gh pr create`` / ``gh pr view``: PR numbers and
      OPEN/MERGED states exist only after creation, tracked here per run.
    - ``gh pr merge --squash``: on real GitHub the squash commit lands on
      the remote main that later phases pull, tag, and verify. Emulated
      as a real local squash commit so every downstream artifact — the
      tag's commit, pyproject.toml on main, Phase 11's checks — is
      genuine git state rather than a scripted answer.
    - ``gh run list``: ``TagRunSelector`` accepts a run only when its
      ``headSha`` equals the commit the tag actually points at, which is
      the squash commit created above — unknowable before the run starts.
    - ``uv build``: Phase 3 requires artifacts on disk in ``dist/``
      afterward, not just a zero exit.
    """

    passthrough: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("gh", "pr", "list"),
        ("gh", "pr", "create"),
        ("gh", "pr", "view"),
        ("gh", "pr", "merge"),
        ("gh", "run", "list"),
        ("uv", "build"),
    )

    __slots__ = ("_lock", "_next_pr", "_prs")

    _lock: threading.Lock
    _next_pr: int
    _prs: dict[int, _PrRecord]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._next_pr = 1
        self._prs = {}
        return self

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        name = Path(cmd[0]).name
        if name == "git":
            return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)
        if cwd is None:
            raise AssertionError(f"emulated command needs a cwd: {cmd!r}")
        if name == "gh" and cmd[1:3] == ["pr", "list"]:
            return self._pr_list(cmd)
        if name == "gh" and cmd[1:3] == ["pr", "create"]:
            return self._pr_create(cmd)
        if name == "gh" and cmd[1:3] == ["pr", "view"]:
            return self._pr_view(cmd)
        if name == "gh" and cmd[1:3] == ["pr", "merge"]:
            return self._pr_merge(cmd, cwd)
        if name == "gh" and cmd[1:3] == ["run", "list"]:
            return self._run_list(cmd, cwd)
        if name == "uv" and cmd[1:2] == ["build"]:
            return self._uv_build(cmd, cwd)
        raise AssertionError(
            f"command routed to _GithubSim without an emulation: {cmd!r}"
        )

    @staticmethod
    def _flag(cmd: list[str], flag: str) -> str:
        return cmd[cmd.index(flag) + 1]

    @staticmethod
    def _done(cmd: list[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(cmd), 0, stdout=stdout, stderr="")

    def _pr_list(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        head = self._flag(cmd, "--head")
        with self._lock:
            rows: list[dict[str, object]] = [
                {"number": number, "state": record.state, "headRefOid": ""}
                for number, record in self._prs.items()
                if record.branch == head
            ]
        return self._done(cmd, json.dumps(rows))

    def _pr_create(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        head = self._flag(cmd, "--head")
        title = self._flag(cmd, "--title")
        with self._lock:
            number = self._next_pr
            self._next_pr += 1
            self._prs[number] = _PrRecord(branch=head, state="OPEN", title=title)
        return self._done(cmd, f"https://github.com/punt-labs/proj/pull/{number}\n")

    def _pr_view(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        number = int(cmd[3])
        with self._lock:
            record = self._prs[number]
        if "mergeCommit" in cmd:
            # `--jq .mergeCommit.oid` strips the JSON envelope on the real
            # `gh` CLI too — the raw oid is the whole stdout, not a field
            # inside a JSON blob.
            return self._done(cmd, f"{record.merge_sha}\n")
        return self._done(cmd, json.dumps({"state": record.state}))

    def _pr_merge(self, cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
        """Squash-merge the PR's branch into local main — the emulated
        counterpart of GitHub merging into the remote main that later
        phases pull, tag, and verify."""
        number = int(cmd[3])
        with self._lock:
            record = self._prs[number]
        _run(["git", "checkout", "main"], cwd=cwd)
        _run(["git", "merge", "--squash", record.branch], cwd=cwd)
        # Matches real `gh pr merge --squash` (no --subject override): the
        # commit subject defaults to the PR title plus " (#<number>)".
        _run(
            ["git", "commit", "-m", f"{record.title} (#{number})"],
            cwd=cwd,
        )
        merge_sha = _run(["git", "rev-parse", "HEAD"], cwd=cwd).stdout.strip()
        # --delete-branch: gh removes the head branch after the merge.
        _run(["git", "branch", "-D", record.branch], cwd=cwd)
        with self._lock:
            record.state = "MERGED"
            record.merge_sha = merge_sha
        return self._done(cmd)

    def _run_list(self, cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
        tag = self._flag(cmd, "--branch")
        sha = _run(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=cwd).stdout.strip()
        runs: list[dict[str, object]] = [
            {
                "databaseId": 1,
                "headBranch": tag,
                "event": "push",
                "headSha": sha,
                "conclusion": "success",
            }
        ]
        return self._done(cmd, json.dumps(runs))

    def _uv_build(self, cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
        dist = Path(cwd) / "dist"
        dist.mkdir(exist_ok=True)
        (dist / f"test_pkg-{_VERSION}-py3-none-any.whl").write_bytes(b"wheel")
        (dist / f"test_pkg-{_VERSION}.tar.gz").write_bytes(b"sdist")
        return self._done(cmd)


def _which_gh_only(name: str) -> str | None:
    """Which-stub: ``gh`` resolves; everything else is absent.

    Absence matters for ``test-cli``: Phase 8 only runs ``<cli> doctor``
    when the CLI resolves on PATH, and a blanket which-stub would route a
    fake doctor invocation into the deny-by-default router.
    """
    return "/usr/bin/gh" if name == "gh" else None


# One response body serving BOTH GraphQL consumers. RequiredChecksWaiter's
# checks query and PrThreadResolver's threads query share the argv prefix
# ["gh", "api", "graphql"] and differ only inside the "-f query=..."
# payload, which FaultRule's element-exact prefix matching cannot see — so
# one rule must answer both. Each consumer navigates only its own subtree:
# the waiter sees a single required check already passed, the resolver
# sees zero unresolved threads, and neither is order-sensitive.
_CHECKS_AND_THREADS_GRAPHQL = json.dumps(
    {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "statusCheckRollup": {
                                        "contexts": {
                                            "nodes": [
                                                {
                                                    "name": "ci",
                                                    "isRequired": True,
                                                    "conclusion": "success",
                                                    "status": "COMPLETED",
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        ]
                    },
                    "reviewThreads": {"nodes": []},
                }
            }
        }
    }
)


def _scripted_release_rules() -> list[FaultRule]:
    """The complete scripted boundary for one clean release run.

    Everything here is a command that would otherwise reach the network
    (the project's origin is a github.com URL, so pushes/pulls/fetches
    must not really run) or an external tool the test host cannot be
    assumed to have. Built fresh per run — rules carry consumed-count
    state.
    """
    ok = CompletedProcessSpec()
    return [
        FaultRule(match=["git", "fetch", "origin"], times=None, response=ok),
        FaultRule(match=["git", "pull"], times=None, response=ok),
        FaultRule(match=["git", "push"], times=None, response=ok),
        # Phase 1's five no-Makefile quality gates (ruff/format/mypy/
        # pyright/pytest) all arrive as `uv run ...`.
        FaultRule(match=["uv", "run"], times=None, response=ok),
        FaultRule(match=["uvx", "twine", "check"], times=None, response=ok),
        # Phase 8's PyPI install and its editable-restore share the prefix.
        FaultRule(match=["uv", "tool", "install"], times=None, response=ok),
        # Phase 11's index-presence resolve.
        FaultRule(match=["uv", "pip", "install"], times=None, response=ok),
        # The patched _get_github_repo answers "punt-labs/punt-kit" for
        # every check-wait, so both governance probes key on that slug.
        FaultRule(
            match=["gh", "api", "repos/punt-labs/punt-kit/branches/main/protection"],
            times=None,
            response=FaultRule.from_fixture("gh_api_branch_protection_protected.json"),
        ),
        FaultRule(
            match=["gh", "api", "repos/punt-labs/punt-kit/rules/branches/main"],
            times=None,
            response=FaultRule.from_fixture("gh_api_rules_branches_ungoverned.json"),
        ),
        FaultRule(
            match=["gh", "api", "graphql"],
            times=None,
            response=CompletedProcessSpec(stdout=_CHECKS_AND_THREADS_GRAPHQL),
        ),
        FaultRule(match=["gh", "run", "watch"], times=None, response=ok),
        # Phase 7's already-released short-circuit: view succeeds, so the
        # phase never reaches `gh release create`.
        FaultRule(
            match=["gh", "release", "view"],
            times=None,
            response=FaultRule.from_fixture("gh_release_view_exists.json"),
        ),
    ]


def _sweep_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A CLI-only python project plus a public-website sibling.

    CLI-only (the plugin surface is dropped) keeps Phase 4/9 off the
    plugin-swap scripts while still exercising the full PR-merge machinery
    twice — the release PR on the project and the propagation PR on the
    sibling. The origin is rewritten to a github.com URL *after* a final
    local fetch, so ``GithubRepo.resolve`` yields ``punt-labs/proj`` (the
    propagators and thread resolver require a resolvable slug) while
    ``refs/remotes/origin/main`` already equals HEAD for preflight's
    up-to-date diff; every command that would then touch that remote for
    real is scripted in ``_scripted_release_rules``.
    """
    root = _make_release_project(tmp_path)
    shutil.rmtree(root / ".claude-plugin")
    _git(["add", "-A"], cwd=str(root))
    _git(["commit", "-m", "drop plugin surface"], cwd=str(root))
    # Origin still points at the repo itself here — this refresh pins
    # refs/remotes/origin/main to the commit above before the URL rewrite
    # makes real fetches impossible.
    _git(["fetch", "origin"], cwd=str(root))
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=str(root),
    )

    projects: list[dict[str, str]] = [
        {"id": "proj", "version": "0.1.0", "githubUrl": ""}
    ]
    _make_sibling(
        tmp_path,
        "public-website",
        {"src/data/projects.json": json.dumps(projects, indent=2) + "\n"},
    )

    monkeypatch.setattr(shutil, "which", _which_gh_only)
    monkeypatch.setattr(release, "_get_github_repo", _fake_get_github_repo)
    return root


def _install_release_ops(
    monkeypatch: pytest.MonkeyPatch, rules: Sequence[FaultRule]
) -> None:
    """Route release.py's ``_run`` through a fresh router + GitHub emulation.

    A fresh ``_GithubSim`` per installation is deliberate: the fresh run
    and the resume run must not share PR-number state, exactly as a real
    resume happens in a new process. No case needs cross-run PR state —
    every PR is created and merged within a single phase execution, and a
    run that stopped before its PR was created re-creates it on resume.
    """
    sim = _GithubSim()
    ops = FaultInjectingOps(
        real_run=sim.run, rules=list(rules), passthrough=_GithubSim.passthrough
    )
    monkeypatch.setattr(release, "_run", ops.run)


@dataclass(frozen=True, slots=True)
class _ResumeCase:
    """One resume point: where the fresh run stops, and what that must report.

    ``anchor`` names a command of the stopped phase itself (the design's
    corrected model: a stop is a failure delivered to an in-flight
    ``ops.run`` call, never a between-phase event poll). Where the phase's
    literal first command's argv is also issued by an earlier phase, the
    anchor is the phase's first *distinctive* command instead — anchoring
    is by argv prefix, which cannot see phase context — except ``verify``,
    whose first command (``git tag --list v0.2.0``) has exactly one
    earlier occurrence (Phase 5's existing-tag probe), skipped by count.

    ``report_name``/``report_num`` are what the incomplete-release report
    must say. For ``propagate`` that is post-release, not propagate: a
    fresh run executes phases 9/10 as one concurrent pair, and the engine
    deliberately credits a mid-pair stop to the pair's entry point so the
    printed resume advice re-enters both (see ``_step9_10``); resuming
    from ``propagate`` is the operator narrowing that advice, and this
    case proves the narrower resume also completes cleanly.
    """

    resume_from: str
    anchor: tuple[str, ...]
    stop_phase: int
    report_name: str
    report_num: int
    anchor_skip: int = 0
    in_worker: bool = False


_CASES: tuple[_ResumeCase, ...] = (
    _ResumeCase("preflight", ("git", "branch", "--show-current"), 1, "preflight", 1),
    _ResumeCase("bump", ("git", "branch", "--list", "release/v0.2.0"), 2, "bump", 2),
    _ResumeCase("build", ("uv", "build"), 3, "build", 3),
    _ResumeCase(
        "release-pr",
        ("git", "push", "-u", "origin", "release/v0.2.0"),
        4,
        "release-pr",
        4,
    ),
    _ResumeCase("tag", ("git", "tag", "--list", "v0.2.0"), 5, "tag", 5),
    _ResumeCase("ci", ("git", "rev-parse", "v0.2.0^{commit}"), 6, "ci", 6),
    _ResumeCase(
        "github-release", ("gh", "release", "view", "v0.2.0"), 7, "github-release", 7
    ),
    _ResumeCase(
        "pypi",
        ("uv", "tool", "install", "--force", "--refresh", "test-pkg==0.2.0"),
        8,
        "pypi",
        8,
    ),
    _ResumeCase(
        "post-release",
        ("git", "branch", "--list", "post-release/v0.2.0"),
        9,
        "post-release",
        9,
        in_worker=True,
    ),
    _ResumeCase(
        "propagate",
        ("git", "status", "--porcelain", "--", "src/data/projects.json"),
        10,
        "post-release",
        9,
        in_worker=True,
    ),
    _ResumeCase(
        "verify", ("git", "tag", "--list", "v0.2.0"), 11, "verify", 11, anchor_skip=1
    ),
)


def test_interrupt_during_resumed_version_detection_reports_resume_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Ctrl-C in a resumed run's pre-pipeline window credits the phase
    the operator asked to resume from — not phase 0 ("unknown").

    A resume without ``--version`` runs ``_get_project_version`` before
    any pipeline step updates the phase tracker. Containing that window's
    interrupt in the incomplete-release path is only half the promise: a
    report that says "a phase could not be identified" with no
    ``--resume-from`` hint is not actionable. The pre-pipeline window is
    credited to the requested resume point, so the report hands back the
    exact command the operator already ran.
    """
    root = _sweep_project(tmp_path, monkeypatch)
    _install_release_ops(monkeypatch, _scripted_release_rules())

    def interrupted_version_lookup(_info: object) -> str:
        # The lookup itself is a pure file read for a python project (no
        # ops.run to anchor a FaultRule on), so the interrupt is injected
        # at the seam directly — same signal-handler shape as the sweep's
        # anchored stops.
        raise _SignalInterrupt

    monkeypatch.setattr(release, "_get_project_version", interrupted_version_lookup)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), dry_run=False, resume_from="ci")

    assert exc_info.value.code == 1
    out = " ".join(capsys.readouterr().out.split())
    assert "Release incomplete" in out
    assert "stopped during phase 6 (ci)" in out
    assert "--resume-from ci" in out
    assert "could not be identified" not in out
    assert "unknown" not in out


def test_sweep_covers_every_resume_point_exactly_once() -> None:
    """Adding a 12th phase must force a 12th sweep case, and vice versa.

    Compared against the canonical phase order (not ``PHASE_NAMES``, whose
    ``release`` alias maps to the same number as ``release-pr``), so the
    sweep's claim of exhaustiveness is enforced rather than asserted in
    prose.
    """
    assert [c.resume_from for c in _CASES] == list(
        release._PHASE_ORDER  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
    )


@pytest.mark.parametrize("case", _CASES, ids=[c.resume_from for c in _CASES])
def test_resume_from_every_phase_completes_a_genuinely_stopped_release(
    case: _ResumeCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every resume point recovers the exact state a real stop leaves.

    The post-stop on-disk state is never hand-built: the fresh run
    produces it by executing everything before the stop for real (real
    git commits, branches, tags, squash-merges) and dying on one of the
    stopped phase's own commands, the same way a signal or an in-phase
    failure lands.
    """
    root = _sweep_project(tmp_path, monkeypatch)
    sibling = tmp_path / "public-website"

    # In-worker phases get a ReleaseError (a real signal's
    # KeyboardInterrupt cannot be delivered to a pool thread); main-thread
    # phases get the signal handler's exact set-event-and-raise shape.
    stop: type[BaseException] | BaseException = (
        ReleaseError(f"injected stop during phase {case.stop_phase}")
        if case.in_worker
        else _SignalInterrupt
    )
    anchor = FaultRule(match=list(case.anchor), skip=case.anchor_skip, raises=stop)
    # Anchor first: several anchors are more-specific prefixes of a
    # scripted rule (e.g. the phase-4 push vs. the blanket push rule), and
    # the router consults rules in order.
    _install_release_ops(monkeypatch, [anchor, *_scripted_release_rules()])

    with pytest.raises(SystemExit) as stop_exc:
        run_release(str(root), version=_VERSION, dry_run=False)

    assert stop_exc.value.code == 1
    assert anchor._consumed == 1  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
    fresh_out = " ".join(capsys.readouterr().out.split())
    assert "Release incomplete" in fresh_out
    assert f"stopped during phase {case.report_num} ({case.report_name})" in fresh_out
    assert f"--resume-from {case.report_name}" in fresh_out

    # The stop landed where scripted: the tag is the run's first
    # irreversible artifact, so its presence cleanly splits the sweep.
    tag_after_stop = _git_out(["tag", "--list", _TAG], cwd=str(root))
    assert tag_after_stop == ("" if case.stop_phase <= 5 else _TAG)

    _install_release_ops(monkeypatch, _scripted_release_rules())
    run_release(
        str(root), version=_VERSION, dry_run=False, resume_from=case.resume_from
    )

    resumed_out = " ".join(capsys.readouterr().out.split())
    assert f"Release {_TAG} Complete" in resumed_out
    assert "Release incomplete" not in resumed_out

    # Pin WHICH commit the tag points at, not just that a tag named _TAG
    # exists — resolved independently of Phase5Tag's own resolution logic,
    # from the release PR's real squash-merge subject (title plus GitHub's
    # default " (#<number>)" suffix), so a broken Phase 4 -> Phase 5
    # threading regression can't hide behind Phase5Tag's git-history
    # fallback landing on the right commit by the same means it's meant to
    # verify.
    release_log = _git_out(["log", "--format=%H %s", "main"], cwd=str(root))
    release_sha = next(
        sha
        for sha, _, subject in (
            line.partition(" ") for line in release_log.splitlines()
        )
        if subject.startswith(f"chore: release v{_VERSION}")
    )
    assert _git_out(["rev-parse", f"{_TAG}^{{commit}}"], cwd=str(root)) == release_sha

    # End state: the release landed the same artifacts a fully clean run
    # produces, whichever phase the stop interrupted.
    assert _git_out(["branch", "--show-current"], cwd=str(root)) == "main"
    assert f'version = "{_VERSION}"' in (root / "pyproject.toml").read_text()
    assert _git_out(["tag", "--list", _TAG], cwd=str(root)) == _TAG
    merged = cast(
        "list[dict[str, object]]",
        json.loads(_git_out(["show", "main:src/data/projects.json"], cwd=str(sibling))),
    )
    assert merged[0]["version"] == _VERSION
    assert _git_out(["branch", "--show-current"], cwd=str(sibling)) == "main"
    assert _git_out(["status", "--porcelain"], cwd=str(sibling)) == ""
