"""Manual recorder for the release engine's ``gh``-fixture library (§2b).

Never run in CI — it needs a live ``gh`` session against a real GitHub org.
Every invocation this tool makes is read-only: ``ReadOnlyGhRunner`` checks
each command against a fixed argv-prefix allowlist before shelling out, and
additionally refuses any ``gh api`` call carrying a mutating ``--method``/
``-X`` flag or a GraphQL ``mutation`` operation, so a command outside the
read-only inventory below is a bug caught in this tool, not a live side
effect on a real repo. Fixture envelopes for a *mutation's outcome* (PR
create, release create, a squash-merge result) cannot be produced by this
tool at all — the recording table has no entry that could build one — and
are hand-authored instead, documented as such in the envelope's ``_meta``.

Usage::

    uv run python tools/record_gh_fixtures.py [--repo OWNER/NAME] [--dest DIR]
    uv run python tools/record_gh_fixtures.py --check [--dest DIR]

``--check`` re-runs each *recorded* (non-hand-authored) fixture's stored
command live and diffs the live response's JSON key-shape against what is
committed — the live-reality drift detector described in §2b step 4. It is
never run in CI (no live credentials there); it is a scheduled or
pre-release manual gate.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Self, TypedDict, cast, final

if TYPE_CHECKING:
    from collections.abc import Sequence


class _PrListingEntry(TypedDict):
    """The shape ``gh pr list --json number,state,headRefName`` decodes to."""

    number: int
    state: str
    headRefName: str


class _RunListingEntry(TypedDict):
    """The shape ``gh run list --json databaseId,...`` decodes to."""

    databaseId: int
    headBranch: str
    event: str
    headSha: str
    conclusion: str | None


_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "gh"
_DEFAULT_REPO = "punt-labs/punt-kit"

# The read-only, non-``gh api`` command inventory this tool may ever build.
# Every entry is an argv *prefix*, compared with the same semantics
# ``FaultRule``/``FaultInjectingOps`` use (§2a) — ``Path(argv[0]).name`` for
# element 0, exact string equality for the rest — so ``("gh", "pr", "list")``
# never admits ``("gh", "pr", "merge")``. ``gh api ...`` is not listed here:
# its endpoint argument (``repos/{owner}/{repo}/...``) is one combined token,
# not a separate argv element a fixed prefix could match, so
# ``ReadOnlyGhRunner`` validates it with dedicated endpoint-shape and
# mutating-method/mutation checks instead — see ``_require_read_only_api_call``.
# This is the allowlist a test asserts every generated non-``api`` command
# against (tests/test_record_gh_fixtures.py).
_READ_ONLY_ALLOWLIST: tuple[tuple[str, ...], ...] = (
    ("gh", "--version"),
    ("gh", "pr", "list"),
    ("gh", "pr", "view"),
    ("gh", "run", "list"),
    ("gh", "run", "view"),
    ("gh", "run", "watch"),
    ("gh", "release", "view"),
)

_MUTATING_METHOD_RE = re.compile(r"^(post|put|patch|delete)$", re.IGNORECASE)


class ReadOnlyViolation(RuntimeError):
    """Raised when a command does not qualify as read-only.

    Never caught inside this tool — a violation here means the recording
    table itself was built wrong, and the fix is to correct the table, not
    to work around the refusal.
    """


class CommandNotReplayableError(RuntimeError):
    """Raised when a recorded command needs redaction before it is safe to
    commit — see ``GhFixtureRecorder._replayable_command``. Never caught
    inside this tool: a live branch/tag/PR-title that looks like a token or
    email is an operator problem to look at, not a shape to paper over by
    storing a ``_meta.command`` that no longer replays the real command.
    """


def _matches_prefix(cmd: Sequence[str], prefix: Sequence[str]) -> bool:
    if not cmd or len(cmd) < len(prefix):
        return False
    if Path(cmd[0]).name != prefix[0]:
        return False
    return list(cmd[1 : len(prefix)]) == list(prefix[1:])


def _flag_present(cmd: Sequence[str], name: str) -> bool:
    """True if ``name`` (e.g. ``"-f"`` or ``"--field"``) appears anywhere in
    ``cmd``, in any spelling ``gh``'s own pflag-based parser accepts
    identically to the bare split form (``-f x=1``): the equals form
    (``--field=x=1``, long flags only) and, for a single-dash single-letter
    flag, the attached form (``-fx=1``). Checking only ``arg == name`` — as
    an earlier version of this function did — misses both: `gh` parses
    ``--method=PUT``, ``-XPUT``, ``--field=x=1``, and ``-Fx=1`` exactly like
    their split-token equivalents, verified directly against a real ``gh``
    binary, so enumerating spellings as separate literal tokens is the wrong
    shape for this check — it will always be one spelling behind.
    """
    for arg in cmd:
        if arg == name:
            return True
        if name.startswith("--") and arg.startswith(name + "="):
            return True
        if len(name) == 2 and name[0] == "-" and arg != name and arg.startswith(name):
            return True
    return False


def _flag_occurrences(cmd: Sequence[str], name: str) -> list[tuple[int, str]]:
    """Every occurrence of ``name`` with a value, as ``(argv_index, value)``
    pairs — every spelling ``_flag_present`` recognizes, but only those
    that actually carry a value (a bare trailing flag with nothing after it
    contributes no value to check, though ``_flag_present`` still treats it
    as present for refusal purposes).
    """
    occurrences: list[tuple[int, str]] = []
    for i, arg in enumerate(cmd):
        if arg == name:
            if i + 1 < len(cmd):
                occurrences.append((i, cmd[i + 1]))
            continue
        if name.startswith("--") and arg.startswith(name + "="):
            occurrences.append((i, arg[len(name) + 1 :]))
            continue
        if len(name) == 2 and name[0] == "-" and arg != name and arg.startswith(name):
            occurrences.append((i, arg[len(name) :]))
    return occurrences


def _effective_method(cmd: Sequence[str]) -> str | None:
    """The HTTP method ``gh`` will actually use for this call.

    ``gh``'s pflag-based parser applies "last occurrence wins" for a
    repeated flag, and ``-X``/``--method`` are two spellings of the exact
    same option, so both must be considered *together*, in argv order, not
    each spelling's first occurrence checked independently. Checking only
    the first ``-X`` and first ``--method`` — an earlier version of this
    function did — misses ``-X GET --method POST`` entirely: it finds the
    harmless ``GET`` from ``-X`` first and, via a short-circuiting ``or``,
    never even looks at ``--method``'s ``POST``.
    """
    occurrences = _flag_occurrences(cmd, "-X") + _flag_occurrences(cmd, "--method")
    if not occurrences:
        return None
    occurrences.sort(key=lambda pair: pair[0])
    return occurrences[-1][1]


@final
class ReadOnlyGhRunner:
    """Runs a command only after proving it cannot mutate anything.

    Two layers of proof, both required: the command must match one of
    ``_READ_ONLY_ALLOWLIST``'s argv prefixes, and — for ``gh api`` calls
    specifically, since ``gh api repos/...`` and ``gh api graphql`` both
    admit a mutating verb the prefix alone cannot see — the call must carry
    no explicit mutating HTTP method and, for GraphQL, no ``mutation``
    operation in its query text.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def require_read_only(self, cmd: Sequence[str]) -> None:
        """Raise ``ReadOnlyViolation`` unless ``cmd`` is provably read-only.

        Checked against the module-level ``_READ_ONLY_ALLOWLIST`` constant
        directly — deliberately not a constructor parameter. An injectable
        allowlist would let a caller instantiate
        ``ReadOnlyGhRunner`` with a custom prefix that includes a mutating
        shape (e.g. ``("gh", "pr", "merge")``), which would make the class's
        entire safety claim caller-configurable rather than structural.
        """
        if len(cmd) >= 3 and Path(cmd[0]).name == "gh" and cmd[1] == "api":
            self._require_read_only_api_call(cmd)
            return
        if not any(_matches_prefix(cmd, prefix) for prefix in _READ_ONLY_ALLOWLIST):
            raise ReadOnlyViolation(
                f"{list(cmd)!r} matches no entry in the read-only allowlist"
            )

    def _require_read_only_api_call(self, cmd: Sequence[str]) -> None:
        """``gh api``'s endpoint is one combined token, so this checks it
        directly rather than via the prefix allowlist: the endpoint must be
        the GraphQL escape hatch or a ``repos/...`` REST path, it must carry
        no explicit mutating HTTP method (in any spelling — see
        ``_flag_present``), no opaque ``--input`` request body, and a
        GraphQL call must carry no ``mutation`` operation in its query text.
        """
        endpoint = cmd[2]
        # `--input` reads the request body from a file or stdin this tool
        # cannot safely inspect — a mutation's text could live entirely in
        # that file and never appear as an argv string at all, so scanning
        # argv for the literal "mutation" (below) would never see it.
        # Refused unconditionally, for both endpoint shapes: no read-only
        # call this tool ever issues needs a request body of any kind.
        if _flag_present(cmd, "--input"):
            raise ReadOnlyViolation(
                f"{list(cmd)!r} passes --input, an unreadable request-body source"
            )
        if endpoint != "graphql" and not endpoint.startswith("repos/"):
            raise ReadOnlyViolation(
                f"{list(cmd)!r} targets an endpoint shape outside "
                "'graphql' or 'repos/...'"
            )
        method = _effective_method(cmd)
        if method is not None and _MUTATING_METHOD_RE.match(method):
            raise ReadOnlyViolation(
                f"{list(cmd)!r} passes a mutating HTTP method {method!r}"
            )
        if endpoint == "graphql":
            if any("mutation" in arg.lower() for arg in cmd):
                raise ReadOnlyViolation(
                    f"{list(cmd)!r} carries a GraphQL mutation operation"
                )
            return
        # A REST `repos/...` call with no explicit `-X`/`--method` defaults
        # to GET *only* as long as it carries no body — `gh api` silently
        # switches its own default to POST the moment a field parameter is
        # present, with no explicit `-X` required to trigger it. Neither
        # read-only `repos/...` endpoint this tool ever calls needs a body,
        # so refusing any field flag outright (in any spelling) closes that
        # default-flip rather than relying on every future addition to
        # remember it. `-f`/`-F`/`--field`/`--raw-field` are legitimate for
        # a GraphQL call (`-f query=...`), so they are only refused here, on
        # the REST branch — the `return` above already sent GraphQL callers
        # past this point.
        for name in ("-f", "-F", "--field", "--raw-field"):
            if _flag_present(cmd, name):
                raise ReadOnlyViolation(
                    f"{list(cmd)!r} passes a body field ({name}) to a REST "
                    "endpoint — gh defaults to POST once a field is present, "
                    "even with no explicit -X"
                )

    def run(self, cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Run ``cmd``, refusing first if it is not provably read-only."""
        self.require_read_only(cmd)
        # argv is built entirely by this module's own recording table, never
        # from unsanitized external input.
        return subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            check=False,
        )


@final
class GhSanitizer:
    """Scrubs recorded ``gh`` output before it is written into git.

    Two passes, always in this order. First, regex redaction of GitHub
    tokens and email addresses — these can appear in any output, JSON or
    not, so they are stripped from the raw text before anything else looks
    at it. Second, for output that parses as JSON, a recursive walk that
    blanks any string value keyed by a field GitHub uses for account
    identity (``login``, ``actor``, ``author``, ``user``, ``assignee``,
    ``requestedReviewer``) — the read-only commands this tool's recording
    table actually issues do not surface these fields today, but a future
    addition to the table (e.g. a review listing) would, and the scrub
    exists so that addition does not also need a new sanitization pass.
    Non-JSON text (e.g. ``gh release view``'s table) only gets the first
    pass — there is no structure to walk.
    """

    __slots__ = ()

    _TOKEN_RE = re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}\b")
    _EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    _IDENTITY_KEYS = frozenset(
        {"login", "actor", "author", "user", "assignee", "requestedReviewer"}
    )

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def sanitize(self, text: str) -> str:
        text = self._TOKEN_RE.sub("REDACTED_TOKEN", text)
        text = self._EMAIL_RE.sub("user@example.com", text)
        try:
            decoded: object = json.loads(text)
        except json.JSONDecodeError:
            return text
        return json.dumps(self._scrub_identities(decoded))

    def _scrub_identities(self, value: object) -> object:
        if isinstance(value, dict):
            # Wire boundary — decoded JSON keys are `object` until narrowed
            # here to the `str` every JSON object key actually is (PY-TS-14).
            fields = cast("dict[str, object]", value)
            return {k: self._scrub_field(k, v) for k, v in fields.items()}
        if isinstance(value, list):
            return [self._scrub_identities(v) for v in cast("list[object]", value)]
        return value

    def _scrub_field(self, key: str, value: object) -> object:
        """Blank ``value`` only when it is itself the identity string a
        key like ``login`` normally holds. GitHub's REST/GraphQL responses
        sometimes nest a whole object under an identity key instead (e.g.
        ``"author": {"login": ..., "id": ...}``) — blanking the object
        wholesale would replace a dict with a bare string, corrupting the
        shape `GhFixtureDriftChecker` fingerprints and producing a false
        "drift" report the next time a live response happens to carry that
        shape. Recursing instead keeps walking for a nested identity string.
        """
        if key in self._IDENTITY_KEYS and isinstance(value, str):
            return "redacted-user"
        return self._scrub_identities(value)


@dataclass(frozen=True, slots=True)
class RepoContext:
    """The owner/repo a recording pass runs against."""

    owner: str
    name: str

    @classmethod
    def parse(cls, slug: str) -> Self:
        owner, sep, name = slug.partition("/")
        if not sep or not owner or not name:
            raise ValueError(f"expected 'owner/repo', got {slug!r}")
        return cls(owner=owner, name=name)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class DiscoveredTargets:
    """Live entities one recording pass queries, resolved once up front.

    Reusing the same PR/run/tag across every command in the pass keeps the
    fixture set internally consistent — the OPEN-PR fixtures all name the
    same PR, for instance — rather than each command independently picking
    whatever happens to be newest at the moment it runs.
    """

    open_pr: int
    open_pr_branch: str
    merged_pr: int
    merged_pr_branch: str
    closed_pr: int
    closed_pr_branch: str
    missing_branch: str
    run_id: int
    tag: str
    missing_tag: str


@final
class GhTargetDiscovery:
    """Finds real, currently-live PRs/runs/tags to record fixtures from.

    Every call here is itself read-only (``gh pr list``, ``gh run list``) —
    routed through the same ``ReadOnlyGhRunner`` the recording pass uses, so
    discovery carries the identical read-only guarantee as recording.
    """

    __slots__ = ("_repo", "_runner")

    _runner: ReadOnlyGhRunner
    _repo: RepoContext

    def __new__(cls, *, runner: ReadOnlyGhRunner, repo: RepoContext) -> Self:
        self = super().__new__(cls)
        self._runner = runner
        self._repo = repo
        return self

    def discover(self) -> DiscoveredTargets:
        prs = self._list_prs()
        open_pr = self._first_matching(prs, "OPEN")
        merged_pr = self._first_matching(prs, "MERGED")
        closed_pr = self._first_matching(prs, "CLOSED")
        run = self._latest_release_run()
        return DiscoveredTargets(
            open_pr=open_pr["number"],
            open_pr_branch=open_pr["headRefName"],
            merged_pr=merged_pr["number"],
            merged_pr_branch=merged_pr["headRefName"],
            closed_pr=closed_pr["number"],
            closed_pr_branch=closed_pr["headRefName"],
            missing_branch="harness-fixture-probe-branch-does-not-exist",
            run_id=run["databaseId"],
            tag=run["headBranch"],
            missing_tag="v0.0.0-harness-fixture-probe",
        )

    def _list_prs(self) -> list[_PrListingEntry]:
        result = self._runner.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self._repo.slug,
                "--state",
                "all",
                "--json",
                "number,state,headRefName",
                "--limit",
                "50",
            ]
        )
        if result.returncode != 0:
            raise LookupError(f"gh pr list failed: {result.stderr.strip()}")
        # Wire boundary — json.loads yields `object` until narrowed to the
        # shape `gh`'s own `--json` flag guarantees (PY-TS-14).
        parsed: object = json.loads(result.stdout)
        if not isinstance(parsed, list):
            raise LookupError(f"gh pr list returned a non-list shape: {parsed!r}")
        return cast("list[_PrListingEntry]", parsed)

    def _first_matching(
        self, prs: list[_PrListingEntry], state: str
    ) -> _PrListingEntry:
        for pr in prs:
            if pr["state"] == state:
                return pr
        raise LookupError(
            f"no {state} PR found in the last {len(prs)} PRs of "
            f"{self._repo.slug} — recording needs at least one of each state"
        )

    def _latest_release_run(self) -> _RunListingEntry:
        """The most recent tag-*push* run of ``release.yml``.

        ``release.yml`` commonly also permits ``workflow_dispatch`` (a
        manual re-run), and ``gh run list`` returns runs newest-first
        regardless of trigger — so the newest entry can be a manual
        dispatch rather than the tag push this fixture is documented to
        represent. ``TagRunSelector.matches`` (the production collaborator
        this fixture exists to feed) rejects any run whose ``event`` is not
        ``"push"`` outright, so recording from a dispatch run would produce
        a `gh_run_list_matching_tag.json` fixture that fails to `match()`
        the very selector it is named for. Filtering here to the same
        `event == "push"` predicate keeps the fixture honest with its own
        name.
        """
        result = self._runner.run(
            [
                "gh",
                "run",
                "list",
                "--repo",
                self._repo.slug,
                "--workflow",
                "release.yml",
                "--limit",
                "20",
                "--json",
                "databaseId,headBranch,event,headSha,conclusion",
            ]
        )
        if result.returncode != 0:
            raise LookupError(f"gh run list failed: {result.stderr.strip()}")
        parsed: object = json.loads(result.stdout)  # wire boundary, see above
        if not isinstance(parsed, list) or not parsed:
            raise LookupError(f"no release.yml runs found for {self._repo.slug}")
        runs = cast("list[_RunListingEntry]", parsed)
        for run in runs:
            if run["event"] == "push":
                return run
        raise LookupError(
            f"no push-triggered release.yml run found in the last {len(runs)} "
            f"runs of {self._repo.slug} — only workflow_dispatch runs, or none "
            "at all"
        )


@dataclass(frozen=True, slots=True)
class FixtureRecording:
    """One fixture's name and the exact argv that produces it."""

    name: str
    command: tuple[str, ...]
    note: str = ""


@final
class GhRecordingPlan:
    """Builds the full recorded-fixture argv list from discovered targets.

    Pure command construction, no execution — this is what
    ``tests/test_record_gh_fixtures.py`` calls with synthetic targets to
    assert every command the tool can ever issue matches the read-only
    allowlist, with no network access required to prove it.
    """

    __slots__ = ("_repo", "_targets")

    _repo: RepoContext
    _targets: DiscoveredTargets

    def __new__(cls, *, repo: RepoContext, targets: DiscoveredTargets) -> Self:
        self = super().__new__(cls)
        self._repo = repo
        self._targets = targets
        return self

    def recordings(self) -> tuple[FixtureRecording, ...]:
        t = self._targets
        repo = self._repo.slug
        return (
            FixtureRecording(
                "gh_pr_list_open.json",
                (
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    t.open_pr_branch,
                    "--state",
                    "all",
                    "--json",
                    "number,state,headRefOid",
                    "--limit",
                    "20",
                ),
                "PrMerger's existing-PR lookup, an OPEN PR.",
            ),
            FixtureRecording(
                "gh_pr_list_merged.json",
                (
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    t.merged_pr_branch,
                    "--state",
                    "all",
                    "--json",
                    "number,state,headRefOid",
                    "--limit",
                    "20",
                ),
                "Same lookup, a MERGED PR at its own head.",
            ),
            FixtureRecording(
                "gh_pr_list_closed.json",
                (
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    t.closed_pr_branch,
                    "--state",
                    "all",
                    "--json",
                    "number,state,headRefOid",
                    "--limit",
                    "20",
                ),
                "Same lookup, a CLOSED (never merged) PR.",
            ),
            FixtureRecording(
                "gh_pr_list_empty.json",
                (
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    t.missing_branch,
                    "--state",
                    "all",
                    "--json",
                    "number,state,headRefOid",
                    "--limit",
                    "20",
                ),
                "Same lookup, no PR for the branch at all.",
            ),
            FixtureRecording(
                "gh_pr_view_open.json",
                ("gh", "pr", "view", str(t.open_pr), "--repo", repo, "--json", "state"),
                "PrMerger._is_merged / merge()'s post-wait state check, OPEN.",
            ),
            FixtureRecording(
                "gh_pr_view_merged.json",
                (
                    "gh",
                    "pr",
                    "view",
                    str(t.merged_pr),
                    "--repo",
                    repo,
                    "--json",
                    "state",
                ),
                "Same check, MERGED.",
            ),
            FixtureRecording(
                "gh_run_list_matching_tag.json",
                (
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    repo,
                    "--workflow",
                    "release.yml",
                    "--branch",
                    t.tag,
                    "--limit",
                    "20",
                    "--json",
                    "databaseId,headBranch,event,headSha,conclusion",
                ),
                "TagRunSelector.list_command's own shape, a tag with a run.",
            ),
            FixtureRecording(
                "gh_run_view_success.json",
                (
                    "gh",
                    "run",
                    "view",
                    str(t.run_id),
                    "--repo",
                    repo,
                    "--json",
                    "status,conclusion",
                ),
                "CiRunWatch.failure_message's verdict query, a healthy run.",
            ),
            FixtureRecording(
                "gh_run_watch_healthy.json",
                (
                    "gh",
                    "run",
                    "watch",
                    str(t.run_id),
                    "--repo",
                    repo,
                    "--exit-status",
                ),
                "Phase6CiWait's post-selection watch call on an already-"
                "completed run — part of the design's full recording "
                "inventory (Phase 6, phase06_ci_wait.py), but no contract "
                "test consumes it: production code runs it with "
                "capture=False and only checks its returncode, never its "
                "stdout, and Phase6CiWait itself is a phase class, not a "
                "shared collaborator (out of Wave 1's collaborator-testing "
                "scope per the design's matrix rows 21-27 boundary).",
            ),
            FixtureRecording(
                "gh_release_view_exists.json",
                ("gh", "release", "view", t.tag, "--repo", repo),
                "Phase 7's already-released short-circuit.",
            ),
            FixtureRecording(
                "gh_release_view_missing.json",
                ("gh", "release", "view", t.missing_tag, "--repo", repo),
                "Phase 7 proceeding to create the release.",
            ),
            FixtureRecording(
                "gh_api_branch_protection_not_protected.json",
                (
                    "gh",
                    "api",
                    f"repos/{repo}/branches/main/protection",
                ),
                "GithubRepo.has_branch_protection on a ruleset-only repo.",
            ),
            FixtureRecording(
                "gh_api_rules_branches_governed.json",
                ("gh", "api", f"repos/{repo}/rules/branches/main"),
                "GithubRepo.has_ruleset on a ruleset-governed repo.",
            ),
            FixtureRecording(
                "gh_graphql_required_checks_passed.json",
                (
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={self._required_checks_query(repo, t.merged_pr)}",
                ),
                "RequiredChecksWaiter.wait, every required check SUCCESS.",
            ),
            FixtureRecording(
                "gh_graphql_required_checks_mixed_conclusions.json",
                (
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={self._required_checks_query(repo, t.open_pr)}",
                ),
                "Same query, a mix of SUCCESS/NEUTRAL conclusions.",
            ),
            FixtureRecording(
                "gh_graphql_pr_threads.json",
                (
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={self._pr_threads_query(repo, t.merged_pr)}",
                ),
                "PrThreadResolver.resolve's listing query.",
            ),
        )

    @staticmethod
    def _required_checks_query(repo: str, pr_number: int) -> str:
        owner, _, name = repo.partition("/")
        return (
            "{"
            f'  repository(owner: "{owner}", name: "{name}") {{'
            f"    pullRequest(number: {pr_number}) {{"
            "      commits(last: 1) {"
            "        nodes {"
            "          commit {"
            "            statusCheckRollup {"
            "              contexts(first: 100) {"
            "                nodes {"
            "                  ... on CheckRun {"
            "                    name"
            f"                    isRequired(pullRequestNumber: {pr_number})"
            "                    conclusion"
            "                    status"
            "                  }"
            "                  ... on StatusContext {"
            "                    context"
            f"                    isRequired(pullRequestNumber: {pr_number})"
            "                    state"
            "                  }"
            "                }"
            "              }"
            "            }"
            "          }"
            "        }"
            "      }"
            "    }"
            "  }"
            "}"
        )

    @staticmethod
    def _pr_threads_query(repo: str, pr_number: int) -> str:
        owner, _, name = repo.partition("/")
        return (
            f'{{ repository(owner: "{owner}", name: "{name}") {{'
            f" pullRequest(number: {pr_number}) {{"
            " reviewThreads(first: 50) {"
            " nodes { id isResolved } } } } }"
        )


@final
class GhFixtureRecorder:
    """Runs a plan's commands live and writes the sanitized envelope files."""

    __slots__ = ("_dest", "_gh_version", "_runner", "_sanitizer")

    _runner: ReadOnlyGhRunner
    _sanitizer: GhSanitizer
    _dest: Path
    _gh_version: str

    def __new__(
        cls, *, runner: ReadOnlyGhRunner, sanitizer: GhSanitizer, dest: Path
    ) -> Self:
        self = super().__new__(cls)
        self._runner = runner
        self._sanitizer = sanitizer
        self._dest = dest
        version = runner.run(["gh", "--version"])
        self._gh_version = version.stdout.splitlines()[0] if version.stdout else ""
        return self

    def record_all(self, recordings: tuple[FixtureRecording, ...]) -> list[Path]:
        self._dest.mkdir(parents=True, exist_ok=True)
        return [self._record_one(r) for r in recordings]

    def _record_one(self, recording: FixtureRecording) -> Path:
        result = self._runner.run(recording.command)
        command = self._replayable_command(recording)
        envelope = {
            "returncode": result.returncode,
            "stdout": self._sanitizer.sanitize(result.stdout),
            "stderr": self._sanitizer.sanitize(result.stderr),
            "_meta": {
                "gh_version": self._gh_version,
                "recorded_at": datetime.now(UTC).isoformat(),
                "command": command,
                "hand_authored": False,
                "note": recording.note,
            },
        }
        path = self._dest / recording.name
        path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
        return path

    def _replayable_command(self, recording: FixtureRecording) -> list[str]:
        """``recording.command``, verified to need no sanitization.

        A branch, tag, or PR-title argument copied from live GitHub data
        could in principle contain a token- or email-shaped substring,
        which would bypass ``stdout``/``stderr``'s redaction pass entirely
        by riding into ``_meta.command`` unchanged — so this checks the
        same way ``sanitize`` would. Storing the *sanitized* command
        instead, rather than refusing outright, would be worse: `--check`
        (`GhFixtureDriftChecker`) executes `_meta.command` as the live argv
        to replay, so a silently-redacted branch name would make it target
        a different, likely-nonexistent ref — the drift check would then
        report a wrong result instead of no longer validating anything
        real, which is a worse failure mode than simply refusing to record.
        A live branch/tag/PR-title that actually looks like a token or
        email is itself worth an operator's attention, not something to
        paper over.
        """
        sanitized = [self._sanitizer.sanitize(arg) for arg in recording.command]
        original = list(recording.command)
        if sanitized != original:
            raise CommandNotReplayableError(
                f"{recording.name}: the command itself needs redaction "
                f"({original!r} -> {sanitized!r}) — refusing to record a "
                "fixture whose _meta.command could not replay the command "
                "that actually produced it"
            )
        return original


@final
class GhFixtureDriftChecker:
    """Re-runs every recorded fixture's command live and diffs its shape.

    The actual drift-from-reality detector (§2b step 4) — the contract test
    (``tests/test_gh_fixture_contracts.py``) only ever compares the static,
    committed fixtures against the parser, so it cannot see a live ``gh``
    upgrade on its own. This is the piece that can.
    """

    __slots__ = ("_dest", "_runner")

    _runner: ReadOnlyGhRunner
    _dest: Path

    def __new__(cls, *, runner: ReadOnlyGhRunner, dest: Path) -> Self:
        self = super().__new__(cls)
        self._runner = runner
        self._dest = dest
        return self

    def check(self) -> list[str]:
        paths = sorted(self._dest.glob("*.json"))
        if not paths:
            # A missing or mistyped --dest makes this loop run zero times,
            # which would otherwise report a silent, vacuous "no drift" —
            # indistinguishable from a genuinely clean check to anyone
            # reading only the exit code.
            return [
                f"{self._dest}: no fixture files found — refusing to report "
                "'no drift' for an empty or missing directory"
            ]
        mismatches: list[str] = []
        for path in paths:
            mismatches.extend(self._check_one(path))
        return mismatches

    def _check_one(self, path: Path) -> list[str]:
        # Wire boundary — a fixture file's decoded JSON is `object` until
        # narrowed to the envelope shape every fixture this tool writes
        # actually has (PY-TS-14).
        envelope = cast("dict[str, object]", json.loads(path.read_text()))
        raw_meta = envelope.get("_meta")
        if not isinstance(raw_meta, dict):
            return [f"{path.name}: missing _meta — not a valid envelope"]
        meta = cast("dict[str, object]", raw_meta)
        if meta.get("hand_authored"):
            return []
        command = meta.get("command")
        if not isinstance(command, list) or not command:
            return [f"{path.name}: _meta.command missing — cannot re-check live"]
        live = self._runner.run(cast("list[str]", command))
        return self._diff(path.name, envelope, live)

    def _diff(
        self,
        name: str,
        envelope: dict[str, object],
        live: subprocess.CompletedProcess[str],
    ) -> list[str]:
        recorded_rc = envelope.get("returncode")
        if (recorded_rc == 0) != (live.returncode == 0):
            return [
                f"{name}: recorded returncode {recorded_rc}, live returncode "
                f"{live.returncode} — success/failure disagreement"
            ]
        recorded_shape = self._json_shape(envelope.get("stdout"))
        live_shape = self._json_shape(live.stdout)
        if recorded_shape != live_shape:
            return [
                f"{name}: stdout shape drifted — recorded {recorded_shape!r}, "
                f"live {live_shape!r}"
            ]
        return []

    def _json_shape(self, raw: object) -> object:
        """A structural fingerprint of decoded JSON — keys and value kinds,
        recursively, with actual values erased. Two payloads with the same
        shape may hold different data; that is expected and not drift.
        """
        if not isinstance(raw, str):
            return type(raw).__name__
        try:
            decoded: object = json.loads(raw)
        except json.JSONDecodeError:
            return "non-json-text"
        return self._shape_of(decoded)

    def _shape_of(self, value: object) -> object:
        if isinstance(value, dict):
            fields = cast("dict[str, object]", value)
            return {k: self._shape_of(v) for k, v in sorted(fields.items())}
        if isinstance(value, list):
            items = [self._shape_of(v) for v in cast("list[object]", value)]
            return self._distinct_shapes(items)
        return type(value).__name__

    @staticmethod
    def _distinct_shapes(shapes: list[object]) -> list[object]:
        """Every distinct element shape in a JSON array, in a deterministic,
        order-insensitive form — not just the first element's shape.

        The GraphQL arrays this recorder captures are commonly
        heterogeneous (a ``contexts`` list mixes ``CheckRun`` and
        ``StatusContext`` nodes with different fields), so collapsing to
        one representative shape would let a later element's field or
        value-kind change go undetected. Deduplicating and sorting by each
        shape's own canonical JSON string keeps the result stable across
        two responses that enumerate the same set of distinct shapes in a
        different order.
        """
        keyed = {json.dumps(shape, sort_keys=True): shape for shape in shapes}
        return [keyed[key] for key in sorted(keyed)]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=_DEFAULT_REPO, help="owner/name to record from"
    )
    parser.add_argument(
        "--dest", default=_DEFAULT_FIXTURES_DIR, type=Path, help="fixture directory"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-run recorded fixtures live and report shape drift",
    )
    return parser


def _display_path(path: Path) -> Path:
    """``path``, relative to the repo root when it lives inside it.

    ``--dest`` need not live under the repo root — a path outside it (e.g.
    a scratch directory for a one-off test recording) must still print
    successfully after the write already landed, rather than raising from
    ``Path.relative_to`` on a path that shares no common root.
    """
    return path.relative_to(_ROOT) if path.is_relative_to(_ROOT) else path


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    runner = ReadOnlyGhRunner()

    if args.check:
        mismatches = GhFixtureDriftChecker(runner=runner, dest=args.dest).check()
        if mismatches:
            for line in mismatches:
                print(f"DRIFT: {line}")
            return 1
        print("no drift — every recorded fixture still matches live gh output")
        return 0

    repo = RepoContext.parse(args.repo)
    targets = GhTargetDiscovery(runner=runner, repo=repo).discover()
    plan = GhRecordingPlan(repo=repo, targets=targets)
    sanitizer = GhSanitizer()
    recorder = GhFixtureRecorder(runner=runner, sanitizer=sanitizer, dest=args.dest)
    for path in recorder.record_all(plan.recordings()):
        print(f"wrote {_display_path(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
