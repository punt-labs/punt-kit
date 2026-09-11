"""Phase 1: pre-flight checks — clean tree, up to date with origin, ready
siblings, and (unless dry-run) quality gates."""

from __future__ import annotations

import json
import re
import shlex
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.siblings import PROPAGATION_SIBLINGS, SiblingRepo
from punt_kit.phases.shared.timeouts import GIT_NETWORK, QUALITY_GATE

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()

# Repo-relative paths of tracked Config-zone files a *running daemon*
# rewrites continuously (standards/punt-labs-dir.md § 7). A repo with an
# active vox session routinely shows this file `modified` in the working
# tree even though nothing about the release is at stake — the clean-tree
# gate below still fails the release (no auto-stash — see the gate's
# comment), but names the exact stash command instead of the generic
# dirty-tree message when this is the *only* thing dirty. Deliberately a
# small, explicit allowlist rather than a path-shape heuristic: lux's
# `.punt-labs/lux/config.md` looks identical in shape but is NOT
# daemon-rewritten (only `enable`/`disable` write it), so it must not be
# on this list. Extend it only when a standard names another file as
# continuously daemon-rewritten.
_DAEMON_MUTABLE_PATHS = frozenset({".punt-labs/vox/vox.md"})


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

        # Not `.stdout.strip()` — porcelain's XY status code can start with
        # a literal space (e.g. " M path" for an unstaged-only
        # modification), and stripping the whole block eats that space
        # whenever it lands as the very first character of the output
        # (the alphabetically-first dirty path), corrupting `ln[3:]`
        # below by one character. `splitlines()` on the raw stdout needs
        # no such strip — a trailing newline produces no extra element,
        # and an empty status yields an empty list either way.
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
            ops.fail(self._dirty_tree_message(dirty_lines))
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

            # A prior release cut outside this flow (a corrective/manual tag)
            # leaves the highest tag's plugin manifest in a shape this
            # release did not produce — warn loudly rather than fail, since
            # the release under way is exactly how the situation gets fixed
            # (ethos v4.16.0 is the precedent).
            self._warn_stale_prior_tag(info)

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
            makefile = info.root / "Makefile"
            if makefile.exists():
                # Prefer the project's own Makefile — a project with optional
                # heavy extras (e.g. a `[display]` extra, pyright-via-npx, an
                # OO ratchet) knows how to gate itself. Bare `uv run
                # mypy/pyright` against the base wheel env reports false
                # errors for code that only imports the extra.
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

    def _dirty_tree_message(self, dirty_lines: list[str]) -> str:
        """Build the "working tree is not clean" failure message.

        ``dirty_lines`` are raw ``git status --porcelain`` lines for
        tracked, modified paths (untracked paths are reported separately).
        When every dirty path is a known daemon-mutable settings file
        (``_DAEMON_MUTABLE_PATHS``), the message names the exact stash
        command instead of the generic dump — the common case for a repo
        with an active vox session, where the operator's fix is always the
        same two commands. Mixed dirt (a daemon file plus anything else)
        keeps the generic message shape, since the operator still has real
        cleanup to do, but still calls out which paths are daemon-mutable
        so the stash step isn't rediscovered by hand. This does not
        auto-stash — that touches the interrupt/resume paths and is a
        separate change.
        """
        dirty = "\n".join(dirty_lines)
        daemon_paths = sorted(
            p
            for ln in dirty_lines
            if (p := ln[3:] if len(ln) > 3 else "") in _DAEMON_MUTABLE_PATHS
        )
        if not daemon_paths:
            return f"Working tree is not clean:\n{dirty}"

        stash_cmd = "git stash push -- " + " ".join(
            shlex.quote(p) for p in daemon_paths
        )
        if len(daemon_paths) == len(dirty_lines):
            return (
                "Working tree has only daemon-mutable settings files dirty "
                f"(standards/punt-labs-dir.md § 7):\n{dirty}\n\n"
                "Stash them before releasing, then restore them after:\n"
                f"  {stash_cmd}\n"
                "  (after the release completes) git stash pop"
            )
        daemon_list = "\n".join(f"  {p}" for p in daemon_paths)
        return (
            f"Working tree is not clean:\n{dirty}\n\n"
            "Note: the following are daemon-mutable settings files "
            "(standards/punt-labs-dir.md § 7) — once the rest is cleaned "
            f"up, stash and restore them with `{stash_cmd}` / "
            f"`git stash pop`:\n{daemon_list}"
        )

    def _warn_stale_prior_tag(self, info: ProjectInfo) -> None:
        """Warn when the highest existing tag's plugin manifest is stale.

        A tag cut outside ``punt release`` (a hand-run corrective release, an
        aborted run that still pushed a tag, etc.) can leave the manifest at
        that tag in the dev shell's name or at a version that does not match
        the tag itself. Neither condition blocks the release under way —
        that release is exactly what corrects it — but an operator who did
        not expect the prior tag to be out of shape needs to know.

        Silent when there are no tags at all, or when the manifest did not
        exist at the highest tag's path (a pre-DES-025 layout move since that
        tag, or a genuinely fresh project) — there is nothing to compare.
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
            data = cast("dict[str, object]", json.loads(show.stdout))
        except json.JSONDecodeError:
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
                "release will correct it (see ethos v4.16.0 for precedent) "
                "— verify that is what you expect."
            )
