"""Release workflow gates the exact candidate and the published package."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke-release.sh"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
TEST = ROOT / ".github" / "workflows" / "test.yml"


def _job(workflow: Path, name: str) -> str:
    body = workflow.read_text().split(f"\n  {name}:\n", 1)[1]
    return body.split("\n\n  ", 1)[0]


def test_pypi_publish_waits_for_the_candidate_smoke() -> None:
    assert "    needs: [build, candidate-smoke]\n" in _job(RELEASE, "pypi")


def test_candidate_smoke_runs_the_built_wheel_for_the_tag() -> None:
    job = _job(RELEASE, "candidate-smoke")
    assert "    needs: build\n" in job
    assert "name: dist" in job
    assert (
        'scripts/smoke-release.sh candidate "${wheels[0]}" "${GITHUB_REF_NAME#v}"'
        in job
    )


def test_published_smoke_compares_pypi_to_the_candidate_wheel() -> None:
    job = _job(RELEASE, "published-smoke")
    assert "    needs: pypi\n" in job
    assert "name: dist" in job
    assert (
        'scripts/smoke-release.sh published "${GITHUB_REF_NAME#v}" "${wheels[0]}"'
        in job
    )


def test_pull_requests_smoke_the_built_wheel() -> None:
    assert "run: make smoke-candidate" in _job(TEST, "candidate-smoke")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "usage:"),
        (["candidate"], "usage:"),
        (["nightly", "x"], "usage:"),
        (["candidate", "missing.whl"], "candidate wheel not found: missing.whl"),
        (["candidate", "README.md"], "not a punt-kit wheel: README.md"),
        (["published", "1.0.0", "missing.whl"], "candidate wheel not found"),
    ],
)
def test_smoke_rejects_bad_arguments_before_installing(
    args: list[str], message: str
) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert "Smoke testing" not in result.stdout


@pytest.mark.parametrize(
    ("tag_version", "matches"),
    [("0.20.0rc1", True), ("0.20.0-rc.1", True), ("0.20.0", False), ("0.19.0", False)],
)
def test_candidate_wheel_must_match_the_tag_version(
    tmp_path: Path, tag_version: str, matches: bool
) -> None:
    wheel = tmp_path / "punt_kit-0.20.0rc1-py3-none-any.whl"
    wheel.write_bytes(b"")
    result = subprocess.run(
        ["bash", str(SCRIPT), "candidate", str(wheel), tag_version],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    mismatch = f"wheel version 0.20.0rc1 is not the expected {tag_version}"
    # A match moves on to installing the empty wheel, which fails later.
    assert result.returncode != 0
    assert (mismatch in result.stderr) is not matches
    assert ("Smoke testing candidate" in result.stdout) is matches
