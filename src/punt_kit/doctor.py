"""Check the punt-kit installation."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass

import typer


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Record the result of one health check."""

    name: str
    passed: bool
    message: str
    required: bool = True

    @property
    def status_suffix(self) -> str:
        """Return the required/optional suffix; omit it for a passing required check."""
        if self.passed and self.required:
            return ""
        return " (optional)" if not self.required else " (required)"


def _check_python() -> CheckResult:
    """Check Python version >= 3.13."""
    vi = sys.version_info
    version = f"{vi.major}.{vi.minor}.{vi.micro}"
    if (vi.major, vi.minor) >= (3, 13):
        return CheckResult("Python", True, version)
    return CheckResult("Python", False, f"{version} (requires >= 3.13)")


def _check_binary(name: str, *, required: bool = True) -> CheckResult:
    """Check whether a binary is on PATH."""
    path = shutil.which(name)
    if path:
        return CheckResult(name, True, path, required=required)
    return CheckResult(name, False, "not found", required=required)


def run_doctor(*, print_results: bool = True) -> tuple[int, list[CheckResult]]:
    """Run all health checks, printing each result when ``print_results``.

    Returns:
        The exit code, 0 when every required check passes and 1 otherwise, and
        the results.
    """
    results = [
        _check_python(),
        _check_binary("uv"),
        _check_binary("ruff", required=False),
        _check_binary("mypy", required=False),
        _check_binary("pyright", required=False),
    ]

    if print_results:
        for r in results:
            mark = "\u2713" if r.passed else "\u2717"
            typer.echo(f"  {mark} {r.name}: {r.message}{r.status_suffix}", color=True)

    failed_required = any(not r.passed and r.required for r in results)
    return (1 if failed_required else 0, results)
