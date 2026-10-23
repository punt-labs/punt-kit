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

    assert (count, pin.all_shas(rewritten)) == (1, [sha])


def test_install_all_entry_ignores_other_projects() -> None:
    pin = ShaPin.install_all_entry("proj")
    content = (
        'curl "$GH/proj-extra/abc1234/install.sh"\n'
        'curl "$GH/xproj/abc1234/install.sh"\n'
        'curl "$GH/proj/main/install.sh"\n'
    )

    assert pin.repinned(content, _SHA) == (content, 0)
    assert pin.all_shas(content) == []


def test_install_all_entry_escapes_the_project_name() -> None:
    pin = ShaPin.install_all_entry("a.b")

    assert pin.all_shas('"$GH/aXb/abc1234/install.sh"') == []


def test_all_shas_returns_every_pin_in_order_not_only_the_first() -> None:
    pin = ShaPin.install_all_entry("proj")
    content = (
        'curl "$GH/proj/aaaaaaa/install.sh"\n'
        'curl "$GH/other/bbbbbbb/install.sh"\n'
        'curl "$GH/proj/ccccccc/install.sh"\n'
    )

    assert pin.all_shas(content) == ["aaaaaaa", "ccccccc"]


def test_profile_pin_reads_back_the_sha_it_writes() -> None:
    pin = ShaPin.profile()
    content = (
        "curl https://raw.githubusercontent.com/punt-labs/.github/abc1234"
        "/install-all.sh | sh\n"
    )

    rewritten, count = pin.repinned(content, _SHA)

    assert (count, pin.all_shas(rewritten)) == (1, [_SHA])


def test_profile_pin_ignores_other_repositories() -> None:
    content = "https://raw.githubusercontent.com/punt-labs/other/abc1234/install-all.sh"

    assert ShaPin.profile().all_shas(content) == []
