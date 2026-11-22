"""Check release prerequisites and run quality gates."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Self, cast, final

from packaging.requirements import InvalidRequirement, Requirement
from rich.console import Console

from punt_kit.phases.phase10_homebrew import has_brew_formula_target
from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.siblings import (
    PROPAGATION_SIBLINGS,
    TAP_SIBLING,
    SiblingRepo,
)
from punt_kit.phases.shared.timeouts import GIT_HOOK, QUALITY_GATE

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()

# Keep an explicit allowlist of daemon-written Config-zone paths
# (standards/punt-labs-dir.md PLD-7), not a path-shape heuristic:
# Lux's .punt-labs/lux.md has a separate display-mode API.
_DAEMON_MUTABLE_PATHS = frozenset({".punt-labs/vox/vox.md"})


@final
class Phase1Preflight:
    """Check release prerequisites and run quality gates."""

    __slots__ = ("_dry_run", "_info", "_ops")

    _info: ProjectInfo
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, dry_run: bool, ops: ReleaseOps) -> Self:
        """Create the phase with its release inputs and operations."""
        self = super().__new__(cls)
        self._info = info
        self._dry_run = dry_run
        self._ops = ops
        return self

    def run(self) -> None:
        """Check release prerequisites and run quality gates.

        Raises:
            ReleaseError: A repository, changelog, script, or quality gate fails
                validation.
            subprocess.CalledProcessError: A checked repository command fails.
            subprocess.TimeoutExpired: An external command exceeds its timeout.
        """
        info = self._info
        dry_run = self._dry_run
        ops = self._ops
        _console.print("\n[bold]Phase 1: Pre-flight[/bold]")
        self.check_dependencies()

        branch = ops.run(
            ["git", "branch", "--show-current"], cwd=str(info.root)
        ).stdout.strip()
        if branch != "main":
            ops.fail(f"Must be on main branch (currently on '{branch}')")
        ops.ok("On main branch")

        # Preserve porcelain's leading XY status space so ln[3:] slices the path.
        status = ops.run(["git", "status", "--porcelain"], cwd=str(info.root)).stdout
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
            ops.fail(self._dirty_tree_message(dirty_lines, untracked_lines))
        if untracked_lines:
            # Require explicit handling of untracked files to keep them out of release
            # commits.
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
            timeout=GIT_HOOK,
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

            # Warn rather than block: this release can correct a stale tagged manifest.
            self._warn_stale_prior_tag(info)

        Changelog(info.root, ops=ops).require_unreleased_entries()
        ops.ok("Changelog has unreleased entries")

        # Validate propagation targets before running expensive quality gates.
        siblings_checked = 0
        for sib_name in PROPAGATION_SIBLINGS:
            # A dirty tap must not block a project that does not propagate into it.
            if sib_name == TAP_SIBLING and not has_brew_formula_target(info.root):
                continue
            sibling = SiblingRepo.resolve(info.root, sib_name, ops=ops)
            if sibling is not None:
                sibling.validate()
                siblings_checked += 1
        if siblings_checked > 0:
            ops.ok(f"Sibling repos ready ({siblings_checked} checked)")
        else:
            ops.info("No sibling repos found (propagation will be skipped)")

        if not dry_run and info.language == "python":
            ops.info("Running quality gates...")
            makefile = info.root / "Makefile"
            if makefile.exists():
                # The project's Makefile accounts for optional extras and
                # project-specific gates.
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

    def check_dependencies(self) -> None:
        """Reject dependencies PyPI cannot accept before release side effects."""
        project = cast(
            "dict[str, object]", (self._info.pyproject or {}).get("project", {})
        )
        groups = {
            "[project].dependencies": cast("list[str]", project.get("dependencies", []))
        }
        optional = cast(
            "dict[str, list[str]]", project.get("optional-dependencies", {})
        )
        groups.update(
            (f"[project.optional-dependencies].{name}", dependencies)
            for name, dependencies in optional.items()
        )
        for group, dependencies in groups.items():
            for dependency in dependencies:
                try:
                    requirement = Requirement(dependency)
                except InvalidRequirement:
                    self._ops.fail(
                        f"Invalid project dependency; fix {group} before releasing"
                    )
                if requirement.url:
                    context = (
                        "" if group == "[project].dependencies" else f" in {group}"
                    )
                    self._ops.fail(
                        f"Direct URL dependency{context}: publish {requirement.name} "
                        "to PyPI and pin a version before releasing"
                    )

    def _dirty_tree_message(
        self, dirty_lines: list[str], untracked_lines: list[str]
    ) -> str:
        """Build the "working tree is not clean" failure message.

        Accept raw porcelain lines and report tracked and untracked dirt
        together. Identify daemon-mutable paths and suggest a scoped stash.
        Leave stashing to the operator to avoid interrupt/resume state changes;
        recommend pop --index to preserve staged status as well as content.
        """
        dirty = "\n".join(dirty_lines)
        daemon_paths = sorted(
            p
            for ln in dirty_lines
            if (p := ln[3:] if len(ln) > 3 else "") in _DAEMON_MUTABLE_PATHS
        )
        if not daemon_paths:
            message = f"Working tree is not clean:\n{dirty}"
        else:
            stash_cmd = "git stash push -- " + " ".join(
                shlex.quote(p) for p in daemon_paths
            )
            # A live vox session can rewrite the file between the stash and the next
            # check.
            race_caveat = (
                "A running vox session can rewrite this file again before "
                "the release re-checks — stop the session first, or "
                "expect to redo this stash."
            )
            if len(daemon_paths) == len(dirty_lines):
                message = (
                    "Working tree has only daemon-mutable settings files "
                    f"dirty (standards/punt-labs-dir.md PLD-7):\n{dirty}\n\n"
                    "If this is a deliberate settings change you want in "
                    "the release, commit it instead. Otherwise, stash it "
                    "before releasing and restore it after:\n"
                    f"  {stash_cmd}\n"
                    "  (after the release completes) git stash pop --index\n\n"
                    f"{race_caveat}"
                )
            else:
                daemon_list = "\n".join(f"  {p}" for p in daemon_paths)
                message = (
                    f"Working tree is not clean:\n{dirty}\n\n"
                    "Note: the following are daemon-mutable settings "
                    f"files (standards/punt-labs-dir.md PLD-7):\n{daemon_list}"
                    "\n\nIf the change is deliberate, commit it; "
                    "otherwise, once the rest is cleaned up, stash and "
                    f"restore it with `{stash_cmd}` / "
                    f"`git stash pop --index`. {race_caveat}"
                )
        if untracked_lines:
            untracked = "\n".join(untracked_lines)
            message += (
                "\n\nUntracked files are also present — commit, gitignore, "
                f"or remove them before releasing:\n{untracked}"
            )
        return message

    def _warn_stale_prior_tag(self, info: ProjectInfo) -> None:
        """Warn when the highest existing tag's plugin manifest is stale.

        Skip absent tags or manifests. A dev name or mismatched version warrants
        a warning, not a failure: this release can correct either condition.
        """
        ops = self._ops
        tag_result = ops.run(
            ["git", "tag", "--list", "v*", "--sort=-v:refname"],
            cwd=str(info.root),
            check=False,
        )
        if tag_result.returncode != 0:
            return
        tags = tag_result.stdout.strip().splitlines()
        if not tags:
            return
        tag = tags[0]

        manifest_rel = info.plugin_manifest.relative_to(info.root).as_posix()
        show = ops.run(
            ["git", "show", f"{tag}:{manifest_rel}"],
            cwd=str(info.root),
            check=False,
        )
        if show.returncode != 0:
            return
        try:
            data = JsonFile.parse_object(show.stdout, source=f"{tag}:{manifest_rel}")
        except ReleaseError as exc:
            ops.warn(f"Prior tag {tag}'s manifest could not be checked: {exc}")
            return

        name = str(data.get("name", ""))
        version = str(data.get("version", ""))
        expected_version = tag.removeprefix("v")
        problems: list[str] = []
        if name.endswith("-dev"):
            problems.append(f"name is still '{name}' (not swapped to prod)")
        if version != expected_version:
            problems.append(f"version is '{version}', expected '{expected_version}'")

        if problems:
            ops.warn(
                f"Prior tag {tag}'s {manifest_rel} looks like it was cut "
                f"outside the release flow: {'; '.join(problems)}. This "
                "release will correct it — verify that is what you expect."
            )
