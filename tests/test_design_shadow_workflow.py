"""Exercise the design gate with passing, failing and invalid reports."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ratchet.yml"
STEP = "Design ratchet (shadow gate)"


def test_full_report_includes_non_gating_design_scan() -> None:
    report = (
        (ROOT / "Makefile")
        .read_text()
        .split("\nreport:", 1)[1]
        .split("\nformat:", 1)[0]
    )
    assert '\t-uv run oo-ratchet design "$(SRC)"\n' in report


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("punt_kit", "domain"),
        ("punt_kit.__main__", "entry"),
        ("punt_kit.audit", "entry"),
        ("punt_kit.audit_github", "adapters"),
        ("punt_kit.audit_permissions", "application"),
        ("punt_kit.detect", "adapters"),
        ("punt_kit.permission_rules", "domain"),
        ("punt_kit.release", "application"),
        ("punt_kit.phases.phase11_checks", "application"),
        ("punt_kit.phases.shared.ops", "domain"),
        ("punt_kit.phases.shared.command_runner", "adapters"),
        ("punt_kit.phases.shared.hook_firing", "domain"),
        ("punt_kit.phases.shared.git_listing", "domain"),
        ("punt_kit.phases.shared.module_version", "domain"),
        ("punt_kit.phases.shared.wheel_contents", "adapters"),
        ("punt_kit.phases.shared.wheel_probe", "adapters"),
        ("punt_kit.phases.shared.changelog_parser", "domain"),
        ("punt_kit.phases.shared.text_file", "adapters"),
        ("punt_kit.phases.shared.pipeline", "application"),
        ("punt_kit.undeclared", None),
    ],
)
def test_design_layer_boundaries(
    module: str,
    expected: str | None,  # None means the module matches no layer.
) -> None:
    layers = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["oo-ratchet"][
        "layers"
    ]
    actual = next(
        (
            layer
            for layer, patterns in layers.items()
            if any(fnmatchcase(module, pattern) for pattern in patterns)
        ),
        None,
    )
    assert actual == expected


def shadow_step() -> str:
    """Extract the actual reporting step, excluding YAML comments and later steps."""
    source = "\n".join(
        line
        for line in WORKFLOW.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    return source.split(f"      - name: {STEP}\n", 1)[1].split("\n      - ", 1)[0]


def test_shadow_is_a_pr_gate_separate_from_check() -> None:
    source = WORKFLOW.read_text()
    assert source.index("- name: Ratchets (PR") < source.index(f"- name: {STEP}")
    step = shadow_step()
    assert "if: ${{ !cancelled() && github.event_name == 'pull_request' }}" in step
    assert "continue-on-error" not in step
    assert "DESIGN_BASE: origin/${{ github.base_ref }}" in step
    assert "${{" not in step.split("run: |\n", 1)[1]
    check = next(
        line
        for line in (ROOT / "Makefile").read_text().splitlines()
        if line.startswith("check:")
    )
    assert "design-shadow" not in check
    assert "DESIGN_BASE ?= origin/main" in (ROOT / "Makefile").read_text()


@pytest.mark.parametrize(
    ("status", "output", "passes"),
    [
        (0, '{"verdict": "neutral"}\n', True),
        (0, '{"verdict": "good-deed"}\n', True),
        (0, '{"verdict": "good-deed: trade"}\n', True),
        (0, '{"verdict": "would-fail: tier0"}\n', False),
        (0, '{"verdict": "would-fail: tier1"}\n', False),
        (0, '{"verdict": "would-fail: tier2"}\n', False),
        (0, "", False),
        (0, "not JSON\n", False),
        (0, "{}\n", False),
        (0, "[]\n", False),
        (0, '{"verdict": "unknown"}\n', False),
        (2, "FAIL: invalid reference\n", False),
        (2, '{"verdict": "neutral"}\n', False),
    ],
)
@pytest.mark.parametrize(
    "base",
    [
        "origin/other-base",
        "origin/`printf${IFS}injected`",
        "origin/$(printf${IFS}injected)",
    ],
)
def test_shadow_publishes_reports_and_gates_verdicts(
    tmp_path: Path, status: int, output: str, passes: bool, base: str
) -> None:
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\nshift 2\nexec "$PYTHON" "$@"\n')
    uv.chmod(0o755)
    scanner = tmp_path / "oo-ratchet"
    scanner.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > "$ARGV_LOG"\n'
        'printf "%s" "$SHADOW_OUTPUT"\nprintf "scanner diagnostic\\n" >&2\n'
        'exit "$SHADOW_STATUS"\n'
    )
    scanner.chmod(0o755)
    summary = tmp_path / "summary.md"
    summary.write_text("Earlier step\n")
    argv_log = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "DESIGN_BASE": base,
        "ARGV_LOG": str(argv_log),
        "SHADOW_OUTPUT": output,
        "SHADOW_STATUS": str(status),
        "PYTHON": sys.executable,
    }
    script = textwrap.dedent(shadow_step().split("run: |\n", 1)[1])
    result = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            script,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == passes, result.stdout + result.stderr
    assert argv_log.read_text().strip() == (
        f"design src/punt_kit/ --shadow-check {base} --json"
    )
    report = summary.read_text()
    assert report.startswith(f"Earlier step\n### {STEP}")
    assert report == "Earlier step\n" + result.stdout
    assert report.endswith("```\n")
    assert output in report
    assert "scanner diagnostic\n" in report


def test_bare_make_still_lists_targets() -> None:
    result = subprocess.run(
        ["make", "-n"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "oo-ratchet design" not in result.stdout
    assert "grep -E" in result.stdout
