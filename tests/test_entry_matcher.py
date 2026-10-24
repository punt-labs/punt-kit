"""Tests for matching marketplace and website entries to a project by full slug."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.entry_matcher import EntryMatcher
from punt_kit.phases.shared.repo_slug import RepoSlug


def _matcher(repo: str = "proj", *names: str) -> EntryMatcher:
    return EntryMatcher("punt-labs", repo, frozenset(names or {repo}))


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/punt-labs/proj",
        "https://github.com/punt-labs/proj.git",
        "https://GitHub.com/Punt-Labs/PROJ.git",
        "git@github.com:punt-labs/proj.git",
        "https://github.com/punt-labs/proj/",
    ],
)
def test_a_url_for_the_same_owner_and_repo_matches(url: str) -> None:
    assert _matcher().claims_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/someone-else/proj",
        "https://github.com/punt-labs/proj-extra",
        "https://github.com/punt-labs/xproj",
        "https://gitlab.com/punt-labs/proj",
        "https://github.com/proj",
        "",
    ],
)
def test_a_url_for_another_owner_or_repo_does_not_match(url: str) -> None:
    assert not _matcher().claims_url(url)


def test_the_short_name_is_never_a_repository_name() -> None:
    """A source URL names the repository; the short name is for ``name`` only."""
    matcher = _matcher("punt-kit", "punt", "punt-kit")

    assert (
        matcher.claims_url("https://github.com/punt-labs/punt"),
        matcher.claims_url("https://github.com/punt-labs/punt-kit"),
    ) == (False, True)


def test_a_marketplace_entry_matches_by_name_or_by_source_url() -> None:
    matcher = _matcher("punt-kit", "punt", "punt-kit")
    by_name = {"name": "punt", "source": {"url": "https://example.test/x"}}
    by_url = {
        "name": "other",
        "source": {"url": "https://github.com/punt-labs/punt-kit"},
    }
    neither = {"name": "other", "source": {"url": "https://github.com/evil/punt-kit"}}

    assert [matcher.claims_plugin(e) for e in (by_name, by_url, neither)] == [
        True,
        True,
        False,
    ]


def test_a_marketplace_entry_without_a_source_matches_only_by_name() -> None:
    assert not _matcher().claims_plugin({"name": "other"})


def test_a_website_entry_matches_by_id_or_github_url() -> None:
    matcher = _matcher()
    by_id = {"id": "proj", "githubUrl": ""}
    by_url = {"id": "x", "githubUrl": "https://github.com/punt-labs/proj"}
    foreign = {"id": "x", "githubUrl": "https://github.com/someone-else/proj"}
    null_url = {"id": "x", "githubUrl": None}

    assert [matcher.claims_website(e) for e in (by_id, by_url, foreign, null_url)] == [
        True,
        True,
        False,
        False,
    ]


def test_the_marketplace_matcher_goes_by_the_short_name_and_the_repo_name() -> None:
    matcher = EntryMatcher.for_marketplace(RepoSlug("punt-labs", "punt-kit"), "punt")

    assert (matcher.owner, matcher.repo) == ("punt-labs", "punt-kit")
    assert matcher.names == frozenset({"punt", "punt-kit"})


def test_the_marketplace_matcher_drops_an_empty_short_name() -> None:
    matcher = EntryMatcher.for_marketplace(RepoSlug("punt-labs", "proj"), "")

    assert matcher.names == frozenset({"proj"})


def test_the_website_matcher_goes_by_the_repo_name_alone() -> None:
    matcher = EntryMatcher.for_website(RepoSlug("punt-labs", "proj"))

    assert matcher.names == frozenset({"proj"})
