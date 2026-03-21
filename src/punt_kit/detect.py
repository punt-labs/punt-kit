"""Project type detection for punt init / punt audit."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path


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
    workflow_files: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    standards_refs: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    cli_commands: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    plugin_mcp_servers: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]

    @property
    def is_hybrid(self) -> bool:
        """True when the project has both a CLI binary and a plugin shell."""
        return self.is_plugin and len(self.cli_commands) > 0


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
        with open(package_json_path) as pj:
            package_json_data = json.load(pj)
        if language is None:
            language = "node"
            project_type = "package"
            standards_refs.append("node")

    # Check Go
    go_mod = root / "go.mod"
    if go_mod.exists() and language is None:
        language = "go"
        project_type = "package"

    # Check Swift
    swift_files = list(root.glob("**/*.swift"))
    xcodegen = root / "project.yml"
    if (swift_files or xcodegen.exists()) and language is None:
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

    # Extract CLI entry points
    cli_commands: list[str] = []
    # Python: pyproject.toml [project.scripts]
    if pyproject_data is not None:
        project_raw = pyproject_data.get("project")
        if isinstance(project_raw, dict):
            project_dict = cast("dict[str, object]", project_raw)
            scripts = project_dict.get("scripts")
            if isinstance(scripts, dict):
                cli_commands = list(cast("dict[str, object]", scripts).keys())
    # Go: cmd/<name>/ directories → each subdirectory is a CLI command
    if language == "go" and not cli_commands:
        cmd_dir = root / "cmd"
        if cmd_dir.is_dir():
            cli_commands = [
                d.name
                for d in sorted(cmd_dir.iterdir())
                if d.is_dir() and (d / "main.go").is_file()
            ]

    # Extract MCP server names from plugin.json
    plugin_mcp_servers: list[str] = []
    for pj_path in (plugin_json, plugin_json_alt):
        if pj_path.exists():
            try:
                pj_data = json.loads(pj_path.read_text(encoding="utf-8"))
                servers = pj_data.get("mcpServers")
                if isinstance(servers, dict):
                    plugin_mcp_servers = list(cast("dict[str, object]", servers).keys())
            except (json.JSONDecodeError, OSError):
                pass
            break

    # All projects get these standard refs
    standards_refs.append("github")
    standards_refs.append("workflow")
    if cli_commands:
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
        cli_commands=cli_commands,
        plugin_mcp_servers=plugin_mcp_servers,
    )


_PYTHON_MCP_RE = re.compile(r"^(?:from\s+fastmcp|import\s+fastmcp)", re.MULTILINE)
_NODE_MCP_RE = re.compile(r"""^import\s+\{[^}]*McpServer""", re.MULTILINE)


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
