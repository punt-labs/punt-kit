"""Installation health checks for punt-kit."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    """Result of a single health check."""

    name: str
    passed: bool
    message: str
    required: bool = True


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
    label = "required" if required else "optional"
    return CheckResult(name, False, f"not found ({label})", required=required)


def run_doctor(*, print_results: bool = True) -> tuple[int, list[CheckResult]]:
    """Run all health checks.

    Returns (exit_code, results).  exit_code is 0 when all required checks
    pass, 1 otherwise.
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
            suffix = "" if r.required else " (optional)"
            print(f"  {mark} {r.name}: {r.message}{suffix}")

    failed_required = any(not r.passed and r.required for r in results)
    return (1 if failed_required else 0, results)
