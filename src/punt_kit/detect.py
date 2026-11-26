"""Project type detection for punt repo init / punt repo audit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.text_file import TextFile

# Prefer the subdirectory that the marketplace can install independently;
# sibling repositories can also declare their plugin at the root.
PLUGIN_MANIFEST_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("plugin", ".claude-plugin", "plugin.json"),
    (".claude-plugin", "plugin.json"),
    ("plugin.json",),
)


def plugin_manifests(root: Path) -> list[Path]:
    """Every plugin manifest present under ``root``, in precedence order.

    Normally at most one exists. More than one means a half-finished move to
    the ``plugin/`` layout left a stale manifest behind, and callers that only
    read the first would silently ignore the other — so the full list is
    returned and ``punt repo audit`` reports the ambiguity.
    """
    return [
        candidate
        for parts in PLUGIN_MANIFEST_CANDIDATES
        if (candidate := root.joinpath(*parts)).is_file()
    ]


@dataclass(frozen=True)
class ProjectInfo:
    """Detected project characteristics."""

    root: Path
    language: str | None = None  # "python", "node", "go", "swift", or None
    project_type: str | None = None  # "package", "plugin", "mcp-server", "docs", etc.
    has_ci: bool = False
    has_claude_md: bool = False
    is_mcp_server: bool = False
    is_plugin: bool = False
    pyproject: dict[str, object] | None = None
    package_json: dict[str, object] | None = None
    workflow_files: list[str] = field(default_factory=list[str])
    standards_refs: list[str] = field(default_factory=list[str])
    cli_commands: list[str] = field(default_factory=list[str])
    plugin_mcp_servers: list[str] = field(default_factory=list[str])
    # Every manifest found, in precedence order. Empty for a non-plugin
    # project — absence is the contract there, not a failed lookup.
    plugin_manifests: list[Path] = field(default_factory=list[Path])

    @property
    def is_hybrid(self) -> bool:
        """True when the project has both a CLI binary and a plugin shell."""
        return self.is_plugin and len(self.cli_commands) > 0

    @property
    def plugin_manifest(self) -> Path:
        """The manifest that governs the plugin.

        Guard with ``is_plugin``: a caller that reaches for the manifest of a
        non-plugin project has a bug, and a ``None`` here would push that bug
        downstream into a path join.

        Raises:
            ValueError: The project has no plugin manifest.
        """
        if not self.plugin_manifests:
            raise ValueError(f"no plugin manifest under {self.root}")
        return self.plugin_manifests[0]

    @property
    def plugin_root(self) -> Path:
        """The directory Claude Code treats as ``CLAUDE_PLUGIN_ROOT``.

        This is the manifest's grandparent under a ``.claude-plugin/`` layout
        and its parent under the bare ``plugin.json`` shape; it is not the repo
        root under the ``plugin/`` layout.

        Raises:
            ValueError: The project has no plugin manifest.
        """
        manifest = self.plugin_manifest
        if manifest.parent.name == ".claude-plugin":
            return manifest.parent.parent
        return manifest.parent


def detect(root: Path) -> ProjectInfo:
    """Scan a directory and return detected project info.

    Detection built on a file it could not read would report a project it
    never saw, so an unreadable input raises instead.

    Raises:
        ReleaseError: ``pyproject.toml`` is not readable TOML, or
            ``package.json`` or the highest-precedence plugin manifest is not a
            readable JSON object.
    """
    root = root.resolve()

    language: str | None = None
    project_type: str | None = None
    is_mcp_server = False
    is_plugin = False
    pyproject_data: dict[str, object] | None = None
    package_json_data: dict[str, object] | None = None
    standards_refs: list[str] = []

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        pyproject_data = TextFile(pyproject_path).toml()
        if "project" in pyproject_data:
            language = "python"
            project_type = "package"
            standards_refs.append("python")

    package_json_path = root / "package.json"
    if package_json_path.exists():
        package_json_data = JsonFile(package_json_path).load_object()
        if language is None:
            language = "node"
            project_type = "package"
            standards_refs.append("node")

    go_mod = root / "go.mod"
    if go_mod.exists() and language is None:
        language = "go"
        project_type = "package"
        standards_refs.append("go")

    swift_files = list(root.glob("**/*.swift"))
    xcodegen = root / "project.yml"
    if (swift_files or xcodegen.exists()) and language is None:
        language = "swift"
        project_type = "app"

    manifests = plugin_manifests(root)
    if manifests:
        is_plugin = True
        if project_type is None:
            project_type = "plugin"
        standards_refs.append("plugins")

    if _has_mcp_server(root, language):
        is_mcp_server = True
        if project_type is None:
            project_type = "mcp-server"

    workflows_dir = root / ".github" / "workflows"
    workflow_files: list[str] = []
    has_ci = False
    if workflows_dir.is_dir():
        workflow_files = [f.name for f in workflows_dir.glob("*.yml")]
        workflow_files.extend(f.name for f in workflows_dir.glob("*.yaml"))
        has_ci = len(workflow_files) > 0

    has_claude_md = (root / "CLAUDE.md").exists()

    if language is None and project_type is None:
        md_files = list(root.glob("*.md"))
        if md_files:
            project_type = "docs"

    cli_commands: list[str] = []
    # Python CLIs are the keys of the project scripts table.
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

    plugin_mcp_servers: list[str] = []
    if manifests:
        servers = JsonFile(manifests[0]).load_object().get("mcpServers")
        if isinstance(servers, dict):
            plugin_mcp_servers = list(cast("dict[str, object]", servers).keys())

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
        is_mcp_server=is_mcp_server,
        is_plugin=is_plugin,
        pyproject=pyproject_data,
        package_json=package_json_data,
        workflow_files=workflow_files,
        standards_refs=standards_refs,
        cli_commands=cli_commands,
        plugin_mcp_servers=plugin_mcp_servers,
        plugin_manifests=manifests,
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
