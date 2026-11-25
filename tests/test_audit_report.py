"""Tests for the output and result of audit checks."""

from io import StringIO

import pytest
from rich.console import Console

from punt_kit.audit_report import FAIL, FIXED, PASS, AuditReport
from punt_kit.errors import CommandFailure


def test_quiet_report_retains_only_failure_diagnostics() -> None:
    stream = StringIO()
    report = AuditReport(
        [(PASS, "present", ""), (FIXED, "created", ""), (FAIL, "missing", "add it")]
    )

    with pytest.raises(CommandFailure) as caught:
        report.report(Console(file=stream), quiet=True)

    assert "missing" in stream.getvalue()
    assert "add it" in stream.getvalue()
    assert "present" not in stream.getvalue()
    assert "created" not in stream.getvalue()
    assert caught.value.details == {
        "passed": 1,
        "failed": 1,
        "fixed": 1,
        "findings": [{"check": "missing", "detail": "add it"}],
    }
