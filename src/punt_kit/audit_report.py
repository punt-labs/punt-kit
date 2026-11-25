"""Render audit findings and retain failed checks for machine callers."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Self

from punt_kit.audit_verdict import FAIL, FIXED, INFO, PASS
from punt_kit.errors import CommandFailure

if TYPE_CHECKING:
    from rich.console import Console

__all__ = ["FAIL", "FIXED", "INFO", "PASS", "AuditReport", "Findings"]

type Findings = list[tuple[str, str, str]]
logger = logging.getLogger(__name__)


class AuditReport:
    """Present check results and fail with the unsuccessful checks."""

    _findings: Findings

    def __new__(cls, findings: Findings) -> Self:
        """Retain the findings in check order."""
        self = super().__new__(cls)
        self._findings = findings
        return self

    def report(self, console: Console) -> tuple[int, int]:
        """Print results and return pass/fix counts once no check has failed."""
        counts = Counter(status for status, _, _ in self._findings)
        for status, label, detail in self._findings:
            console.print(f"  {status} {label}")
            if detail:
                console.print(f"      [dim]{detail}[/dim]")
        passed, failed, fixed = counts[PASS], counts[FAIL], counts[FIXED]
        summary = f"  [bold]{passed} passed[/bold], [bold]{failed} failed[/bold]"
        if fixed:
            summary += f", [bold yellow]{fixed} fixed[/bold yellow]"
        console.print(f"\n{summary}\n")
        logger.info(
            "Audit finished passed=%d failed=%d fixed=%d", passed, failed, fixed
        )
        if failed:
            raise CommandFailure(
                f"{failed} audit finding(s)",
                {
                    "passed": passed,
                    "failed": failed,
                    "fixed": fixed,
                    "findings": [
                        {"check": label, "detail": detail}
                        for status, label, detail in self._findings
                        if status == FAIL
                    ],
                },
            )
        return passed, fixed
