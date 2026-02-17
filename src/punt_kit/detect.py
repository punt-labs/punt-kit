"""Project type detection for punt init / punt audit."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


@dataclass(frozen=True)
class ProjectInfo:
    """Detected project characteristics."""

    root: Path
    language: str | None = None  # "python", "node", "swift", or None
    project_type: str | None = None  # "package", "plugin", "mcp-server", "docs", etc.
    has_ci: bool = False
    has_claude_md: bool = False
    has_beads: bool = False
    is_mcp_server: bool = False
    is_plugin: bool = False
    pyproject: dict[str, object] | None = None
    package_json: dict[str, object] | None = None
    workflow_files: list[str] = field(default_factory=list)
    standards_refs: list[str] = field(default_factory=list)


def detect(root: Path) -> ProjectInfo:
    """Scan a directory and return detected project info."""
    root = root.resolve()

    language: str | None = None
    project_type: str | None = None
    is_mcp_server = False
    is_plugin = False
    pyproject_data: dict[str, object] | None = None
    package_json_data: dict[str, object] | None = None
    standards_refs: list[str] = []

    # Check pyproject.toml
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
        if "project" in pyproject_data:
            language = "python"
            project_type = "package"
            standards_refs.append("python")

    # Check package.json
    package_json_path = root / "package.json"
    if package_json_path.exists():
        with open(package_json_path) as f:
            package_json_data = json.load(f)
        if language is None:
            language = "node"
            project_type = "package"
            standards_refs.append("node")

    # Check Swift
    swift_files = list(root.glob("**/*.swift"))
    xcodegen = root / "project.yml"
    if swift_files or xcodegen.exists():
        if language is None:
            language = "swift"
            project_type = "app"

    # Check Claude Code plugin
    plugin_json = root / ".claude-plugin" / "plugin.json"
    plugin_json_alt = root / "plugin.json"
    if plugin_json.exists() or plugin_json_alt.exists():
        is_plugin = True
        if project_type is None:
            project_type = "plugin"
        standards_refs.append("plugins")

    # Check MCP server
    if _has_mcp_server(root, language):
        is_mcp_server = True
        if project_type is None:
            project_type = "mcp-server"

    # Check CI
    workflows_dir = root / ".github" / "workflows"
    workflow_files: list[str] = []
    has_ci = False
    if workflows_dir.is_dir():
        workflow_files = [f.name for f in workflows_dir.glob("*.yml")]
        workflow_files.extend(f.name for f in workflows_dir.glob("*.yaml"))
        has_ci = len(workflow_files) > 0

    # Check CLAUDE.md
    has_claude_md = (root / "CLAUDE.md").exists()

    # Check beads
    has_beads = (root / ".beads").is_dir()

    # If no language detected but has markdown files, it's a docs project
    if language is None and project_type is None:
        md_files = list(root.glob("*.md"))
        if md_files:
            project_type = "docs"

    # All projects get these standard refs
    standards_refs.append("github")
    standards_refs.append("workflow")
    if language == "python":
        standards_refs.append("cli")

    return ProjectInfo(
        root=root,
        language=language,
        project_type=project_type,
        has_ci=has_ci,
        has_claude_md=has_claude_md,
        has_beads=has_beads,
        is_mcp_server=is_mcp_server,
        is_plugin=is_plugin,
        pyproject=pyproject_data,
        package_json=package_json_data,
        workflow_files=workflow_files,
        standards_refs=standards_refs,
    )


_PYTHON_MCP_RE = __import__("re").compile(r"^(?:from\s+fastmcp|import\s+fastmcp)", __import__("re").MULTILINE)
_NODE_MCP_RE = __import__("re").compile(r"""^import\s+\{[^}]*McpServer""", __import__("re").MULTILINE)


def _has_mcp_server(root: Path, language: str | None) -> bool:
    """Check if the project contains an MCP server.

    Uses regexes anchored to line starts to match actual import statements,
    avoiding false positives from string literals in detection code.
    """
    if language == "python":
        for py_file in root.rglob("*.py"):
            try:
                content = py_file.read_text(errors="ignore")
                if _PYTHON_MCP_RE.search(content):
                    return True
            except OSError:
                continue
    if language == "node":
        for js_file in (*root.rglob("*.mjs"), *root.rglob("*.js")):
            try:
                content = js_file.read_text(errors="ignore")
                if _NODE_MCP_RE.search(content):
                    return True
            except OSError:
                continue
    return False
