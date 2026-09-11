"""Fixture-authoring types for the recorded ``gh`` envelope library (§2b).

These ``TypedDict``\\ s exist for exactly two things: readability when writing
a new hand-authored fixture, and mypy coverage of ``load_gh_fixture`` below.
They are never what a contract test validates a parser *against* —
``tests/test_gh_fixture_contracts.py`` drives the real production collaborator
methods against each fixture's raw ``stdout`` instead. A hand-maintained
mirror of ``gh``'s response shapes cannot detect its own drift from the code
it is meant to protect (a schema and a parser can go stale together and keep
agreeing); driving the real parser against a static fixture can, because the
parser itself is what changes when the source changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "gh"


class FixtureMeta(TypedDict):
    """The ``_meta`` sidecar every envelope carries — never handed to a
    ``FaultRule`` response; read by the recorder, the drift checker, and the
    version-stamp gate only.
    """

    gh_version: str
    recorded_at: str
    command: list[str]
    hand_authored: bool
    note: str


class FixtureEnvelope(TypedDict):
    """The on-disk shape of every file under ``tests/fixtures/gh/``."""

    returncode: int
    stdout: str
    stderr: str
    _meta: FixtureMeta


class PrListEntry(TypedDict):
    """One element of ``gh pr list --json number,state,headRefOid``."""

    number: int
    state: str
    headRefOid: str


class PrViewState(TypedDict):
    """``gh pr view <n> --json state``."""

    state: str


class RunListEntry(TypedDict):
    """One element of ``gh run list --json databaseId,headBranch,...``."""

    databaseId: int
    headBranch: str
    event: str
    headSha: str
    conclusion: str | None


class RunViewResult(TypedDict):
    """``gh run view <id> --json status,conclusion``."""

    status: str
    conclusion: str | None


class ReviewThreadNode(TypedDict):
    """One node of a PR-thread-listing GraphQL response."""

    id: str
    isResolved: bool


class BranchProtectionErrorBody(TypedDict):
    """The 404 error body ``gh api .../branches/main/protection`` returns
    for an unprotected branch.
    """

    message: str
    documentation_url: str
    status: str


def load_gh_fixture(
    name: str, *, fixtures_dir: Path = _FIXTURES_DIR
) -> FixtureEnvelope:
    """Load one recorded/hand-authored envelope, typed for test readability.

    Distinct from ``FaultRule.from_fixture`` (which extracts only the
    ``CompletedProcessSpec`` a ``FaultRule`` needs) — this returns the whole
    envelope, ``_meta`` included, for tests that assert on the fixture
    library itself (the version-stamp gate, hand-authored bookkeeping).
    """
    raw: object = json.loads((fixtures_dir / name).read_text())
    # Wire boundary — json.loads yields `object` until narrowed to the
    # envelope shape every fixture this library ships actually has
    # (PY-TS-14).
    return cast("FixtureEnvelope", raw)
