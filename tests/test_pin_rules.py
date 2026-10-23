"""Tests for the one definition of each SHA pin the release writes and verifies."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.pin_rules import ShaPin

_SHA = "0123abc"


@pytest.mark.parametrize("sha", ["abc1234", "ABCDEF1", "a" * 40])
def test_install_all_entry_reads_back_the_sha_it_writes(sha: str) -> None:
    pin = ShaPin.install_all_entry("proj")
    content = 'curl -fsSL "$GH/proj/abc1234/install.sh" | sh\n'

    rewritten, count = pin.repinned(content, sha)

    assert (count, pin.first_sha(rewritten)) == (1, sha)


def test_install_all_entry_ignores_other_projects() -> None:
    pin = ShaPin.install_all_entry("proj")
    content = (
        'curl "$GH/proj-extra/abc1234/install.sh"\n'
        'curl "$GH/xproj/abc1234/install.sh"\n'
        'curl "$GH/proj/main/install.sh"\n'
    )

    assert pin.repinned(content, _SHA) == (content, 0)
    assert pin.first_sha(content) is None


def test_install_all_entry_escapes_the_project_name() -> None:
    pin = ShaPin.install_all_entry("a.b")

    assert pin.first_sha('"$GH/aXb/abc1234/install.sh"') is None


def test_has_pin_starting_with_accepts_a_longer_pin_of_the_same_commit() -> None:
    pin = ShaPin.install_all_entry("proj")
    content = f'"$GH/proj/{_SHA}ffff/install.sh"'

    assert (
        pin.has_pin_starting_with(content, _SHA),
        pin.has_pin_starting_with(content, "9999999"),
    ) == (True, False)


def test_profile_pin_reads_back_the_sha_it_writes() -> None:
    pin = ShaPin.profile()
    content = (
        "curl https://raw.githubusercontent.com/punt-labs/.github/abc1234"
        "/install-all.sh | sh\n"
    )

    rewritten, count = pin.repinned(content, _SHA)

    assert (count, pin.first_sha(rewritten)) == (1, _SHA)


def test_profile_pin_ignores_other_repositories() -> None:
    content = "https://raw.githubusercontent.com/punt-labs/other/abc1234/install-all.sh"

    assert ShaPin.profile().first_sha(content) is None
