"""punt audit — compliance check against Punt Labs standards."""

from __future__ import annotations

import importlib.resources
import re
import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rich.console import Console
from rich.markup import escape

from punt_kit.audit_github import GithubSettingsAudit
from punt_kit.audit_permissions import PermissionsAudit
from punt_kit.audit_verdict import FAIL, FIXED, INFO, PASS
from punt_kit.detect import ProjectInfo, detect
from punt_kit.git_checkout import GitCheckout
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.install_urls import InstallUrl, InstallUrlRecognizer
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.text_file import TextFile

if TYPE_CHECKING:
    from collections.abc import Callable

console = Console()

# One audit finding: (status, label, detail).
type _Findings = list[tuple[str, str, str]]

TEMPLATES = importlib.resources.files("punt_kit") / "templates"


def run_audit(path: str, *, fix: bool = False) -> None:
    """Check compliance against Punt Labs standards.

    When *fix* is True, create missing mechanical files from templates.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    try:
        info = detect(root)
    except ReleaseError as exc:
        console.print(f"\n[bold]punt audit[/bold] — {root.name}")
        console.print(f"  {FAIL} Project files are readable")
        console.print(f"      [dim]{escape(str(exc))}[/dim]")
        raise SystemExit(1) from exc

    mode = "[bold]punt audit --fix[/bold]" if fix else "[bold]punt audit[/bold]"
    console.print(f"\n{mode} — {root.name}")
    lang = info.language or "none"
    ptype = info.project_type or "unknown"
    console.print(f"  Language: {lang}  Type: {ptype}\n")

    checks: tuple[Callable[[], _Findings], ...] = (
        partial(_check_ci, info),
        partial(_check_tool_config, info),
        partial(_check_markdownlint, info, fix=fix),
        partial(_check_markdownlint_content, info),
        partial(_check_py_typed, info, fix=fix),
        partial(_check_changelog, info, fix=fix),
        partial(_check_beads, info),
        partial(_check_claude_md, info),
        PermissionsAudit(info).findings,
        partial(_check_makefile, info),
        partial(_check_plugin_dev_isolation, info),
        partial(_check_install_sh, info),
        partial(_check_readme_sha_pins, info),
        partial(_check_plugin_version_sync, info),
        GithubSettingsAudit(info.root).findings,
    )
    results = [finding for check in checks for finding in _guarded(check)]

    # Print results
    passes = 0
    failures = 0
    fixes = 0
    for status, label, detail in results:
        console.print(f"  {status} {label}")
        if detail:
            console.print(f"      [dim]{detail}[/dim]")
        if status == PASS:
            passes += 1
        elif status == FAIL:
            failures += 1
        elif status == FIXED:
            fixes += 1

    summary = f"  [bold]{passes} passed[/bold], [bold]{failures} failed[/bold]"
    if fixes:
        summary += f", [bold yellow]{fixes} fixed[/bold yellow]"
    console.print(f"\n{summary}\n")

    if failures > 0:
        raise SystemExit(1)


def _guarded(check: Callable[[], _Findings]) -> _Findings:
    """Run one check; a file it cannot read becomes a FAIL naming the file.

    Without this one unreadable file would abort the audit and discard every
    finding the other checks had already produced.
    """
    try:
        return check()
    except ReleaseError as exc:
        return [(FAIL, "Project files are readable", escape(str(exc)))]


def _check_ci(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check CI workflow existence per project type."""
    results: list[tuple[str, str, str]] = []
    workflows_dir = info.root / ".github" / "workflows"

    if info.language == "python":
        lint_exists = (workflows_dir / "lint.yml").exists()
        results.append(
            (
                PASS if lint_exists else FAIL,
                "CI lint workflow exists",
                ".github/workflows/lint.yml" if lint_exists else "Missing lint.yml",
            )
        )

        test_exists = (workflows_dir / "test.yml").exists()
        results.append(
            (
                PASS if test_exists else FAIL,
                "CI test workflow exists",
                ".github/workflows/test.yml" if test_exists else "Missing test.yml",
            )
        )

    elif info.language == "node":
        lint_exists = (workflows_dir / "lint.yml").exists()
        results.append(
            (
                PASS if lint_exists else FAIL,
                "CI lint workflow exists",
                ".github/workflows/lint.yml" if lint_exists else "Missing lint.yml",
            )
        )

    elif info.language == "swift":
        build_exists = (workflows_dir / "build.yml").exists()
        results.append(
            (
                PASS if build_exists else FAIL,
                "CI build workflow exists",
                ".github/workflows/build.yml" if build_exists else "Missing build.yml",
            )
        )

    # All repos should have docs.yml
    docs_exists = (workflows_dir / "docs.yml").exists()
    results.append(
        (
            PASS if docs_exists else FAIL,
            "CI docs workflow exists",
            ".github/workflows/docs.yml" if docs_exists else "Missing docs.yml",
        )
    )

    return results


