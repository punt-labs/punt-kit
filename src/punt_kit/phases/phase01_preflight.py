"""Phase 1: pre-flight checks — clean tree, up to date with origin, ready
siblings, and (unless dry-run) quality gates."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.siblings import PROPAGATION_SIBLINGS, SiblingRepo
from punt_kit.phases.shared.timeouts import GIT_NETWORK, QUALITY_GATE

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase1Preflight:
    """Phase 1: pre-flight checks."""

    __slots__ = ("_dry_run", "_info", "_ops")

    _info: ProjectInfo
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, dry_run: bool, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._dry_run = dry_run
        self._ops = ops
        return self

    def run(self) -> None:
        info = self._info
        dry_run = self._dry_run
        ops = self._ops
        _console.print("\n[bold]Phase 1: Pre-flight[/bold]")

        # 1a. Git state
        branch = ops.run(
            ["git", "branch", "--show-current"], cwd=str(info.root)
        ).stdout.strip()
        if branch != "main":
            ops.fail(f"Must be on main branch (currently on '{branch}')")
        ops.ok("On main branch")

        status = ops.run(
            ["git", "status", "--porcelain"], cwd=str(info.root)
        ).stdout.strip()
        dirty_lines: list[str] = []
        untracked_lines: list[str] = []
        for ln in status.splitlines():
            path = ln[3:] if len(ln) > 3 else ""
            if path == ".beads" or path.startswith(".beads/"):
                continue
            if ln.startswith("?? "):
                untracked_lines.append(ln)
            else:
                dirty_lines.append(ln)
        if dirty_lines:
            dirty = "\n".join(dirty_lines)
            ops.fail(f"Working tree is not clean:\n{dirty}")
        if untracked_lines:
            # Untracked files at release time are almost always noise (temp
            # files, forgotten artifacts) that must not ride along in
            # release commits — force the operator to commit, gitignore, or
            # remove them.
            untracked = "\n".join(untracked_lines)
            ops.fail(
                "Untracked files present — commit, gitignore, or remove them "
                f"before releasing:\n{untracked}"
            )
        ops.ok("Working tree clean")

        fetch = ops.run(
            ["git", "fetch", "origin"],
            cwd=str(info.root),
            check=False,
            timeout=GIT_NETWORK,
        )
        if fetch.returncode != 0:
            ops.fail(f"git fetch origin failed:\n{fetch.stderr.strip()}")
        diff = ops.run(
            ["git", "diff", "HEAD", "origin/main", "--stat"],
            cwd=str(info.root),
            check=False,
        )
        if diff.returncode != 0:
            ops.fail(f"git diff failed:\n{diff.stderr.strip()}")
        if diff.stdout.strip():
            ops.fail(f"Not up to date with origin/main:\n{diff.stdout.strip()}")
        ops.ok("Up to date with origin/main")

        # 1b. Project type (already detected)
        if info.is_hybrid:
            ptype = "hybrid"
        elif info.is_plugin:
            ptype = "plugin"
        else:
            ptype = "CLI-only"
        ops.ok(f"Project type: {ptype}")

        if info.is_hybrid or info.is_plugin:
            release_script = info.root / "scripts" / "release-plugin.sh"
            restore_script = info.root / "scripts" / "restore-dev-plugin.sh"
            if not release_script.exists() or not restore_script.exists():
                ops.fail("Missing release-plugin.sh or restore-dev-plugin.sh")
            ops.ok("Release/restore scripts present")

        # 1c. Changelog check
        changelog = Changelog(info.root, ops=ops).text()
        if "## [Unreleased]" not in changelog:
            ops.fail("No [Unreleased] section in CHANGELOG.md")

        unreleased_match = re.search(
            r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
        )
        if not unreleased_match or not unreleased_match.group(1).strip():
            ops.fail("[Unreleased] section is empty — nothing to release")
        ops.ok("Changelog has unreleased entries")

        # 1d. Sibling repos (propagation targets) must be clean and on main.
        # Check early so we fail before quality gates, not mid-propagation.
        # Also catches stale propagation branches from prior releases.
        siblings_checked = 0
        for sib_name in PROPAGATION_SIBLINGS:
            sibling = SiblingRepo.resolve(info.root, sib_name, ops=ops)
            if sibling is not None:
                sibling.validate()
                siblings_checked += 1
        if siblings_checked > 0:
            ops.ok(f"Sibling repos ready ({siblings_checked} checked)")
        else:
            ops.info("No sibling repos found (propagation will be skipped)")

        # 1e. Quality gates
        if not dry_run and info.language == "python":
            ops.info("Running quality gates...")
            gates = [
                ["uv", "run", "ruff", "check", "src/", "tests/"],
                ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
                ["uv", "run", "mypy", "src/", "tests/"],
                ["uv", "run", "pyright", "src/", "tests/"],
                ["uv", "run", "pytest", "tests/", "-v"],
            ]
            for gate in gates:
                result = ops.run(
                    gate,
                    cwd=str(info.root),
                    check=False,
                    capture=False,
                    timeout=QUALITY_GATE,
                )
                if result.returncode != 0:
                    ops.fail(f"Quality gate failed: {' '.join(gate)}")
            ops.ok("All quality gates passed")
        elif not dry_run and info.language == "go":
            ops.info("Running quality gates...")
            makefile = info.root / "Makefile"
            if makefile.exists():
                result = ops.run(
                    ["make", "check"],
                    cwd=str(info.root),
                    check=False,
                    capture=False,
                    timeout=QUALITY_GATE,
                )
                if result.returncode != 0:
                    ops.fail("Quality gate failed: make check")
            else:
                for gate in [["go", "vet", "./..."], ["go", "test", "-race", "./..."]]:
                    result = ops.run(
                        gate,
                        cwd=str(info.root),
                        check=False,
                        capture=False,
                        timeout=QUALITY_GATE,
                    )
                    if result.returncode != 0:
                        ops.fail(f"Quality gate failed: {' '.join(gate)}")
            ops.ok("All quality gates passed")
        elif dry_run:
            ops.dry("Would run quality gates")
