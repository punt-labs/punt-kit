"""Tests for recognizing a project's pinned install.sh URLs."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.install_urls import InstallUrlRecognizer

_RECOGNIZER = InstallUrlRecognizer("punt-labs", "proj")
_HOST = "https://raw.githubusercontent.com/punt-labs/proj"


@pytest.mark.parametrize(
    "tail",
    [
        "install.sh.bak",
        "install.sh-old",
        "install.sh_v2",
        "install.shell",
        "install.sh.1",
    ],
)
def test_a_longer_file_name_is_not_an_install_sh_reference(tail: str) -> None:
    assert _RECOGNIZER.scan(f"curl {_HOST}/abc1234/{tail}") == []


@pytest.mark.parametrize("after", ["", ".", ")", " | sh", "?x=1", ",", '"'])
def test_install_sh_followed_by_punctuation_is_still_a_reference(after: str) -> None:
    refs = _RECOGNIZER.scan(f"see {_HOST}/abc1234/install.sh{after}")

    assert [ref.segment for ref in refs] == ["abc1234"]


@pytest.mark.parametrize(
    "authority",
    [
        "user@raw.githubusercontent.com",
        "user:secret@raw.githubusercontent.com",
        "raw.githubusercontent.com:8443",
        "raw.githubusercontent.com:443",
    ],
)
def test_userinfo_or_a_port_makes_a_pin_url_untrusted(authority: str) -> None:
    url = f"https://{authority}/punt-labs/proj/abc1234/install.sh"

    (ref,) = _RECOGNIZER.scan(url)

    assert ref.is_trusted is False


def test_the_plain_host_is_trusted() -> None:
    (ref,) = _RECOGNIZER.scan(f"{_HOST}/abc1234/install.sh")

    assert ref.is_trusted is True


def test_classify_reports_tag_pins_as_well_as_sha_pins() -> None:
    content = (
        f"{_HOST}/abc1234/install.sh and {_HOST}/v1.2.3/install.sh "
        f"and {_HOST}/main/install.sh"
    )

    pins, has_untrusted = _RECOGNIZER.classify(content)

    assert (pins, has_untrusted) == (["abc1234", "v1.2.3"], False)


def test_a_segment_is_a_sha_by_shape() -> None:
    assert [
        InstallUrlRecognizer.is_sha_segment(s) for s in ("abc1234", "v1.2.3", "main")
    ] == [True, False, False]


@pytest.mark.parametrize(
    "token", ["https://[", "https://[evil/proj/abc1234/install.sh"]
)
def test_an_unbalanced_bracket_url_is_not_an_install_url(token: str) -> None:
    refs = _RECOGNIZER.scan(f"curl {token} | sh; curl {_HOST}/abc1234/install.sh | sh")

    assert [ref.segment for ref in refs] == ["abc1234"]
