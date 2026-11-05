"""Phase 8 installs what users get (pinned, restarted); Phase 10 feeds the tap."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import detect
from punt_kit.phases.phase01_preflight import Phase1Preflight
from punt_kit.phases.phase08_verify_pypi import Phase8VerifyPypi
from punt_kit.phases.phase10_homebrew import HomebrewTapPropagator, tap_owned_paths
from punt_kit.phases.phase11_verify import Phase11Verify
from punt_kit.phases.shared.command_runner import CommandRunner
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.repo_slug import RepoSlug
from punt_kit.phases.shared.siblings import SiblingRegistry, SiblingRepo
from punt_kit.phases.shared.skips import SkipRecorder
from tests.harness.fault_ops import CompletedProcessSpec, FaultRule
from tests.helpers import (
    commit_all,
    fault_ops,
    flat,
    git,
    git_out,
    make_release_project,
    make_sibling,
    project_with_origin,
)

if TYPE_CHECKING:
    from tests.harness.fault_ops import FaultInjectingOps

SERVICE_TABLE = '\n[tool.punt-kit.release.service]\nsystemd = "svc"\n'
CONSTRAINTS = "lancedb==0.40.0\n"
OVERRIDES = "opencv-python-headless\n"
SHOW = ["systemctl", "--user", "show", "svc"]


@dataclass
class Machine:
    """A scripted host: records every non-git command and answers service queries."""

    pids: list[int] = field(default_factory=list[int])
    load_state: str = "loaded"
    load_rc: int = 0
    load_stderr: str = ""
    editable_rc: int = 0
    calls: list[list[str]] = field(default_factory=list[list[str]])
    constraints_seen: list[str] = field(default_factory=list[str])
    overrides_seen: list[str] = field(default_factory=list[str])

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 60,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return CommandRunner.run(
                cmd,
                cwd=cwd,
                timeout=timeout,
                check=check,
                capture=capture,
                errors=errors,
            )
        self.calls.append(cmd)
        out = ""
        if cmd[:4] == SHOW and "--property=LoadState" in cmd:
            if self.load_rc:
                return subprocess.CompletedProcess(
                    cmd, self.load_rc, "", self.load_stderr
                )
            out = self.load_state
        elif cmd[:2] == ["launchctl", "print"]:
            out = f"service = {{\n\tpid = {self._next_pid()}\n}}"
        elif cmd[-2:] == ["--editable", "."]:
            return subprocess.CompletedProcess(cmd, self.editable_rc, "", "")
        elif cmd[:4] == SHOW and "--property=MainPID" in cmd:
            out = str(self._next_pid())
        elif cmd[:3] == ["uv", "tool", "install"]:
            for flag, seen in (
                ("--constraints", self.constraints_seen),
                ("--overrides", self.overrides_seen),
            ):
                if flag in cmd:
                    seen.append(Path(cmd[cmd.index(flag) + 1]).read_text())
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")

    def _next_pid(self) -> int:
        return self.pids.pop(0) if len(self.pids) > 1 else self.pids[0]

    def commands(self, prefix: list[str]) -> list[list[str]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]

    def uv_installs(self) -> list[list[str]]:
        return self.commands(["uv", "tool", "install"])


def _ops(machine: Machine, *rules: FaultRule) -> FaultInjectingOps:
    return fault_ops(
        rules,
        real_run=machine.run,
        passthrough=[["uv"], ["systemctl"], ["launchctl"], ["make"]],
    )


def _host(monkeypatch: pytest.MonkeyPatch, *tools: str) -> None:
    """The host has these service managers; time does not pass."""

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in tools else None

    def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(time, "sleep", no_sleep)


@pytest.fixture(autouse=True)
def _systemd_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _host(monkeypatch, "systemctl")


def _released_project(
    tmp_path: Path, *, constraints: bool, service: bool = True, overrides: bool = False
) -> Path:
    """A project whose v0.2.0 tag does (or does not) carry install-constraints.txt."""
    root = make_release_project(tmp_path)
    if service:
        with (root / "pyproject.toml").open("a") as f:
            f.write(SERVICE_TABLE)
    if constraints:
        (root / "install-constraints.txt").write_text(CONSTRAINTS)
    if overrides:
        (root / "install-overrides.txt").write_text(OVERRIDES)
    commit_all(root, "release")
    git(["tag", "v0.2.0"], cwd=str(root))
    return root


def _phase8(
    root: Path, machine: Machine, *rules: FaultRule, dry_run: bool = False
) -> SkipRecorder:
    ops = _ops(machine, *rules)
    skips = SkipRecorder(ops=ops)
    Phase8VerifyPypi(detect(root), "0.2.0", dry_run=dry_run, ops=ops, skips=skips).run()
    return skips


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


def test_phase8_restores_the_editable_install_even_when_the_restart_fails(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100])
    with pytest.raises(ReleaseError, match="kept PID 100"):
        _phase8(_released_project(tmp_path, constraints=True), machine)

    assert machine.uv_installs()[-1][-2:] == ["--editable", "."]


def test_phase8_restores_the_editable_install_when_the_pypi_install_fails(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 200])
    failed = FaultRule(
        match=["uv", "tool", "install", "--force", "--refresh"],
        times=None,
        response=CompletedProcessSpec(returncode=1),
    )
    with pytest.raises(ReleaseError, match="after 10 attempts"):
        _phase8(_released_project(tmp_path, constraints=True), machine, failed)

    assert machine.uv_installs()[-1][-2:] == ["--editable", "."]


def test_phase8_reports_a_failed_restore_as_secondary_without_masking_the_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = Machine(pids=[100], editable_rc=1)
    with pytest.raises(ReleaseError, match="kept PID 100"):
        _phase8(_released_project(tmp_path, constraints=True), machine)

    assert "secondary to" in flat(capsys.readouterr().out)


def test_phase8_fails_on_a_failed_restore_when_nothing_else_failed(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 200], editable_rc=1)
    with pytest.raises(ReleaseError, match="editable . failed"):
        _phase8(_released_project(tmp_path, constraints=True), machine)


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


def test_phase8_records_a_manual_action_skip_when_the_service_is_not_loaded(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100], load_state="not-found")
    skips = _phase8(_released_project(tmp_path, constraints=True), machine)

    assert tuple(skips.drain()) == (
        "SKIPPED — manual action required: declared service svc is not loaded "
        "on this host; release verified without a restart",
    )


def test_phase8_fails_when_the_service_manager_cannot_be_queried(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100], load_rc=1, load_stderr="Failed to connect to bus")
    with pytest.raises(ReleaseError, match="Failed to connect to bus"):
        _phase8(_released_project(tmp_path, constraints=True), machine)


@pytest.mark.parametrize(
    "table",
    [
        '\n[tool.punt-kit.release]\nservice = "svc"\n',
        "\n[tool.punt-kit.release.service]\nsystemd = 3\n",
        "\n[tool.punt-kit.release.service]\n",
    ],
    ids=["not-a-table", "non-string-name", "no-name"],
)
def test_phase8_fails_on_an_unusable_service_declaration(
    tmp_path: Path, table: str
) -> None:
    root = _released_project(tmp_path, constraints=True, service=False)
    with (root / "pyproject.toml").open("a") as f:
        f.write(table)

    with pytest.raises(ReleaseError, match="release.service"):
        _phase8(root, Machine(pids=[100, 200]))


def _launchd_project(tmp_path: Path, table: str) -> Path:
    root = _released_project(tmp_path, constraints=True, service=False)
    with (root / "pyproject.toml").open("a") as f:
        f.write(table)
    return root


LAUNCHD_ONLY = '\n[tool.punt-kit.release.service]\nlaunchd = "com.example.svc"\n'
BOTH = (
    '\n[tool.punt-kit.release.service]\nsystemd = "svc"\nlaunchd = "com.example.svc"\n'
)


def test_a_launchd_only_declaration_is_restarted_on_a_host_with_both_managers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _host(monkeypatch, "systemctl", "launchctl")
    machine = Machine(pids=[100, 100, 200])
    _phase8(_launchd_project(tmp_path, LAUNCHD_ONLY), machine)

    assert len(machine.commands(["launchctl", "kickstart"])) == 1
    assert machine.commands(["systemctl"]) == []


@pytest.mark.parametrize(
    ("platform", "restarted_with"),
    [("darwin", "launchctl"), ("linux", "systemctl")],
)
def test_with_both_declared_and_available_the_platforms_manager_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, restarted_with: str
) -> None:
    _host(monkeypatch, "systemctl", "launchctl")
    monkeypatch.setattr(sys, "platform", platform)
    machine = Machine(pids=[100, 100, 200])
    _phase8(_launchd_project(tmp_path, BOTH), machine)

    restarts = machine.commands([restarted_with])
    assert any("restart" in c or "kickstart" in c for c in restarts)


def test_a_declaration_for_an_unavailable_manager_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _host(monkeypatch, "systemctl")
    with pytest.raises(ReleaseError, match="is not available"):
        _phase8(_launchd_project(tmp_path, LAUNCHD_ONLY), Machine(pids=[100]))


# --- Phase 8: install overrides ---


def test_phase8_passes_the_tags_overrides_alongside_the_constraints(
    tmp_path: Path,
) -> None:
    machine = Machine(pids=[100, 200])
    root = _released_project(tmp_path, constraints=True, overrides=True)
    (root / "install-overrides.txt").write_text("working-tree-edit\n")

    _phase8(root, machine)

    first = machine.uv_installs()[0]
    assert "--overrides" in first
    assert (machine.constraints_seen, machine.overrides_seen) == (
        [CONSTRAINTS],
        [OVERRIDES],
    )


def test_phase8_without_overrides_passes_none(tmp_path: Path) -> None:
    machine = Machine(pids=[100, 200])
    _phase8(_released_project(tmp_path, constraints=True), machine)

    assert "--overrides" not in machine.uv_installs()[0]


def test_phase8_overrides_alone_are_still_passed(tmp_path: Path) -> None:
    machine = Machine(pids=[100, 200])
    _phase8(_released_project(tmp_path, constraints=False, overrides=True), machine)

    assert machine.overrides_seen == [OVERRIDES]


def test_phase8_fails_when_reading_the_overrides_errors(tmp_path: Path) -> None:
    broken = FaultRule(
        match=[
            "git",
            "ls-tree",
            "--name-only",
            "v0.2.0",
            "--",
            "install-overrides.txt",
        ],
        response=CompletedProcessSpec(returncode=128, stderr="fatal: bad object"),
    )
    with pytest.raises(ReleaseError, match="bad object"):
        _phase8(
            _released_project(tmp_path, constraints=True, overrides=True),
            Machine(pids=[100, 200]),
            broken,
        )


def test_phase8_dry_run_does_not_claim_the_file_is_absent_at_an_uncreated_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)  # no tag, no constraints file
    _phase8(root, Machine(pids=[100]), dry_run=True)

    out = flat(capsys.readouterr().out)
    assert "would read install-constraints.txt from v0.2.0" in out
    assert "absent" not in out


# --- Phase 8: reading the constraints is not guessing ---


def test_phase8_fails_when_the_release_tag_does_not_resolve(tmp_path: Path) -> None:
    root = make_release_project(tmp_path)  # never tagged
    with pytest.raises(ReleaseError, match="v0.2.0 does not resolve"):
        _phase8(root, Machine(pids=[100, 200]))


def test_phase8_fetches_a_missing_tag_from_origin_once(tmp_path: Path) -> None:
    root = _released_project(tmp_path, constraints=True)
    resolves = FaultRule(
        match=["git", "rev-parse", "--verify", "--quiet"],
        responses=[CompletedProcessSpec(returncode=1), CompletedProcessSpec()],
    )
    fetch = FaultRule(
        match=["git", "fetch", "origin", "tag", "v0.2.0"],
        response=CompletedProcessSpec(),
    )
    machine = Machine(pids=[100, 200])
    _phase8(root, machine, resolves, fetch)

    assert fetch.consumed == 1
    assert machine.constraints_seen == [CONSTRAINTS]


def test_phase8_fails_instead_of_installing_unpinned_when_ls_tree_errors(
    tmp_path: Path,
) -> None:
    broken = FaultRule(
        match=["git", "ls-tree"],
        response=CompletedProcessSpec(returncode=128, stderr="fatal: bad object"),
    )
    machine = Machine(pids=[100, 200])
    with pytest.raises(ReleaseError, match="bad object"):
        _phase8(_released_project(tmp_path, constraints=True), machine, broken)

    assert machine.uv_installs()[:1] == []


def test_phase8_fails_instead_of_installing_unpinned_when_git_show_errors(
    tmp_path: Path,
) -> None:
    broken = FaultRule(
        match=["git", "show"],
        response=CompletedProcessSpec(returncode=128, stderr="fatal: unreadable"),
    )
    machine = Machine(pids=[100, 200])
    with pytest.raises(ReleaseError, match="unreadable"):
        _phase8(_released_project(tmp_path, constraints=True), machine, broken)


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


def _tap(tmp_path: Path, *, formula: bool = True, changelog: bool = True) -> Path:
    files = {"CHANGELOG.md": TAP_CHANGELOG} if changelog else {}
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

    formula_text = 'class Proj < Formula\n  version "0.2.0"\nend\n'

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 60,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "make":
            self.calls.append(cmd)
            out = next(a for a in cmd if a.startswith("FORMULA_OUT=")).split("=", 1)[1]
            target = Path(cmd[2]) / out
            target.write_text(self.formula_text)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return super().run(
            cmd, cwd=cwd, timeout=timeout, check=check, capture=capture, errors=errors
        )


class _BumpedVersionStaleArchive(FormulaWriter):
    formula_text = (
        'class Proj < Formula\n  url "https://h/proj-0.1.0.tar.gz"\n'
        '  version "0.2.0"\nend\n'
    )


def _propagate(root: Path, machine: Machine, merges: Merges) -> SkipRecorder:
    ops = _ops(machine)
    skips = SkipRecorder(ops=ops)
    HomebrewTapPropagator(detect(root), ops=ops, skips=skips).run(
        "0.2.0", dry_run=False, merge_sibling=merges
    )
    return skips


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


def test_tap_propagation_without_a_target_is_silent_and_does_nothing(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path, target=False)
    _tap(tmp_path)
    machine, merges = FormulaWriter(), Merges()

    _propagate(root, machine, merges)

    assert (machine.commands(["make"]), merges.calls) == ([], [])


@pytest.mark.parametrize(
    ("why", "needle"),
    [
        ("no-formula", "Formula/proj.rb does not exist"),
        ("no-tap", "no ../homebrew-tap"),
    ],
)
def test_an_opted_in_project_with_no_tap_or_formula_records_a_manual_skip(
    tmp_path: Path, why: str, needle: str
) -> None:
    root = _brew_project(tmp_path)
    if why != "no-tap":
        _tap(tmp_path, formula=False)
    machine, merges = FormulaWriter(), Merges()

    skips = _propagate(root, machine, merges)

    (notice,) = skips.drain()
    assert needle in notice
    assert "manual action required" in notice
    assert (machine.commands(["make"]), merges.calls) == ([], [])


def test_a_bumped_version_over_a_stale_archive_fails_the_postcondition(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    _tap(tmp_path)

    with pytest.raises(ReleaseError, match=r"0\.1\.0, 0\.2\.0|0\.2\.0, 0\.1\.0"):
        _propagate(root, _BumpedVersionStaleArchive(), Merges())


def test_a_tap_without_a_changelog_records_a_manual_skip_and_still_opens_the_pr(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    _tap(tmp_path, changelog=False)
    merges = Merges()

    skips = _propagate(root, FormulaWriter(), merges)

    (notice,) = skips.drain()
    assert "CHANGELOG.md does not exist" in notice
    assert "manual action required" in notice
    assert [call[2] for call in merges.calls] == [["Formula/proj.rb"]]


def test_a_target_that_ignores_formula_out_fails_naming_the_makefile(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    _tap(tmp_path)

    with pytest.raises(ReleaseError, match=r"Makefile.*not 0\.2\.0"):
        _propagate(root, Machine(), Merges())


class _FailsAfterWriting(FormulaWriter):
    """A target that writes the formula, then dies."""

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 60,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        done = super().run(
            cmd, cwd=cwd, timeout=timeout, check=check, capture=capture, errors=errors
        )
        if cmd[0] == "make":
            return subprocess.CompletedProcess(cmd, 2, "", "")
        return done


def test_a_make_that_fails_after_a_partial_write_is_recovered_by_the_next_run(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)
    with pytest.raises(ReleaseError, match="make brew-formula failed"):
        _propagate(root, _FailsAfterWriting(), Merges())
    assert "0.2.0" in (tap / "Formula" / "proj.rb").read_text()

    ops = _ops(Machine())

    def resolve(base: Path, name: str) -> Path | None:
        sibling = SiblingRepo.resolve(base, name, ops=ops)
        return sibling.path if sibling else None

    SiblingRegistry(ops=ops).reset_all(
        root, resolve=resolve, tap_paths=tap_owned_paths(detect(root), ops=ops)
    )
    merges = Merges()
    _propagate(root, FormulaWriter(), merges)

    assert [call[1] for call in merges.calls] == ["propagate/v0.2.0-proj-homebrew-tap"]


def test_reset_returns_the_tap_from_a_propagation_branch(tmp_path: Path) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)
    git(["checkout", "-b", "propagate/v0.2.0-proj-homebrew-tap"], cwd=str(tap))
    ops = _ops(Machine())

    def resolve(base: Path, name: str) -> Path | None:
        sibling = SiblingRepo.resolve(base, name, ops=ops)
        return sibling.path if sibling else None

    SiblingRegistry(ops=ops).reset_all(
        root, resolve=resolve, tap_paths=tap_owned_paths(detect(root), ops=ops)
    )

    assert git_out(["branch", "--show-current"], cwd=str(tap)) == "main"


def _reset(root: Path) -> None:
    ops = _ops(Machine())

    def resolve(base: Path, name: str) -> Path | None:
        sibling = SiblingRepo.resolve(base, name, ops=ops)
        return sibling.path if sibling else None

    SiblingRegistry(ops=ops).reset_all(
        root, resolve=resolve, tap_paths=tap_owned_paths(detect(root), ops=ops)
    )


def test_reset_leaves_another_tools_dirty_formula_alone(tmp_path: Path) -> None:
    root = _brew_project(tmp_path)
    tap = make_sibling(
        tmp_path,
        "homebrew-tap",
        {"Formula/proj.rb": "a\n", "Formula/other.rb": "b\n", "CHANGELOG.md": "c\n"},
    )
    (tap / "Formula" / "other.rb").write_text("operator edit\n")

    _reset(root)

    assert (tap / "Formula" / "other.rb").read_text() == "operator edit\n"


def test_reset_restores_only_this_projects_formula_and_the_tap_changelog(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)
    (tap / "Formula" / "proj.rb").write_text("partial\n")
    (tap / "CHANGELOG.md").write_text("partial\n")

    _reset(root)

    assert (tap / "CHANGELOG.md").read_text() == TAP_CHANGELOG


def test_a_project_without_the_target_never_has_the_tap_touched(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path, target=False)
    tap = _tap(tmp_path)
    (tap / "Formula" / "proj.rb").write_text("operator edit\n")
    git(["checkout", "-b", "propagate/v0.1.0-proj-homebrew-tap"], cwd=str(tap))

    _reset(root)

    assert (
        (tap / "Formula" / "proj.rb").read_text(),
        git_out(["branch", "--show-current"], cwd=str(tap)),
    ) == ("operator edit\n", "propagate/v0.1.0-proj-homebrew-tap")


@pytest.mark.parametrize("opted_in", [False, True])
def test_a_dirty_tap_blocks_preflight_only_for_a_project_that_uses_it(
    tmp_path: Path, opted_in: bool
) -> None:
    root = make_release_project(tmp_path)
    if opted_in:
        (root / "Makefile").write_text("brew-formula:\n\t@true\n")
        commit_all(root, "makefile")
    git(["fetch", "origin"], cwd=str(root))
    tap = _tap(tmp_path)
    (tap / "Formula" / "proj.rb").write_text("dirty\n")
    ops = _ops(Machine())
    preflight = Phase1Preflight(detect(root), dry_run=True, ops=ops)

    if opted_in:
        with pytest.raises(ReleaseError, match="homebrew-tap has uncommitted"):
            preflight.run()
    else:
        preflight.run()


# --- Phase 11: the tap formula's version ---


def _verify_tap(tmp_path: Path, formula_text: str, *, committed: bool = True) -> str:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)
    (tap / "Formula" / "proj.rb").write_text(
        f"class Proj < Formula\n  {formula_text}end\n"
    )
    if committed:
        commit_all(tap, "formula")
    return _check(root)


def _check(root: Path) -> str:
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
        "homebrew-tap True Formula/proj.rb version=0.2.0"
    )


def test_verify_reads_the_version_from_the_formula_url(tmp_path: Path) -> None:
    url = 'url "https://files.pythonhosted.org/p/proj-0.2.0.tar.gz"\n'
    assert _verify_tap(tmp_path, url).startswith("homebrew-tap True")


def test_verify_fails_when_the_tap_formula_is_a_stale_release(tmp_path: Path) -> None:
    assert _verify_tap(tmp_path, 'version "0.1.5"\n') == (
        "homebrew-tap False Formula/proj.rb version=0.1.5"
    )


def test_verify_reads_the_committed_formula_not_the_working_tree(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)  # main carries 0.1.0
    (tap / "Formula" / "proj.rb").write_text(
        'class Proj < Formula\n  version "0.2.0"\nend\n'
    )  # unmerged

    assert _check(root).startswith("homebrew-tap False")


def test_verify_fails_for_an_opted_in_project_with_no_tap(tmp_path: Path) -> None:
    root = _brew_project(tmp_path)

    assert _check(root) == "homebrew-tap False sibling homebrew-tap not found"


def test_verify_fails_for_an_opted_in_project_whose_formula_is_missing(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    _tap(tmp_path, formula=False)

    assert _check(root) == "homebrew-tap False Formula/proj.rb not on origin/main"


def test_verify_is_silent_for_a_project_without_the_target(tmp_path: Path) -> None:
    root = _brew_project(tmp_path, target=False)
    _tap(tmp_path)
    ops = _ops(Machine())
    verify = Phase11Verify(
        detect(root), "0.2.0", dry_run=False, ops=ops, skips=SkipRecorder(ops=ops)
    )

    assert (
        verify._homebrew_checks(  # pyright: ignore[reportPrivateUsage]
            RepoSlug("punt-labs", "proj")
        )
        == []
    )


def test_verify_reads_origin_main_whatever_branch_the_tap_has_checked_out(
    tmp_path: Path,
) -> None:
    root = _brew_project(tmp_path)
    tap = _tap(tmp_path)  # main carries 0.1.0
    bare = tmp_path / "tap-origin.git"
    git(["clone", "--bare", str(tap), str(bare)], cwd=str(tmp_path))
    git(["remote", "set-url", "origin", str(bare)], cwd=str(tap))
    publisher = tmp_path / "publisher"
    git(["clone", str(bare), str(publisher)], cwd=str(tmp_path))
    git(["config", "user.email", "t@t.com"], cwd=str(publisher))
    git(["config", "user.name", "T"], cwd=str(publisher))
    (publisher / "Formula" / "proj.rb").write_text(
        'class Proj < Formula\n  version "0.2.0"\nend\n'
    )
    commit_all(publisher, "release")
    git(["push", "origin", "main"], cwd=str(publisher))
    git(["checkout", "-b", "side"], cwd=str(tap))

    assert _check(root) == "homebrew-tap True Formula/proj.rb version=0.2.0"


def test_verify_fails_a_bumped_version_over_a_stale_archive(tmp_path: Path) -> None:
    text = 'url "https://h/proj-0.1.0.tar.gz"\n  version "0.2.0"\n  '
    assert _verify_tap(tmp_path, text) == (
        "homebrew-tap False Formula/proj.rb version=0.2.0, 0.1.0"
    )