def _check_tool_config(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check language-specific tool configuration."""
    results: list[tuple[str, str, str]] = []

    if info.language != "python":
        return results

    pyproject_path = info.root / "pyproject.toml"
    if not pyproject_path.exists():
        results.append((FAIL, "pyproject.toml exists", "Missing"))
        return results

    data = TextFile(pyproject_path).toml()

    tool_raw = data.get("tool")
    tool = cast("dict[str, object]", tool_raw) if isinstance(tool_raw, dict) else {}

    ruff = tool.get("ruff")
    results.append(
        (
            PASS if ruff else FAIL,
            r"Linting configured (\[tool.ruff])",
            r"in pyproject.toml" if ruff else r"Missing \[tool.ruff] in pyproject.toml",
        )
    )

    mypy = tool.get("mypy")
    results.append(
        (
            PASS if mypy else FAIL,
            r"Type checking configured (\[tool.mypy])",
            r"in pyproject.toml" if mypy else r"Missing \[tool.mypy] in pyproject.toml",
        )
    )

    pyright = tool.get("pyright")
    results.append(
        (
            PASS if pyright else FAIL,
            r"Type checking configured (\[tool.pyright])",
            r"in pyproject.toml"
            if pyright
            else r"Missing \[tool.pyright] in pyproject.toml",
        )
    )

    pytest_raw = tool.get("pytest")
    pytest_cfg = (
        cast("dict[str, object]", pytest_raw).get("ini_options")
        if isinstance(pytest_raw, dict)
        else None
    )
    results.append(
        (
            PASS if pytest_cfg else FAIL,
            r"Test config exists (\[tool.pytest.ini_options])",
            r"in pyproject.toml"
            if pytest_cfg
            else r"Missing \[tool.pytest.ini_options]",
        )
    )

    return results


def _check_markdownlint(info: ProjectInfo, *, fix: bool) -> list[tuple[str, str, str]]:
    """Check markdownlint configuration files."""
    results: list[tuple[str, str, str]] = []

    # Template files stored without dot prefix to avoid setuptools dotfile issues
    configs = {
        ".markdownlint.jsonc": "markdownlint.jsonc",
        ".markdownlint-cli2.jsonc": "markdownlint-cli2.jsonc",
    }

    for filename, template_name in configs.items():
        target = info.root / filename
        if target.exists():
            results.append((PASS, f"{filename} exists", ""))
        elif fix:
            template_ref = TEMPLATES / template_name
            content = template_ref.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8")
            results.append((FIXED, f"{filename} created", ""))
        else:
            results.append(
                (FAIL, f"{filename} exists", "Missing — run punt audit --fix")
            )

    return results


def _check_markdownlint_content(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Run markdownlint-cli2 on tracked markdown files to catch content errors."""
    npx = shutil.which("npx")
    if npx is None:
        return [(INFO, "Markdown lint (npx not available)", "Install Node.js to run")]

    # Only lint git-tracked files to avoid scratch file noise
    tracked_md = _get_tracked_markdown(info.root)
    if not tracked_md:
        return [(INFO, "Markdown lint (no tracked .md files)", "")]

    try:
        result = subprocess.run(
            [npx, "--yes", "markdownlint-cli2", *tracked_md],
            cwd=str(info.root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return [
                (PASS, "Markdown lint passes", f"{len(tracked_md)} file(s) checked")
            ]
        # Count errors from output
        error_lines = [
            line
            for line in result.stdout.splitlines()
            if " error " in line or "MD0" in line
        ]
        return [
            (
                FAIL,
                "Markdown lint passes",
                f"{len(error_lines)} error(s) — run: npx markdownlint-cli2 '**/*.md'",
            )
        ]
    except subprocess.TimeoutExpired:
        return [(INFO, "Markdown lint (timed out)", "")]
    except OSError:
        return [(INFO, "Markdown lint (could not run)", "")]


def _get_tracked_markdown(root: Path) -> list[str]:
    """Get list of git-tracked markdown files relative to root."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "*.md", "**/*.md"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        return [f for f in result.stdout.strip().splitlines() if f.endswith(".md")]
    except (subprocess.TimeoutExpired, OSError):
        return []


def _check_py_typed(info: ProjectInfo, *, fix: bool) -> list[tuple[str, str, str]]:
    """Check py.typed marker file for Python packages."""
    if info.language != "python":
        return []

    pkg_dir = _find_package_dir(info)
    if pkg_dir is None:
        return [(INFO, "py.typed marker", "Could not determine package directory")]

    py_typed = pkg_dir / "py.typed"
    if py_typed.exists():
        return [(PASS, "py.typed marker exists", str(_relpath(py_typed, info.root)))]

    if fix:
        py_typed.write_text("")
        return [(FIXED, "py.typed marker created", str(_relpath(py_typed, info.root)))]

    return [
        (
            FAIL,
            "py.typed marker exists",
            f"Missing {_relpath(py_typed, info.root)} — run punt audit --fix",
        )
    ]


def _check_changelog(info: ProjectInfo, *, fix: bool) -> list[tuple[str, str, str]]:
    """Check CHANGELOG.md exists."""
    changelog = info.root / "CHANGELOG.md"
    if changelog.exists():
        return [(PASS, "CHANGELOG.md exists", "")]

    if fix:
        project_name = _get_project_name(info)
        TextFile(changelog).write(
            f"# Changelog\n\nAll notable changes to {project_name} "
            "will be documented in this file.\n\n"
            "The format is based on "
            "[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).\n"
        )
        return [(FIXED, "CHANGELOG.md created", "")]

    return [(FAIL, "CHANGELOG.md exists", "Missing — run punt audit --fix")]


def _check_beads(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check if beads is initialized."""
    return [
        (
            PASS if info.has_beads else FAIL,
            "Beads initialized",
            ".beads/ directory" if info.has_beads else "Missing .beads/ — run bd init",
        )
    ]


def _check_claude_md(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check if CLAUDE.md exists."""
    return [
        (
            PASS if info.has_claude_md else FAIL,
            "CLAUDE.md exists",
            "" if info.has_claude_md else "Missing CLAUDE.md — run punt init",
        )
    ]


_REQUIRED_MAKE_TARGETS = {"help", "test", "lint", "check", "format"}


def _check_makefile(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check Makefile existence and required targets per makefile.md standard."""
    if info.language is None:
        return []

    results: list[tuple[str, str, str]] = []
    makefile = info.root / "Makefile"

    if not makefile.exists():
        results.append((FAIL, "Makefile exists", "Missing — see standards/makefile.md"))
        return results

    results.append((PASS, "Makefile exists", ""))

    content = TextFile(makefile).read()

    # Check required targets — look for "target:" at line start
    target_re = re.compile(r"^([a-zA-Z_-]+)\s*:", re.MULTILINE)
    found_targets = {m.group(1) for m in target_re.finditer(content)}

    missing = _REQUIRED_MAKE_TARGETS - found_targets
    if missing:
        results.append(
            (
                FAIL,
                "Required Makefile targets present",
                f"Missing: {', '.join(sorted(missing))}",
            )
        )
    else:
        results.append(
            (
                PASS,
                "Required Makefile targets present",
                f"{len(_REQUIRED_MAKE_TARGETS)} required targets found",
            )
        )

    # Check that all targets have ## comments for help extraction
    help_re = re.compile(r"^([a-zA-Z_-]+)\s*:.*##", re.MULTILINE)
    targets_with_help = {m.group(1) for m in help_re.finditer(content)}
    targets_without_help = (found_targets & _REQUIRED_MAKE_TARGETS) - targets_with_help
    if targets_without_help:
        results.append(
            (
                FAIL,
                "Makefile targets have ## help comments",
                f"Missing ## on: {', '.join(sorted(targets_without_help))}",
            )
        )
    else:
        results.append((PASS, "Makefile targets have ## help comments", ""))

    return results


def _check_plugin_dev_isolation(
    info: ProjectInfo,
) -> list[tuple[str, str, str]]:
    """Check plugin repos follow the dev/prod namespace isolation standard.

    Checks:
    1. Exactly one plugin.json — a second one means a half-finished move
    2. plugin.json name ends in -dev (working tree is the dev namespace)
    3. Release/restore scripts exist (hybrid projects only)
    4. Every prod command has a -dev variant
    """
    if not info.is_plugin:
        return []

    results: list[tuple[str, str, str]] = []

    # A stale manifest left behind by an incomplete move to the plugin/
    # layout is worse than a missing one: every reader takes the winning
    # candidate and the loser drifts unnoticed until a release swaps the
    # wrong file.
    if len(info.plugin_manifests) > 1:
        found = ", ".join(
            p.relative_to(info.root).as_posix() for p in info.plugin_manifests
        )
        results.append((FAIL, "Exactly one plugin manifest", f"Found: {found}"))
    else:
        results.append(
            (
                PASS,
                "Exactly one plugin manifest",
                info.plugin_manifest.relative_to(info.root).as_posix(),
            )
        )

    results.extend(_check_plugin_dev_suffix(info))

    # Check release/restore scripts exist. Required of hybrid projects only:
    # plugins.md "Release flow for pure plugins" states a pure plugin may lack
    # scripts/release-plugin.sh and do the swap-tag-restore by hand (DES-007).
    # Failing dungeon, prfaq, and z-spec for following the standard is a
    # false-positive gate, and a gate that cries wolf gets ignored wholesale.
    release_script = info.root / "scripts" / "release-plugin.sh"
    restore_script = info.root / "scripts" / "restore-dev-plugin.sh"
    missing_scripts: list[str] = []
    if not release_script.exists():
        missing_scripts.append("scripts/release-plugin.sh")
    if not restore_script.exists():
        missing_scripts.append("scripts/restore-dev-plugin.sh")
    if not missing_scripts:
        results.append((PASS, "Release/restore scripts exist", ""))
    elif info.is_hybrid:
        results.append(
            (
                FAIL,
                "Release/restore scripts exist",
                f"Missing: {', '.join(missing_scripts)}",
            )
        )
    else:
        results.append(
            (
                INFO,
                "Release/restore scripts exist",
                "Pure plugin — swap-tag-restore is manual (plugins.md, DES-007)",
            )
        )

    # Check -dev command variants. Anchored on the plugin root, not the repo
    # root: under the plugin/ layout the commands moved with the manifest, and
    # a repo-root glob would find nothing and report no findings at all.
    commands_dir = info.plugin_root / "commands"
    if commands_dir.is_dir():
        prod_commands = sorted(
            f.stem for f in commands_dir.glob("*.md") if not f.stem.endswith("-dev")
        )
        dev_commands = sorted(
            f.stem.removesuffix("-dev") for f in commands_dir.glob("*-dev.md")
        )

        if prod_commands:
            missing = [c for c in prod_commands if c not in dev_commands]
            if missing:
                results.append(
                    (
                        FAIL,
                        "Dev command variants exist",
                        f"Missing: {', '.join(f'{c}-dev.md' for c in missing)}",
                    )
                )
            else:
                results.append(
                    (
                        PASS,
                        "Dev command variants exist",
                        f"{len(dev_commands)} dev commands",
                    )
                )
    else:
        # Say the directory is absent instead of emitting no row. A plugin
        # may legitimately ship only hooks or agents, but "the check found
        # nowhere to look" and "the check passed" must not read alike.
        results.append(
            (
                INFO,
                "Dev command variants exist",
                f"No {commands_dir.relative_to(info.root).as_posix()}/ directory",
            )
        )

    return results


def _check_plugin_dev_suffix(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check the working tree's plugin name carries the ``-dev`` suffix."""
    try:
        plugin_name = _read_plugin_field(info, "name")
    except ReleaseError as exc:
        return [(FAIL, "Plugin manifest is readable", str(exc))]
    if plugin_name is None:
        return []
    if plugin_name.endswith("-dev"):
        return [(PASS, "Plugin name has -dev suffix", plugin_name)]
    return [
        (
            FAIL,
            "Plugin name has -dev suffix",
            f"'{plugin_name}' — should be '{plugin_name}-dev'",
        )
    ]


def _check_install_sh(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check that hybrid projects have a compliant install.sh."""
    if not info.is_hybrid:
        return []

    results: list[tuple[str, str, str]] = []
    install_sh = info.root / "install.sh"

    if not install_sh.exists():
        results.append(
            (FAIL, "install.sh exists", "Hybrid project requires install.sh")
        )
        return results

    results.append((PASS, "install.sh exists", ""))

    content = TextFile(install_sh).read()

    if "set -eu" in content:
        results.append((PASS, "install.sh has strict mode", "set -eu"))
    else:
        results.append((FAIL, "install.sh has strict mode", "Missing set -eu"))

    if "marketplace update" in content or "marketplace_update" in content:
        results.append((PASS, "install.sh refreshes marketplace", ""))
    else:
        results.append(
            (
                FAIL,
                "install.sh refreshes marketplace",
                "Missing marketplace update step (DES-003)",
            )
        )

    if "insteadOf" in content:
        results.append((PASS, "install.sh has SSH fallback", ""))
    else:
        results.append(
            (FAIL, "install.sh has SSH fallback", "Missing HTTPS fallback for SSH")
        )

    if "doctor" in content:
        results.append((PASS, "install.sh runs doctor", ""))
    else:
        results.append(
            (FAIL, "install.sh runs doctor", "Missing doctor verification step")
        )

    return results


def _check_readme_sha_pins(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check that README's install URLs for this repository are SHA pins.

    Pins are recognized by ``InstallUrlRecognizer`` under the project's own
    ``owner/repo`` (from its origin remote), the same definition the release
    writes and verifies with: another tool's install one-liner is not this
    project's pin, and a URL naming this repository on a different host is
    reported rather than ignored.
    """
    readme = info.root / "README.md"
    if not readme.exists():
        return []

    content = TextFile(readme).read()
    if "install.sh" not in content and "raw.githubusercontent.com" not in content:
        return []
    try:
        slug = GitCheckout(info.root).github_slug()
    except ValueError as exc:
        return [(INFO, "README install URL pins (not checked)", str(exc))]

    refs = InstallUrlRecognizer.for_slug(slug).scan(content)
    if not refs:
        return []
    label = "README raw GitHub URLs use SHA pins"
    problems = _readme_pin_problems(refs, slug)
    if problems:
        return [(FAIL, label, "; ".join(problems))]
    return [(PASS, label, f"{len(refs)} URL(s) checked")]


def _readme_pin_problems(refs: list[InstallUrl], slug: str) -> list[str]:
    """What is wrong with the install URLs ``refs``, one phrase per kind of problem."""
    problems: list[str] = []
    branches = sorted({r.segment for r in refs if r.is_trusted and not r.is_sha_pin})
    if branches:
        problems.append(f"Branch or tag refs found: {', '.join(branches)}")
    untrusted = sorted({r.url for r in refs if not r.is_trusted})
    if untrusted:
        problems.append(
            f"Not on raw.githubusercontent.com/{slug}: {', '.join(untrusted)}"
        )
    return problems


def _check_plugin_version_sync(info: ProjectInfo) -> list[tuple[str, str, str]]:
    """Check that plugin.json version matches pyproject.toml version."""
    if not info.is_plugin:
        return []

    try:
        plugin_version = _read_plugin_field(info, "version")
    except ReleaseError as exc:
        return [(FAIL, "Plugin manifest is readable", str(exc))]
    if plugin_version is None:
        return []

    # Skip if no pyproject.toml (pure plugins)
    pyproject_path = info.root / "pyproject.toml"
    if not pyproject_path.exists():
        return []

    data = TextFile(pyproject_path).toml()

    project_raw = data.get("project")
    if not isinstance(project_raw, dict):
        return []

    project = cast("dict[str, object]", project_raw)
    pyproject_version = project.get("version")
    if not isinstance(pyproject_version, str):
        return []

    if plugin_version == pyproject_version:
        return [(PASS, "Plugin version matches pyproject.toml", f"v{plugin_version}")]

    return [
        (
            FAIL,
            "Plugin version matches pyproject.toml",
            f"plugin.json={plugin_version}, pyproject.toml={pyproject_version}",
        )
    ]


def _read_plugin_field(info: ProjectInfo, field: str) -> str | None:
    """Read a string field from plugin.json.

    None when no manifest declares the field — the callers turn that into a
    skipped check, since a plugin that omits a field is a different finding
    from one whose value is wrong. A manifest that cannot be read raises
    :class:`ReleaseError` instead of being skipped, so a broken file is never
    mistaken for a field it did not declare.
    """
    for pj_path in info.plugin_manifests:
        value = JsonFile(pj_path).load_object().get(field)
        if isinstance(value, str):
            return value
    return None


def _find_package_dir(info: ProjectInfo) -> Path | None:
    """Find the Python package directory (src layout)."""
    src_dir = info.root / "src"
    if not src_dir.is_dir():
        return None

    # Look for directories with __init__.py under src/
    for child in sorted(src_dir.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            return child

    return None


def _get_project_name(info: ProjectInfo) -> str:
    """Extract human-readable project name from metadata."""
    if info.pyproject is not None:
        project_raw = info.pyproject.get("project")
        if isinstance(project_raw, dict):
            project = cast("dict[str, object]", project_raw)
            name = project.get("name")
            if isinstance(name, str):
                return name

    return info.root.name


def _relpath(path: Path, root: Path) -> str:
    """Return path relative to root as a string."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
