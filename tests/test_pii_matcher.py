"""Tests for pure PII matching."""

from punt_kit.pii_matcher import Finding, PiiConfig, PiiMatcher, ScanSource


def test_deny_checks_use_input_line_and_file() -> None:
    matcher = PiiMatcher(PiiConfig(deny=["demo-token"]), [])

    assert matcher.scan(ScanSource("test.txt", "clean\ndemo-token")) == [
        Finding("test.txt", 2, "deny", "demo-token")
    ]
