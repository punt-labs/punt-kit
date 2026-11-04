"""Phase 8 installs what users get (pinned, restarted); Phase 10 feeds the tap."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import detect
from punt_kit.phases.phase08_verify_pypi import Phase8VerifyPypi
from punt_kit.phases.phase10_homebrew import HomebrewTapPropagator
from punt_kit.phases.phase11_verify import Phase11Verify
from punt_kit.phases.shared.command_runner import CommandRunner
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.repo_slug import RepoSlug
from punt_kit.phases.shared.skips import SkipRecorder
from tests.helpers import (
    commit_all,
    fault_ops,
    flat,
    git,
    make_release_project,
    make_sibling,
    project_with_origin,
)

if TYPE_CHECKING:
    from tests.harness.fault_ops import FaultInjectingOps

SERVICE_TABLE = '\n[tool.punt-kit.release.service]\nsystemd = "svc"\n'
CONSTRAINTS = "lancedb==0.40.0\n"
SHOW = ["systemctl", "--user", "show", "svc"]


@dataclass
class Machine:
    """A scripted host: records every non-git command and answers service queries."""

    pids: list[int] = field(default_factory=list[int])
    load_state: str = "loaded"
    calls: list[list[str]] = field(default_factory=list[list[str]])
    constraints_seen: list[str] = field(default_factory=list[str])

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 60,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return CommandRunner.run(
                cmd, cwd=cwd, timeout=timeout, check=check, capture=capture
            )
        self.calls.append(cmd)
        out = ""
        if cmd[:4] == SHOW and "--property=LoadState" in cmd:
            out = self.load_state
        elif cmd[:4] == SHOW and "--property=MainPID" in cmd:
            out = str(self.pids.pop(0) if len(self.pids) > 1 else self.pids[0])
        elif "--constraints" in cmd:
            pins = Path(cmd[cmd.index("--constraints") + 1])
            self.constraints_seen.append(pins.read_text())
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")

    def commands(self, prefix: list[str]) -> list[list[str]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]

    def uv_installs(self) -> list[list[str]]:
        return self.commands(["uv", "tool", "install"])


def _ops(machine: Machine) -> FaultInjectingOps:
    return fault_ops(
        real_run=machine.run,
        passthrough=[["uv"], ["systemctl"], ["launchctl"], ["make"]],
    )


@pytest.fixture(autouse=True)
def _host(monkeypatch: pytest.MonkeyPatch) -> None:
    """systemd is the host's manager; time does not pass."""

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name == "systemctl" else None

    def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(time, "sleep", no_sleep)


def _released_project(
    tmp_path: Path, *, constraints: bool, service: bool = True
) -> Path:
    """A project whose v0.2.0 tag does (or does not) carry install-constraints.txt."""
    root = make_release_project(tmp_path)
    if service:
        with (root / "pyproject.toml").open("a") as f:
            f.write(SERVICE_TABLE)
    if constraints:
        (root / "install-constraints.txt").write_text(CONSTRAINTS)
    commit_all(root, "release")
    git(["tag", "v0.2.0"], cwd=str(root))
    return root


def _phase8(root: Path, machine: Machine) -> None:
    Phase8VerifyPypi(
        detect(root),
        "0.2.0",
        dry_run=False,
        ops=_ops(machine),
    ).run()


# --- Phase 8: constraints ---


def test_phase8_installs_with_the_constraints_from_the_release_tag(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 200])
    _phase8(_released_project(tmp_path, constraints=True), machine)

    first = machine.uv_installs()[0]
    assert first[-3:-1] == ["--constraints", first[-2]]
    assert first[-1] == "test-pkg==0.2.0"
    assert machine.constraints_seen == [CONSTRAINTS]


def test_phase8_reads_constraints_from_the_tag_not_the_working_tree(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 200])
    root = _released_project(tmp_path, constraints=True)
    (root / "install-constraints.txt").write_text("lancedb==9.9.9\n")

    _phase8(root, machine)

    assert machine.constraints_seen == [CONSTRAINTS]


def test_phase8_without_constraints_installs_unpinned_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = Machine(pids=[100, 200])
    _phase8(_released_project(tmp_path, constraints=False), machine)

    assert "--constraints" not in machine.uv_installs()[0]
    assert "unpinned" in flat(capsys.readouterr().out)


def test_phase8_restores_the_editable_install_last(tmp_path: Path) -> None:
    machine = Machine(pids=[100, 200])
    _phase8(_released_project(tmp_path, constraints=True), machine)

    assert machine.uv_installs()[-1][-2:] == ["--editable", "."]


# --- Phase 8: the daemon restart ---


def test_phase8_restarts_the_service_and_passes_when_the_pid_changed(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 200])
    _phase8(_released_project(tmp_path, constraints=True), machine)

    assert machine.commands(["systemctl", "--user", "restart", "svc"]) != []


def test_phase8_fails_when_the_service_keeps_its_pid(tmp_path: Path) -> None:
    machine = Machine(pids=[100])
    with pytest.raises(ReleaseError, match="kept PID 100"):
        _phase8(_released_project(tmp_path, constraints=True), machine)


def test_phase8_does_not_restore_the_editable_install_after_a_failed_restart(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100])
    with pytest.raises(ReleaseError):
        _phase8(_released_project(tmp_path, constraints=True), machine)

    assert all("--editable" not in c for c in machine.uv_installs())


def test_phase8_fails_when_the_service_is_not_running_after_restart(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 0])
    with pytest.raises(ReleaseError, match="not running after restart"):
        _phase8(_released_project(tmp_path, constraints=True), machine)


