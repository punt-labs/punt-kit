"""Tests for matching marketplace and website entries to a project by full slug."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.entry_matcher import EntryMatcher


def _matcher(*names: str) -> EntryMatcher:
    return EntryMatcher("punt-labs", frozenset(names))


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
    assert _matcher("proj").claims_url(url)


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
    assert not _matcher("proj").claims_url(url)


def test_any_candidate_name_under_the_owner_matches() -> None:
    matcher = _matcher("punt", "punt-kit")

    assert matcher.claims_url("https://github.com/punt-labs/punt")


def test_a_marketplace_entry_matches_by_name_or_by_source_url() -> None:
    matcher = _matcher("punt", "punt-kit")
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
    assert not _matcher("proj").claims_plugin({"name": "other"})


def test_a_website_entry_matches_by_id_or_github_url() -> None:
    matcher = _matcher("proj")
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
