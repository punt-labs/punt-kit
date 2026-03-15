"""Tests for punt auto — marker-based section management."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from punt_kit.auto import (
    build_context,
    merge_file,
    merge_json_permissions,
    parse_segments,
    render_section,
    run_auto,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# parse_segments
# ---------------------------------------------------------------------------


class TestParseSegments:
    def test_no_markers(self) -> None:
        content = "# Hello\n\nSome content."
        segments = parse_segments(content, "markdown")
        assert len(segments) == 1
        assert segments[0] == (None, "# Hello\n\nSome content.")

    def test_single_managed_section(self) -> None:
        content = (
            "# Header\n"
            "<!-- punt:begin foo -->\n"
            "managed content\n"
            "<!-- punt:end foo -->\n"
            "# Footer"
        )
        segments = parse_segments(content, "markdown")
        assert len(segments) == 3
        assert segments[0] == (None, "# Header")
        assert segments[1] == (
            "foo",
            "<!-- punt:begin foo -->\nmanaged content\n<!-- punt:end foo -->",
        )
        assert segments[2] == (None, "# Footer")

    def test_multiple_managed_sections(self) -> None:
        content = (
            "local1\n"
            "<!-- punt:begin a -->\n"
            "a content\n"
            "<!-- punt:end a -->\n"
            "local2\n"
            "<!-- punt:begin b -->\n"
            "b content\n"
            "<!-- punt:end b -->\n"
            "local3"
        )
        segments = parse_segments(content, "markdown")
        assert len(segments) == 5
        assert segments[0][0] is None
        assert segments[1][0] == "a"
        assert segments[2][0] is None
        assert segments[3][0] == "b"
        assert segments[4][0] is None

    def test_makefile_markers(self) -> None:
        content = (
            "# local\n"
            "# punt:begin targets\n"
            ".PHONY: check\n"
            "# punt:end targets\n"
            "# more local"
        )
        segments = parse_segments(content, "makefile")
        assert len(segments) == 3
        assert segments[1][0] == "targets"

    def test_unclosed_marker_raises(self) -> None:
        content = "before\n<!-- punt:begin broken -->\nno end marker"
        with pytest.raises(SystemExit):
            parse_segments(content, "markdown")

    def test_empty_content(self) -> None:
        segments = parse_segments("", "markdown")
        assert len(segments) == 1
        assert segments[0] == (None, "")

    def test_adjacent_sections(self) -> None:
        content = (
            "<!-- punt:begin a -->\n"
            "a\n"
            "<!-- punt:end a -->\n"
            "<!-- punt:begin b -->\n"
            "b\n"
            "<!-- punt:end b -->"
        )
        segments = parse_segments(content, "markdown")
        # Adjacent sections: a, (empty local), b — or just a, b if no gap
        managed = [s for s in segments if s[0] is not None]
        assert len(managed) == 2
        assert managed[0][0] == "a"
        assert managed[1][0] == "b"


# ---------------------------------------------------------------------------
# merge_file
# ---------------------------------------------------------------------------


class TestMergeFile:
    def test_replace_existing_section(self) -> None:
        original = (
            "# Header\n"
            "<!-- punt:begin foo -->\n"
            "old content\n"
            "<!-- punt:end foo -->\n"
            "# Footer"
        )
        rendered = {
            "foo": "<!-- punt:begin foo -->\nnew content\n<!-- punt:end foo -->"
        }
        result = merge_file(original, rendered, "markdown")
        assert "new content" in result
        assert "old content" not in result
        assert "# Header" in result
        assert "# Footer" in result

    def test_append_new_section(self) -> None:
        original = (
            "# Header\n<!-- punt:begin foo -->\nfoo\n<!-- punt:end foo -->\n# Footer"
        )
        rendered = {
            "foo": "<!-- punt:begin foo -->\nfoo\n<!-- punt:end foo -->",
            "bar": "<!-- punt:begin bar -->\nbar\n<!-- punt:end bar -->",
        }
        result = merge_file(original, rendered, "markdown")
        assert "bar" in result
        # bar should appear after foo (after last managed section)
        foo_pos = result.index("<!-- punt:end foo -->")
        bar_pos = result.index("<!-- punt:begin bar -->")
        assert bar_pos > foo_pos

    def test_append_to_file_with_no_managed_sections(self) -> None:
        original = "# My Project\n\nSome content."
        rendered = {
            "foo": "<!-- punt:begin foo -->\nfoo content\n<!-- punt:end foo -->"
        }
        result = merge_file(original, rendered, "markdown")
        assert "# My Project" in result
        assert "foo content" in result

    def test_idempotent(self) -> None:
        original = (
            "# Header\n"
            "<!-- punt:begin foo -->\n"
            "content\n"
            "<!-- punt:end foo -->\n"
            "# Footer"
        )
        rendered = {"foo": "<!-- punt:begin foo -->\ncontent\n<!-- punt:end foo -->"}
        result = merge_file(original, rendered, "markdown")
        assert result == original

    def test_preserves_local_content(self) -> None:
        original = (
            "# My custom header\n"
            "\n"
            "## Project-specific section\n"
            "\n"
            "Important local content.\n"
            "\n"
            "<!-- punt:begin gates -->\n"
            "old gates\n"
            "<!-- punt:end gates -->\n"
            "\n"
            "## More local stuff\n"
            "\n"
            "Don't touch this."
        )
        rendered = {
            "gates": "<!-- punt:begin gates -->\nnew gates\n<!-- punt:end gates -->"
        }
        result = merge_file(original, rendered, "markdown")
        assert "My custom header" in result
        assert "Project-specific section" in result
        assert "Important local content." in result
        assert "More local stuff" in result
        assert "Don't touch this." in result
        assert "new gates" in result
        assert "old gates" not in result

    def test_empty_original(self) -> None:
        rendered = {"foo": "<!-- punt:begin foo -->\ncontent\n<!-- punt:end foo -->"}
        result = merge_file("", rendered, "markdown")
        assert "content" in result
        assert not result.startswith("\n")


# ---------------------------------------------------------------------------
# render_section
# ---------------------------------------------------------------------------


class TestRenderSection:
    def test_renders_with_markers(self, tmp_path: Path) -> None:
        # We need actual template files for render_section, so test via run_auto
        # This is a structural test — the markers wrap the content
        section = render_section(
            "quality-gates",
            "claude/quality-gates.md.j2",
            {"quality_gates_command": "make check", "has_makefile": True},
            "markdown",
        )
        assert section.startswith("<!-- punt:begin quality-gates -->")
        assert section.endswith("<!-- punt:end quality-gates -->")
        assert "make check" in section

    def test_static_template(self) -> None:
        section = render_section(
            "no-preexisting",
            "claude/no-preexisting.md.j2",
            {},
            "markdown",
        )
        assert "pre-existing" in section.lower()
        assert "<!-- punt:begin no-preexisting -->" in section


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_python_project_with_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "Makefile").write_text("check:\n\techo ok\n")

        from punt_kit.detect import detect

        info = detect(tmp_path)
        ctx = build_context(info)

        assert ctx["language"] == "python"
        assert ctx["has_makefile"] is True
        assert ctx["quality_gates_command"] == "make check"

    def test_python_project_without_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        from punt_kit.detect import detect

        info = detect(tmp_path)
        ctx = build_context(info)

        assert ctx["has_makefile"] is False
        assert "uv run" in str(ctx["quality_gates_command"])

    def test_detects_prfaq_and_design(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Test\n")
        (tmp_path / "prfaq.tex").write_text("\\documentclass{article}\n")
        (tmp_path / "DESIGN.md").write_text("# Design\n")

        from punt_kit.detect import detect

        info = detect(tmp_path)
        ctx = build_context(info)

        assert ctx["has_prfaq"] is True
        assert ctx["has_design_md"] is True


# ---------------------------------------------------------------------------
# merge_json_permissions
# ---------------------------------------------------------------------------


class TestMergeJsonPermissions:
    def test_adds_missing_permissions(self, tmp_path: Path) -> None:
        from punt_kit.detect import detect

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        info = detect(tmp_path)

        existing: dict[str, object] = {}
        merged, changed = merge_json_permissions(existing, info)

        assert changed is True
        perms = merged["permissions"]
        assert isinstance(perms, dict)
        allow = cast("list[str]", perms["allow"])
        assert "Bash(git:*)" in allow

    def test_preserves_existing(self, tmp_path: Path) -> None:
        from punt_kit.detect import detect

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        info = detect(tmp_path)

        existing: dict[str, object] = {
            "permissions": {"allow": ["Bash(custom:*)"]},
            "env": {"KEY": "val"},
        }
        merged, _ = merge_json_permissions(existing, info)

        perms = merged["permissions"]
        assert isinstance(perms, dict)
        allow = cast("list[str]", perms["allow"])
        assert "Bash(custom:*)" in allow
        assert merged.get("env") == {"KEY": "val"}

    def test_idempotent(self, tmp_path: Path) -> None:
        from punt_kit.detect import detect

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        info = detect(tmp_path)

        existing: dict[str, object] = {}
        merged1, _ = merge_json_permissions(existing, info)
        _, changed2 = merge_json_permissions(merged1, info)

        assert changed2 is False

    def test_no_cross_project_paths(self, tmp_path: Path) -> None:
        """Verify ../** paths are not included (punt-kit-fsw fix)."""
        from punt_kit.detect import detect

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        info = detect(tmp_path)

        existing: dict[str, object] = {}
        merged, _ = merge_json_permissions(existing, info)

        perms = merged["permissions"]
        assert isinstance(perms, dict)
        allow_strs = cast("list[str]", perms["allow"])
        assert "Read(../**)" not in allow_strs
        assert "Edit(../**)" not in allow_strs
        assert "Write(../**)" not in allow_strs


# ---------------------------------------------------------------------------
# Integration: run_auto
# ---------------------------------------------------------------------------


class TestRunAuto:
    def test_auto_claude_creates_managed_sections(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nCustom content.\n")

        run_auto(str(tmp_path), target="claude")

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "# My Project" in content
        assert "Custom content." in content
        assert "<!-- punt:begin no-preexisting -->" in content
        assert "<!-- punt:end no-preexisting -->" in content
        assert "<!-- punt:begin quality-gates -->" in content
        assert "<!-- punt:begin standards-references -->" in content

    def test_auto_claude_idempotent(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "CLAUDE.md").write_text("# My Project\n")

        run_auto(str(tmp_path), target="claude")
        first = (tmp_path / "CLAUDE.md").read_text()

        run_auto(str(tmp_path), target="claude")
        second = (tmp_path / "CLAUDE.md").read_text()

        assert first == second

    def test_auto_claude_updates_managed_preserves_local(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "CLAUDE.md").write_text(
            "# My Project\n\n"
            "<!-- punt:begin quality-gates -->\n"
            "## Quality Gates\n\n"
            "old command\n"
            "<!-- punt:end quality-gates -->\n\n"
            "## My Local Section\n\n"
            "Don't touch this.\n"
        )

        run_auto(str(tmp_path), target="claude")

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "My Local Section" in content
        assert "Don't touch this." in content
        assert "old command" not in content

    def test_auto_claude_dry_run_no_changes(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "CLAUDE.md").write_text("# My Project\n")

        run_auto(str(tmp_path), target="claude", dry_run=True)

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "<!-- punt:begin" not in content

    def test_auto_settings(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        run_auto(str(tmp_path), target="settings")

        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "Bash(git:*)" in data["permissions"]["allow"]

    def test_auto_invalid_target(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Test\n")

        with pytest.raises(SystemExit, match="1"):
            run_auto(str(tmp_path), target="bogus")

    def test_auto_creates_claude_md_if_missing(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        run_auto(str(tmp_path), target="claude")

        assert (tmp_path / "CLAUDE.md").exists()
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "<!-- punt:begin" in content

    def test_auto_claude_with_prfaq(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "prfaq.tex").write_text("\\documentclass{article}\n")
        (tmp_path / "CLAUDE.md").write_text("# Test\n")

        run_auto(str(tmp_path), target="claude")

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "prfaq.tex" in content

    def test_auto_claude_without_prfaq(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "CLAUDE.md").write_text("# Test\n")

        run_auto(str(tmp_path), target="claude")

        content = (tmp_path / "CLAUDE.md").read_text()
        # prfaq line should not appear in pre-pr checklist
        assert "prfaq.tex" not in content
