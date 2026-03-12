"""punt release — deterministic release workflow for Punt Labs projects."""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn, cast

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect

console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 7200,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with standard options."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )


def _fail(msg: str) -> NoReturn:
    """Print error and exit."""
    console.print(f"[red]Error:[/red] {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def _info(msg: str) -> None:
    console.print(f"  [dim]▶[/dim] {msg}")


def _dry(msg: str) -> None:
    console.print(f"  [yellow]DRY[/yellow] {msg}")


def _get_project_version(info: ProjectInfo) -> str:
    """Extract current version from pyproject.toml."""
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    project = info.pyproject.get("project")
    if not isinstance(project, dict):
        _fail("No [project] section in pyproject.toml")
    version = cast("dict[str, object]", project).get("version")
    if not isinstance(version, str):
        _fail("No version in pyproject.toml [project]")
    return version


def _get_package_name(info: ProjectInfo) -> str:
    """Extract package name from pyproject.toml."""
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    project = info.pyproject.get("project")
    if not isinstance(project, dict):
        _fail("No [project] section in pyproject.toml")
    name = cast("dict[str, object]", project).get("name")
    if not isinstance(name, str):
        _fail("No name in pyproject.toml [project]")
    return name


def _find_package_dir(info: ProjectInfo) -> Path | None:
    """Find the Python package directory (src layout)."""
    src_dir = info.root / "src"
    if not src_dir.is_dir():
        return None
    for child in sorted(src_dir.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            return child
    return None


def _get_github_repo(root: Path) -> str | None:
    """Extract GitHub owner/repo from git remote."""
    try:
        result = _run(
            ["git", "remote", "get-url", "origin"], cwd=str(root), check=False
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        if url.startswith("git@github.com:"):
            return url.removeprefix("git@github.com:").removesuffix(".git")
        if "github.com/" in url:
            return url.split("github.com/")[1].removesuffix(".git")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _read_changelog(root: Path) -> str:
    """Read CHANGELOG.md content."""
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        _fail("CHANGELOG.md not found")
    return changelog.read_text(encoding="utf-8")


def _extract_version_notes(changelog: str, version: str) -> str:
    """Extract release notes for a specific version from changelog."""
    # Match ## [X.Y.Z] - YYYY-MM-DD or ## [X.Y.Z]
    pattern = rf"## \[{re.escape(version)}\][^\n]*\n"
    match = re.search(pattern, changelog)
    if not match:
        return f"Release v{version}"

    start = match.end()
    # Find next ## heading
    next_heading = re.search(r"\n## \[", changelog[start:])
    end = start + next_heading.start() if next_heading else len(changelog)

    return changelog[start:end].strip()


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


def _phase1_preflight(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 1: Pre-flight checks."""
    console.print("\n[bold]Phase 1: Pre-flight[/bold]")

    # 1a. Git state
    branch = _run(
        ["git", "branch", "--show-current"], cwd=str(info.root)
    ).stdout.strip()
    if branch != "main":
        _fail(f"Must be on main branch (currently on '{branch}')")
    _ok("On main branch")

    status = _run(["git", "status", "--porcelain"], cwd=str(info.root)).stdout.strip()
    if status:
        _fail(f"Working tree is not clean:\n{status}")
    _ok("Working tree clean (no modified or untracked files)")

    fetch = _run(["git", "fetch", "origin"], cwd=str(info.root), check=False)
    if fetch.returncode != 0:
        _fail(f"git fetch origin failed:\n{fetch.stderr.strip()}")
    diff = _run(
        ["git", "diff", "HEAD", "origin/main", "--stat"],
        cwd=str(info.root),
        check=False,
    )
    if diff.returncode != 0:
        _fail(f"git diff failed:\n{diff.stderr.strip()}")
    if diff.stdout.strip():
        _fail(f"Not up to date with origin/main:\n{diff.stdout.strip()}")
    _ok("Up to date with origin/main")

    # 1b. Project type (already detected)
    if info.is_hybrid:
        ptype = "hybrid"
    elif info.is_plugin:
        ptype = "plugin"
    else:
        ptype = "CLI-only"
    _ok(f"Project type: {ptype}")

    if info.is_hybrid:
        release_script = info.root / "scripts" / "release-plugin.sh"
        restore_script = info.root / "scripts" / "restore-dev-plugin.sh"
        if not release_script.exists() or not restore_script.exists():
            _fail("Missing release-plugin.sh or restore-dev-plugin.sh")
        _ok("Release/restore scripts present")

    # 1c. Changelog check
    changelog = _read_changelog(info.root)
    if "## [Unreleased]" not in changelog:
        _fail("No [Unreleased] section in CHANGELOG.md")

    unreleased_match = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased_match or not unreleased_match.group(1).strip():
        _fail("[Unreleased] section is empty — nothing to release")
    _ok("Changelog has unreleased entries")

    # 1d. Quality gates
    if not dry_run and info.language == "python":
        _info("Running quality gates...")
        gates = [
            ["uv", "run", "ruff", "check", "src/", "tests/"],
            ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
            ["uv", "run", "mypy", "src/", "tests/"],
            ["uv", "run", "pyright", "src/", "tests/"],
            ["uv", "run", "pytest", "tests/", "-v"],
        ]
        for gate in gates:
            result = _run(gate, cwd=str(info.root), check=False, capture=False)
            if result.returncode != 0:
                _fail(f"Quality gate failed: {' '.join(gate)}")
        _ok("All quality gates passed")
    elif dry_run:
        _dry("Would run quality gates")


def _suggest_version(changelog: str, current: str) -> str:
    """Suggest a version bump based on changelog content."""
    unreleased = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased:
        return current

    content = unreleased.group(1)
    parts = current.split(".")
    if len(parts) != 3:
        return current

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    # Check for breaking changes only within the ### Changed subsection
    changed_match = re.search(r"### Changed\n(.*?)(?=\n### |\Z)", content, re.DOTALL)
    has_breaking = (
        changed_match is not None and "breaking" in changed_match.group(1).lower()
    )
    if has_breaking:
        return f"{major + 1}.0.0"
    if "### Added" in content:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _phase2_version_bump(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 2: Bump version in all locations."""
    console.print(f"\n[bold]Phase 2: Version bump → {version}[/bold]")

    root = info.root

    # 2b. Bump version in pyproject.toml
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        new_content = re.sub(
            r'^(version\s*=\s*")[^"]*(")',
            rf"\g<1>{version}\2",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if dry_run:
            _dry(f'pyproject.toml: version = "{version}"')
        else:
            pyproject_path.write_text(new_content, encoding="utf-8")
            _ok(f'pyproject.toml: version = "{version}"')

    # Bump __init__.py __version__
    pkg_dir = _find_package_dir(info)
    if pkg_dir is not None:
        init_py = pkg_dir / "__init__.py"
        if init_py.exists():
            content = init_py.read_text(encoding="utf-8")
            if "__version__" in content:
                new_content = re.sub(
                    r'^(__version__\s*=\s*")[^"]*(")',
                    rf"\g<1>{version}\2",
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
                if dry_run:
                    _dry(f'{init_py.name}: __version__ = "{version}"')
                else:
                    init_py.write_text(new_content, encoding="utf-8")
                    _ok(f'{init_py.name}: __version__ = "{version}"')

    # Bump plugin.json version
    plugin_json = root / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        data["version"] = version
        if dry_run:
            _dry(f'plugin.json: version = "{version}"')
        else:
            plugin_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            _ok(f'plugin.json: version = "{version}"')

    # Bump install.sh VERSION pin
    install_sh = root / "install.sh"
    if install_sh.exists():
        content = install_sh.read_text(encoding="utf-8")
        new_content = re.sub(
            r'^(VERSION=")[^"]*(")',
            rf"\g<1>{version}\2",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if new_content != content:
            if dry_run:
                _dry(f'install.sh: VERSION="{version}"')
            else:
                install_sh.write_text(new_content, encoding="utf-8")
                _ok(f'install.sh: VERSION="{version}"')

    # 2c. Update CHANGELOG.md
    changelog_path = root / "CHANGELOG.md"
    if changelog_path.exists():
        today = datetime.date.today().isoformat()
        content = changelog_path.read_text(encoding="utf-8")
        new_content = content.replace(
            "## [Unreleased]",
            f"## [Unreleased]\n\n## [{version}] - {today}",
            1,
        )
        if dry_run:
            _dry(f"CHANGELOG.md: [Unreleased] → [{version}] - {today}")
        else:
            changelog_path.write_text(new_content, encoding="utf-8")
            _ok(f"CHANGELOG.md: [{version}] - {today}")

    # 2d. Refresh lock file and commit
    if dry_run:
        _dry("uv lock (refresh lock file)")
        _dry(f'git commit -m "chore: release v{version}"')
    else:
        lock_file = root / "uv.lock"
        if lock_file.exists():
            _run(["uv", "lock"], cwd=str(root))
            _ok("uv.lock refreshed")
        _run(["git", "add", "-A"], cwd=str(root))
        _run(
            ["git", "commit", "-m", f"chore: release v{version}"],
            cwd=str(root),
        )
        _ok("Release commit created")


def _phase3_build(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 3: Build validation."""
    if info.language != "python":
        return

    console.print("\n[bold]Phase 3: Build validation[/bold]")

    if dry_run:
        _dry("rm -rf dist/ && uv build && uvx twine check dist/*")
        return

    dist = info.root / "dist"
    if dist.exists():
        shutil.rmtree(dist)

    _run(["uv", "build"], cwd=str(info.root), capture=False)

    # twine check on built artifacts only (.whl and .tar.gz)
    dist_dir = info.root / "dist"
    artifacts = sorted(p for p in dist_dir.iterdir() if p.suffix in {".whl", ".gz"})
    if not artifacts:
        _fail("No build artifacts found in dist/ for twine check")

    result = _run(
        ["uvx", "twine", "check", *[str(p) for p in artifacts]],
        cwd=str(info.root),
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        _fail(f"twine check failed:\n{result.stdout}\n{result.stderr}")
    _ok("Build artifacts pass twine check")


def _phase4_tag_push(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 4: Plugin swap, tag, push, restore."""
    console.print(f"\n[bold]Phase 4: Tag and push v{version}[/bold]")

    root = info.root

    # 4a. Plugin swap (hybrid only)
    if info.is_hybrid:
        release_script = root / "scripts" / "release-plugin.sh"
        if dry_run:
            _dry("bash scripts/release-plugin.sh")
        else:
            _run(["bash", str(release_script)], cwd=str(root), capture=False)
            _ok("Plugin swapped to prod")

    # 4b. Tag
    tag = f"v{version}"
    if dry_run:
        _dry(f"git tag {tag}")
    else:
        _run(["git", "tag", tag], cwd=str(root))
        _ok(f"Tagged {tag}")

    # 4c. Push
    if dry_run:
        _dry(f"git push origin main {tag}")
    else:
        console.print(
            f"\n  [bold yellow]About to push main + {tag} to origin[/bold yellow]"
        )
        _run(["git", "push", "origin", "main", tag], cwd=str(root), capture=False)
        _ok("Pushed to origin")

    # 4d. Restore dev state (hybrid only)
    if info.is_hybrid:
        restore_script = root / "scripts" / "restore-dev-plugin.sh"
        if dry_run:
            _dry("bash scripts/restore-dev-plugin.sh && git push origin main")
        else:
            _run(["bash", str(restore_script)], cwd=str(root), capture=False)
            _run(["git", "push", "origin", "main"], cwd=str(root), capture=False)
            _ok("Dev plugin state restored and pushed")

    # 4e. Bump README install URL SHAs to point to the tagged commit
    _bump_readme_install_sha(info, version, dry_run=dry_run)


def _bump_readme_install_sha(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Update SHA-pinned install.sh URLs in README.md to the tagged commit."""
    root = info.root
    readme_path = root / "README.md"
    install_sh = root / "install.sh"
    if not readme_path.exists() or not install_sh.exists():
        return

    tag = f"v{version}"
    github_repo = _get_github_repo(root)
    if github_repo:
        owner, repo_name = github_repo.split("/", 1)
    else:
        owner, repo_name = "punt-labs", root.name

    # Get the short SHA of the tagged commit
    if dry_run:
        short_sha = "<SHA>"
    else:
        result = _run(
            ["git", "rev-parse", "--short", tag],
            cwd=str(root),
        )
        short_sha = result.stdout.strip()

    content = readme_path.read_text(encoding="utf-8")
    esc_owner = re.escape(owner)
    esc_repo = re.escape(repo_name)

    # Replace SHA-pinned install URLs: <owner>/<repo>/<hex-sha>/install.sh
    new_content = re.sub(
        rf"(raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/)[0-9a-fA-F]{{7,40}}(/install\.sh)",
        rf"\g<1>{short_sha}\2",
        content,
    )

    # Also replace version-tag install URLs: <owner>/<repo>/v1.2.3/install.sh
    new_content = re.sub(
        rf"(raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/)v[0-9]+\.[0-9]+\.[0-9]+(/install\.sh)",
        rf"\g<1>{short_sha}\2",
        new_content,
    )

    if new_content == content:
        return

    if dry_run:
        _dry(f"README.md: install URLs → {short_sha} ({tag})")
        return

    readme_path.write_text(new_content, encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=str(root))
    _run(
        ["git", "commit", "-m", f"chore: bump README install URL to {tag}"],
        cwd=str(root),
    )
    _run(["git", "push", "origin", "main"], cwd=str(root), capture=False)
    _ok(f"README.md: install URLs → {short_sha} ({tag})")


def _phase5_ci_wait(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 5: Wait for CI."""
    console.print("\n[bold]Phase 5: Wait for CI[/bold]")

    tag = f"v{version}"

    if dry_run:
        _dry("gh run list --branch main --limit 5")
        _dry("gh run watch <run-id>")
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found — install from https://cli.github.com")

    # Find the run triggered by the tag push
    _info(f"Looking for CI run triggered by {tag}...")

    # Give CI a moment to start
    import time

    time.sleep(5)

    # Try release workflow first, fall back to any recent run
    release_run = None
    runs: list[dict[str, object]] = []
    for workflow in ["release.yml", ""]:
        cmd = [
            gh,
            "run",
            "list",
            "--limit",
            "3",
            "--json",
            "databaseId,headBranch,event,status,name",
        ]
        if workflow:
            cmd.extend(["--workflow", workflow])
        result = _run(cmd, cwd=str(info.root), check=False)
        if result.returncode != 0:
            continue
        runs = json.loads(result.stdout)
        if runs:
            release_run = runs[0]
            break

    if release_run is None:
        _info("No release workflow run found — checking for any recent run...")
        if runs:
            release_run = runs[0]

    if release_run is None:
        _fail("No CI runs found")

    run_id = release_run["databaseId"]
    _info(f"Watching run {run_id} ({release_run.get('name', 'unknown')})...")

    result = _run(
        [gh, "run", "watch", str(run_id), "--exit-status"],
        cwd=str(info.root),
        check=False,
        capture=False,
        timeout=7200,
    )
    if result.returncode != 0:
        _fail(f"CI run {run_id} failed — fix before continuing")
    _ok("CI passed")


def _phase6_github_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 6: Create GitHub release."""
    console.print(f"\n[bold]Phase 6: GitHub release v{version}[/bold]")

    tag = f"v{version}"

    if dry_run:
        _dry(f'gh release create {tag} --title "{tag}" --notes "..."')
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found")

    changelog = _read_changelog(info.root)
    notes = _extract_version_notes(changelog, version)

    result = _run(
        [gh, "release", "create", tag, "--title", tag, "--notes", notes],
        cwd=str(info.root),
        check=False,
    )
    if result.returncode != 0:
        _fail(f"Failed to create release: {result.stderr}")
    _ok(f"GitHub release {tag} created")


def _phase7_verify_pypi(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 7: Verify PyPI install."""
    if info.language != "python":
        return

    console.print("\n[bold]Phase 7: Verify PyPI install[/bold]")

    package_name = _get_package_name(info)

    if dry_run:
        _dry(f"uv tool install --force --refresh {package_name}=={version}")
        if info.cli_commands:
            _dry(f"{info.cli_commands[0]} doctor (if available)")
        _dry("uv tool install --force --editable .")
        return

    _info(f"Installing {package_name}=={version} from PyPI...")

    # Retry loop — PyPI propagation can take a minute
    for attempt in range(10):
        result = _run(
            [
                "uv",
                "tool",
                "install",
                "--force",
                "--refresh",
                f"{package_name}=={version}",
            ],
            cwd=str(info.root),
            check=False,
            capture=False,
        )
        if result.returncode == 0:
            break
        if attempt < 9:
            _info(f"Attempt {attempt + 1}/10 — waiting 30s for PyPI propagation...")
            import time

            time.sleep(30)
    else:
        _fail(
            f"Failed to install {package_name}=={version} from PyPI after 10 attempts"
        )

    _ok(f"Installed {package_name}=={version} from PyPI")

    # Run doctor if available
    if info.cli_commands:
        cli_name = info.cli_commands[0]
        cli_path = shutil.which(cli_name)
        if cli_path:
            doctor_result = _run([cli_path, "doctor"], check=False, capture=False)
            if doctor_result.returncode == 0:
                _ok(f"{cli_name} doctor passed")

    # Restore editable install
    _info("Restoring editable install...")
    _run(
        ["uv", "tool", "install", "--force", "--editable", "."],
        cwd=str(info.root),
        capture=False,
    )
    _ok("Editable install restored")


# ---------------------------------------------------------------------------
# Sibling repo helpers
# ---------------------------------------------------------------------------


def _resolve_sibling(root: Path, name: str) -> Path | None:
    """Resolve a sibling repo directory.

    Checks root's parent for a sibling named ``name`` with a ``.git``
    directory.  For the self-referential case (e.g. punt-kit updating
    its own install-all.sh), returns root itself when root.name matches.
    """
    parent = root.parent
    sibling = parent / name
    if sibling.is_dir() and (sibling / ".git").exists():
        return sibling
    return None


def _validate_sibling(path: Path, name: str) -> None:
    """Validate a sibling repo is ready for propagation."""
    branch = _run(["git", "branch", "--show-current"], cwd=str(path)).stdout.strip()
    if branch != "main":
        _fail(f"Sibling {name} is on branch '{branch}', expected main")

    # Only block on modified/staged files — untracked files are harmless
    status = _run(["git", "status", "--porcelain"], cwd=str(path)).stdout.strip()
    dirty = "\n".join(ln for ln in status.splitlines() if not ln.startswith("?? "))
    if dirty:
        _fail(f"Sibling {name} has uncommitted changes:\n{dirty}")

    result = _run(
        ["git", "pull", "--ff-only", "origin", "main"],
        cwd=str(path),
        check=False,
    )
    if result.returncode != 0:
        _fail(f"Sibling {name}: git pull --ff-only failed:\n{result.stderr.strip()}")


def _sibling_commit_push(path: Path, files: list[str], message: str, name: str) -> bool:
    """Stage, commit, and push changes in a sibling repo.

    Returns True if a commit was made, False if no changes.
    """
    cwd = str(path)
    status = _run(
        ["git", "status", "--porcelain", "--", *files], cwd=cwd
    ).stdout.strip()
    if not status:
        return False

    for f in files:
        _run(["git", "add", f], cwd=cwd)
    _run(["git", "commit", "-m", message], cwd=cwd)

    result = _run(
        ["git", "push", "origin", "main"], cwd=cwd, check=False, capture=False
    )
    if result.returncode != 0:
        # Retry once: pull, check if change already landed
        _info(f"{name}: push failed, retrying after pull...")
        rebase = _run(
            ["git", "pull", "--rebase", "origin", "main"], cwd=cwd, check=False
        )
        if rebase.returncode != 0:
            _run(["git", "rebase", "--abort"], cwd=cwd, check=False)
            _fail(
                f"{name}: rebase conflict during push retry — "
                "resolve manually and re-run the release"
            )
        retry = _run(
            ["git", "push", "origin", "main"], cwd=cwd, check=False, capture=False
        )
        if retry.returncode != 0:
            _fail(f"{name}: push still failing after rebase — resolve manually")
    return True


# ---------------------------------------------------------------------------
# Phase 8: Local propagation
# ---------------------------------------------------------------------------


def _propagate_install_all(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """8a. Update project's install.sh SHA in punt-kit/install-all.sh."""
    if not (info.root / "install.sh").exists():
        return

    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]

    sibling = _resolve_sibling(info.root, "punt-kit")
    if sibling is None:
        _fail("Sibling punt-kit not found — required for install-all.sh propagation")
        return  # unreachable, makes type checker happy

    install_all = sibling / "install-all.sh"
    if not install_all.exists():
        _fail("install-all.sh not found in punt-kit — required for propagation")
        return  # unreachable

    tag = f"v{version}"
    if dry_run:
        _dry(f"../punt-kit/install-all.sh: {project_name} SHA → <tag-sha> ({tag})")
        return

    _validate_sibling(sibling, "punt-kit")

    tag_sha = _run(
        ["git", "rev-parse", "--short", f"{tag}^{{commit}}"], cwd=str(info.root)
    ).stdout.strip()

    content = install_all.read_text(encoding="utf-8")
    esc = re.escape(project_name)
    pattern = rf"(\$GH/{esc}/)[0-9a-fA-F]{{7,40}}(/install\.sh)"
    new_content, count = re.subn(pattern, rf"\g<1>{tag_sha}\2", content)

    if count == 0:
        _fail(
            f"install-all.sh: no entry found for {project_name!r} "
            "— cannot propagate install SHA"
        )

    if new_content == content:
        _ok(f"install-all.sh: {project_name} SHA already current")
        return

    install_all.write_text(new_content, encoding="utf-8")

    if _sibling_commit_push(
        sibling,
        ["install-all.sh"],
        f"chore: update {project_name} install SHA to {tag}",
        "punt-kit",
    ):
        _ok(f"install-all.sh: {project_name} SHA → {tag_sha} ({tag})")


def _propagate_marketplace(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """8b. Update version and ref in claude-plugins marketplace.json."""
    if not info.is_plugin and not info.is_hybrid:
        return

    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]
    tag = f"v{version}"

    sibling = _resolve_sibling(info.root, "claude-plugins")
    if sibling is None:
        _fail("Sibling claude-plugins not found — required for marketplace propagation")
        return

    marketplace_path = sibling / ".claude-plugin" / "marketplace.json"
    if not marketplace_path.exists():
        _fail("marketplace.json not found in claude-plugins")
        return

    if dry_run:
        _dry(
            f"../claude-plugins/marketplace.json: "
            f"{project_name} version={version}, ref={tag}"
        )
        return

    _validate_sibling(sibling, "claude-plugins")

    raw = json.loads(marketplace_path.read_text(encoding="utf-8"))
    data = cast("dict[str, object]", raw)
    plugins = cast("list[dict[str, object]]", data.get("plugins", []))

    found = False
    for plugin in plugins:
        src = cast("dict[str, str]", plugin.get("source", {}))
        repo_url = str(src.get("repo", ""))
        if repo_url.endswith("/" + project_name) or plugin.get("name") == project_name:
            plugin["version"] = version
            if "source" not in plugin:
                plugin["source"] = src
            src["ref"] = tag
            found = True
            break

    if not found:
        _fail(
            f"No marketplace entry for {project_name} in marketplace.json "
            "— required for plugin/hybrid releases"
        )

    marketplace_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    if _sibling_commit_push(
        sibling,
        [".claude-plugin/marketplace.json"],
        f"chore: bump {project_name} to {tag} in marketplace",
        "claude-plugins",
    ):
        _ok(f"marketplace: {project_name} version={version}, ref={tag}")
    else:
        _ok(f"marketplace: {project_name} already current")


def _propagate_profile(info: ProjectInfo, *, dry_run: bool) -> None:
    """8c. Update .github profile README with punt-kit HEAD SHA."""
    repo = _get_github_repo(info.root)
    if repo != "punt-labs/punt-kit":
        return

    sibling = _resolve_sibling(info.root, ".github")
    if sibling is None:
        _info("Sibling .github not found — skipping profile update")
        return

    readme = sibling / "profile" / "README.md"
    if not readme.exists():
        _info(".github/profile/README.md not found — skipping")
        return

    # Get punt-kit's current main HEAD (includes the 8a commit)
    punt_kit_sha = _run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=str(info.root)
    ).stdout.strip()

    if dry_run:
        _dry(f"../.github/profile/README.md: install-all.sh SHA → {punt_kit_sha}")
        return

    _validate_sibling(sibling, ".github")

    content = readme.read_text(encoding="utf-8")
    new_content, count = re.subn(
        r"(punt-labs/punt-kit/)[0-9a-fA-F]{7,40}(/install-all\.sh)",
        rf"\g<1>{punt_kit_sha}\2",
        content,
    )

    if count == 0:
        _fail(
            "profile/README.md: no install-all.sh URL found "
            "matching punt-labs/punt-kit/<sha>/install-all.sh"
        )

    if new_content == content:
        _ok("profile: install-all.sh SHA already current")
        return

    readme.write_text(new_content, encoding="utf-8")

    if _sibling_commit_push(
        sibling,
        ["profile/README.md"],
        f"chore: update install-all.sh SHA to {punt_kit_sha}",
        ".github",
    ):
        _ok(f"profile: install-all.sh SHA → {punt_kit_sha}")


def _propagate_website(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """8d. Update version in public-website projects.json."""
    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]

    sibling = _resolve_sibling(info.root, "public-website")
    if sibling is None:
        _info("Sibling public-website not found — skipping website update")
        return

    projects_json = sibling / "src" / "data" / "projects.json"
    if not projects_json.exists():
        _info("projects.json not found in public-website — skipping")
        return

    if dry_run:
        _dry(f"../public-website/projects.json: {project_name} version={version}")
        return

    _validate_sibling(sibling, "public-website")

    data = json.loads(projects_json.read_text(encoding="utf-8"))

    found = False
    for project in data:
        github_url = project.get("githubUrl") or ""
        if project.get("id") == project_name or github_url.endswith("/" + project_name):
            project["version"] = version
            # Update installCommand SHA if present
            install_cmd = project.get("installCommand") or ""
            if install_cmd and f"/{project_name}/" in install_cmd:
                tag = f"v{version}"
                tag_sha = _run(
                    ["git", "rev-parse", "--short", f"{tag}^{{commit}}"],
                    cwd=str(info.root),
                ).stdout.strip()
                project["installCommand"] = re.sub(
                    rf"({re.escape(project_name)}/)[0-9a-fA-F]{{7,40}}"
                    r"(/install\.sh)",
                    rf"\g<1>{tag_sha}\2",
                    install_cmd,
                )
            found = True
            break

    if not found:
        _info(f"No website entry for {project_name} — skipping")
        return

    projects_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    if _sibling_commit_push(
        sibling,
        ["src/data/projects.json"],
        f"chore: bump {project_name} to v{version}",
        "public-website",
    ):
        _ok(f"website: {project_name} version={version}")
    else:
        _ok(f"website: {project_name} already current")


def _phase8_propagate(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 8: Local cross-repo propagation."""
    console.print("\n[bold]Phase 8: Propagate[/bold]")

    # Order matters: 8a before 8c (profile depends on punt-kit HEAD after 8a)
    _propagate_install_all(info, version, dry_run=dry_run)
    _propagate_marketplace(info, version, dry_run=dry_run)
    _propagate_profile(info, dry_run=dry_run)
    _propagate_website(info, version, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Phase 9: Verify
# ---------------------------------------------------------------------------


def _phase9_verify(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 9: Run release verification checks."""
    console.print("\n[bold]Phase 9: Verify[/bold]")

    if dry_run:
        _dry("Would run release verification checks")
        return

    tag = f"v{version}"
    checks: list[tuple[str, bool, str]] = []

    # 1. Git tag exists
    result = _run(["git", "tag", "--list", tag], cwd=str(info.root), check=False)
    tag_exists = tag in result.stdout.strip()
    checks.append(("Git tag", tag_exists, tag if tag_exists else "not found"))

    # 2. Version consistency (read fresh from disk — info.pyproject is stale
    # after Phase 2 bumps the version)
    pyproject_path = info.root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]*)"', content, re.MULTILINE)
        current = match.group(1) if match else "not found"
        checks.append(("pyproject.toml", current == version, f"version={current}"))

    pkg_dir = _find_package_dir(info)
    if pkg_dir is not None:
        init_py = pkg_dir / "__init__.py"
        if init_py.exists():
            content = init_py.read_text(encoding="utf-8")
            match = re.search(r'__version__\s*=\s*"([^"]*)"', content)
            if match:
                init_ver = match.group(1)
                checks.append(
                    ("__init__.py", init_ver == version, f"__version__={init_ver}")
                )

    plugin_json = info.root / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
        pj_ver = pj_data.get("version", "not found")
        checks.append(("plugin.json", pj_ver == version, f"version={pj_ver}"))

    install_sh = info.root / "install.sh"
    if install_sh.exists():
        content = install_sh.read_text(encoding="utf-8")
        match = re.search(r'VERSION="([^"]*)"', content)
        install_ver = match.group(1) if match else "not found"
        checks.append(("install.sh", install_ver == version, f"VERSION={install_ver}"))

    # 3. Changelog stamped (must have date: ## [X.Y.Z] - YYYY-MM-DD)
    changelog = _read_changelog(info.root)
    stamped = bool(
        re.search(
            rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}",
            changelog,
            re.MULTILINE,
        )
    )
    checks.append(("CHANGELOG", stamped, "stamped" if stamped else "not stamped"))

    # 4. install-all.sh SHA
    if install_sh.exists():
        repo = _get_github_repo(info.root)
        if repo:
            project_name = repo.split("/")[-1]
            sibling = _resolve_sibling(info.root, "punt-kit")
            if not sibling:
                checks.append(("install-all.sh", False, "sibling punt-kit not found"))
            else:
                install_all = sibling / "install-all.sh"
                if not install_all.exists():
                    checks.append(("install-all.sh", False, "install-all.sh not found"))
                else:
                    iac = install_all.read_text(encoding="utf-8")
                    match = re.search(
                        rf"\$GH/{re.escape(project_name)}/"
                        r"([0-9a-fA-F]{7,40})/install\.sh",
                        iac,
                    )
                    if match:
                        sha = match.group(1)
                        vr = _run(
                            ["git", "show", f"{sha}:install.sh"],
                            cwd=str(info.root),
                            check=False,
                        )
                        sha_ok = (
                            f'VERSION="{version}"' in vr.stdout
                            if vr.returncode == 0
                            else False
                        )
                        checks.append(("install-all.sh", sha_ok, f"SHA={sha}"))
                    else:
                        checks.append(("install-all.sh", False, "entry not found"))

    # 5. Marketplace
    if info.is_plugin or info.is_hybrid:
        repo = _get_github_repo(info.root)
        if repo:
            project_name = repo.split("/")[-1]
            sibling = _resolve_sibling(info.root, "claude-plugins")
            if not sibling:
                checks.append(
                    ("marketplace", False, "sibling claude-plugins not found")
                )
            else:
                mp = sibling / ".claude-plugin" / "marketplace.json"
                if not mp.exists():
                    checks.append(("marketplace", False, "marketplace.json not found"))
                else:
                    data = cast(
                        "dict[str, object]",
                        json.loads(mp.read_text(encoding="utf-8")),
                    )
                    plugins = cast("list[dict[str, object]]", data.get("plugins", []))
                    mp_found = False
                    for p in plugins:
                        src = cast("dict[str, str]", p.get("source", {}))
                        if (
                            str(src.get("repo", "")).endswith("/" + project_name)
                            or p.get("name") == project_name
                        ):
                            mp_ver = str(p.get("version", ""))
                            mp_ref = str(src.get("ref", ""))
                            ok = mp_ver == version and mp_ref == tag
                            checks.append(
                                (
                                    "marketplace",
                                    ok,
                                    f"version={mp_ver}, ref={mp_ref}",
                                )
                            )
                            mp_found = True
                            break
                    if not mp_found:
                        checks.append(
                            ("marketplace", False, f"no entry for {project_name}")
                        )

    # 6. Profile (punt-kit only)
    repo = _get_github_repo(info.root)
    if repo == "punt-labs/punt-kit":
        sibling = _resolve_sibling(info.root, ".github")
        if not sibling:
            checks.append(("profile SHA", False, "sibling .github not found"))
        else:
            readme = sibling / "profile" / "README.md"
            if not readme.exists():
                checks.append(("profile SHA", False, "profile/README.md not found"))
            else:
                content = readme.read_text(encoding="utf-8")
                punt_kit_sha = _run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=str(info.root),
                ).stdout.strip()
                sha_in_profile = bool(
                    re.search(
                        rf"punt-labs/punt-kit/{re.escape(punt_kit_sha)}"
                        r"/install-all\.sh",
                        content,
                    )
                )
                checks.append(
                    (
                        "profile SHA",
                        sha_in_profile,
                        f"SHA={punt_kit_sha}",
                    )
                )

    # 7. Website (optional — sibling may not exist)
    if repo:
        project_name = repo.split("/")[-1]
        sibling = _resolve_sibling(info.root, "public-website")
        if sibling:
            pj = sibling / "src" / "data" / "projects.json"
            if pj.exists():
                data = json.loads(pj.read_text(encoding="utf-8"))
                web_found = False
                for entry in data:
                    github_url = entry.get("githubUrl") or ""
                    if entry.get("id") == project_name or github_url.endswith(
                        "/" + project_name
                    ):
                        web_ver = entry.get("version")
                        checks.append(
                            (
                                "website",
                                web_ver == version,
                                f"version={web_ver}",
                            )
                        )
                        web_found = True
                        break
                if not web_found:
                    checks.append(("website", False, f"no entry for {project_name}"))

    # 8. PyPI
    if info.language == "python":
        package_name = _get_package_name(info)
        result = _run(
            ["uv", "run", "pip", "index", "versions", package_name],
            check=False,
        )
        pypi_ok = (
            bool(re.search(rf"\b{re.escape(version)}\b", result.stdout))
            if result.returncode == 0
            else False
        )
        checks.append(("PyPI", pypi_ok, f"{package_name}=={version}"))

    # Print results
    all_pass = True
    for name, passed, detail in checks:
        if passed:
            _ok(f"{name}: {detail}")
        else:
            console.print(f"  [red]✗[/red] {name}: {detail}")
            all_pass = False

    if not all_pass:
        _fail("Some verification checks failed — see above")


def _phase_summary(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Print release summary."""
    tag = f"v{version}"
    package = _get_package_name(info) if info.language == "python" else info.root.name
    if info.is_hybrid:
        ptype = "hybrid"
    elif info.is_plugin:
        ptype = "plugin"
    else:
        ptype = "CLI-only"

    dr = "(dry run) " if dry_run else ""
    console.print(f"\n[bold green]Release {tag} {dr}Complete[/bold green]\n")
    console.print(f"  Package:        {package}")
    console.print(f"  Version:        {version}")
    console.print(f"  Type:           {ptype}")
    console.print(f"  Tag:            {tag}")
    console.print()
    if not dry_run:
        console.print("  Restart Claude Code to pick up marketplace changes.")
    console.print()


# ---------------------------------------------------------------------------
# Phase name → number mapping for --resume-from
# ---------------------------------------------------------------------------

PHASE_NAMES: dict[str, int] = {
    "preflight": 1,
    "bump": 2,
    "build": 3,
    "tag": 4,
    "ci": 5,
    "github-release": 6,
    "pypi": 7,
    "propagate": 8,
    "verify": 9,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_release(
    path: str,
    *,
    version: str | None = None,
    dry_run: bool = False,
    resume_from: str | None = None,
) -> None:
    """Execute the release workflow.

    Phases 1-7 handle the originating repo. Phase 8 propagates to sibling
    repos locally. Phase 9 runs final verification checks.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        _fail(f"{root} is not a directory")

    info = detect(root)

    if info.language is None and not info.is_plugin:
        _fail("Cannot detect project type — is this a Punt Labs project?")

    # Determine start phase
    start = 1
    if resume_from:
        if resume_from not in PHASE_NAMES:
            valid = ", ".join(sorted(PHASE_NAMES.keys()))
            _fail(f"Unknown phase '{resume_from}'. Valid: {valid}")
        start = PHASE_NAMES[resume_from]

    mode = "[bold yellow]DRY RUN[/bold yellow] — " if dry_run else ""
    resume = f" (resuming from phase {start})" if start > 1 else ""
    console.print(f"\n{mode}[bold]punt release[/bold] — {root.name}{resume}")

    # Run preflight before version detection (need clean tree for accurate reads)
    if start <= 1:
        _phase1_preflight(info, dry_run=dry_run)

    # Determine version
    if version is None:
        if start == 1:
            # Fresh release — detect from changelog
            if info.pyproject is None:
                _fail("Version required for plugin-only projects (no pyproject.toml)")
            current = _get_project_version(info)
            changelog = _read_changelog(root)
            version = _suggest_version(changelog, current)
            console.print(
                f"\n  [bold]Suggested version:[/bold] {version} (current: {current})"
            )
            if not dry_run:
                _info(f"Using suggested version {version}")
        else:
            # Resuming — read current version from pyproject.toml
            if info.pyproject is not None:
                version = _get_project_version(info)
                _info(f"Detected version {version} from pyproject.toml")
            else:
                _fail("Cannot determine version — pass it explicitly")
    if start <= 2:
        _phase2_version_bump(info, version, dry_run=dry_run)
    if start <= 3:
        _phase3_build(info, dry_run=dry_run)
    if start <= 4:
        _phase4_tag_push(info, version, dry_run=dry_run)
    if start <= 5:
        _phase5_ci_wait(info, version, dry_run=dry_run)
    if start <= 6:
        _phase6_github_release(info, version, dry_run=dry_run)
    if start <= 7:
        _phase7_verify_pypi(info, version, dry_run=dry_run)
    if start <= 8:
        _phase8_propagate(info, version, dry_run=dry_run)
    if start <= 9:
        _phase9_verify(info, version, dry_run=dry_run)

    _phase_summary(info, version, dry_run=dry_run)