def test_phase8_skips_the_restart_when_the_project_declares_no_service(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100])
    _phase8(_released_project(tmp_path, constraints=True, service=False), machine)

    assert machine.commands(["systemctl"]) == []


def test_phase8_skips_the_restart_when_the_service_is_not_registered(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100], load_state="not-found")
    _phase8(_released_project(tmp_path, constraints=True), machine)

    assert machine.commands(["systemctl", "--user", "restart"]) == []


# --- Phase 10e: the homebrew-tap ---

TAP_CHANGELOG = (
    "# Changelog\n\n## [Unreleased]\n\n### Changed\n\n- biff: bump to v1.0.0\n"
)


def _brew_project(tmp_path: Path, *, target: bool = True) -> Path:
    info = project_with_origin(tmp_path)
    if target:
        (info.root / "Makefile").write_text(
            "brew-formula: ## regenerate the formula\n\t@echo $(FORMULA_OUT)\n"
        )
    return info.root


def _tap(tmp_path: Path, *, formula: bool = True) -> Path:
    files = {"CHANGELOG.md": TAP_CHANGELOG}
    if formula:
        files["Formula/proj.rb"] = 'class Proj < Formula\n  version "0.1.0"\nend\n'
    return make_sibling(tmp_path, "homebrew-tap", files)


@dataclass
class Merges:
    calls: list[tuple[Path, str, list[str], str, str]] = field(
        default_factory=list[tuple[Path, str, list[str], str, str]]
    )

    def __call__(
        self,
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        self.calls.append((path, branch, files, message, name))
        return True


class FormulaWriter(Machine):
    """``make brew-formula`` stands in for quarry's target: it writes the formula."""

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 60,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "make":
            self.calls.append(cmd)
            out = next(a for a in cmd if a.startswith("FORMULA_OUT=")).split("=", 1)[1]
            target = Path(cmd[2]) / out
            target.write_text('class Proj < Formula\n  version "0.2.0"\nend\n')
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return super().run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)


def _propagate(root: Path, machine: Machine, merges: Merges) -> None:
    ops = _ops(machine)
    HomebrewTapPropagator(
        detect(root),
        ops=ops,
        skips=SkipRecorder(ops=ops),
    ).run("0.2.0", dry_run=False, merge_sibling=merges)


def test_tap_propagation_runs_make_brew_formula_into_the_tap(tmp_path: Path) -> None:
    root = _brew_project(tmp_path)
    _tap(tmp_path)
    machine, merges = FormulaWriter(), Merges()

    _propagate(root, machine, merges)

    assert machine.commands(["make"]) == [
        [
            "make",
            "-C",
            str(root),
            "brew-formula",
            "FORMULA_OUT=../homebrew-tap/Formula/proj.rb",
        ]
    ]


def test_tap_propagation_opens_one_pr_with_the_formula_and_the_changelog(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)
    merges = Merges()

    _propagate(root, FormulaWriter(), merges)

    assert merges.calls == [
        (
            tap,
            "propagate/v0.2.0-proj-homebrew-tap",
            ["Formula/proj.rb", "CHANGELOG.md"],
            "chore: bump proj to v0.2.0",
            "homebrew-tap",
        )
    ]


def test_tap_propagation_files_the_bump_under_unreleased(tmp_path: Path) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)

    _propagate(root, FormulaWriter(), Merges())

    assert (tap / "CHANGELOG.md").read_text() == (
        "# Changelog\n\n## [Unreleased]\n\n### Changed\n\n"
        "- biff: bump to v1.0.0\n- proj: bump to v0.2.0\n"
    )


@pytest.mark.parametrize("why", ["no-target", "no-formula", "no-tap"])
def test_tap_propagation_is_skipped_unless_target_tap_and_formula_exist(
    tmp_path: Path, why: str
) -> None:
    root = _brew_project(tmp_path, target=why != "no-target")
    if why != "no-tap":
        _tap(tmp_path, formula=why != "no-formula")
    machine, merges = FormulaWriter(), Merges()

    _propagate(root, machine, merges)

    assert (machine.commands(["make"]), merges.calls) == ([], [])


# --- Phase 11: the tap formula's version ---


def _verify_tap(tmp_path: Path, formula_text: str) -> str:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)
    (tap / "Formula" / "proj.rb").write_text(formula_text)
    ops = _ops(Machine())
    verify = Phase11Verify(
        detect(root),
        "0.2.0",
        dry_run=False,
        ops=ops,
        skips=SkipRecorder(ops=ops),
    )
    (check,) = verify._homebrew_checks(  # pyright: ignore[reportPrivateUsage]
        RepoSlug("punt-labs", "proj")
    )
    return f"{check.name} {check.passed} {check.detail}"


def test_verify_passes_when_the_tap_formula_is_this_release(tmp_path: Path) -> None:
    assert _verify_tap(tmp_path, 'version "0.2.0"\n') == (
        "homebrew-tap True proj.rb version=0.2.0"
    )


def test_verify_reads_the_version_from_the_formula_url(tmp_path: Path) -> None:
    url = 'url "https://files.pythonhosted.org/p/proj-0.2.0.tar.gz"\n'
    assert _verify_tap(tmp_path, url).startswith("homebrew-tap True")


def test_verify_fails_when_the_tap_formula_is_a_stale_release(tmp_path: Path) -> None:
    assert _verify_tap(tmp_path, 'version "0.1.0"\n') == (
        "homebrew-tap False proj.rb version=0.1.0"
    )
