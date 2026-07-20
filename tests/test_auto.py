"""Tests for punt auto — marker-based section management."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from punt_kit.auto import (
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
        assert len(segments) == 0

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
    def test_renders_with_markers(self) -> None:
        section = render_section(
            "help",
            "makefile/help.mk.j2",
            {},
            "makefile",
        )
        assert section.startswith("# punt:begin help")
        assert section.endswith("# punt:end help")
        assert ".PHONY: help" in section

    def test_standard_targets_template(self) -> None:
        section = render_section(
            "standard-targets",
            "makefile/python.mk.j2",
            {},
            "makefile",
        )
        assert "# punt:begin standard-targets" in section
        assert "# punt:end standard-targets" in section
        assert "uv run pytest" in section

    def test_missing_template_exits(self) -> None:
        with pytest.raises(SystemExit, match="1"):
            render_section("gone", "makefile/gone.mk.j2", {}, "makefile")


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
    def test_auto_makefile_creates_managed_sections(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        run_auto(str(tmp_path), target="makefile")

        content = (tmp_path / "Makefile").read_text()
        assert "# punt:begin standard-targets" in content
        assert "# punt:end standard-targets" in content
        assert "# punt:begin help" in content
        assert "# punt:end help" in content
        assert "uv run pytest" in content

    def test_auto_makefile_idempotent(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        run_auto(str(tmp_path), target="makefile")
        first = (tmp_path / "Makefile").read_text()

        run_auto(str(tmp_path), target="makefile")
        second = (tmp_path / "Makefile").read_text()

        assert first == second

    def test_auto_makefile_updates_managed_preserves_local(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "Makefile").write_text(
            "# Local preamble\n\n"
            "# punt:begin standard-targets\n"
            "old targets\n"
            "# punt:end standard-targets\n\n"
            "custom:\n\techo custom\n"
        )

        run_auto(str(tmp_path), target="makefile")

        content = (tmp_path / "Makefile").read_text()
        assert "# Local preamble" in content
        assert "echo custom" in content
        assert "old targets" not in content

    def test_auto_makefile_dry_run_no_changes(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        run_auto(str(tmp_path), target="makefile", dry_run=True)

        assert not (tmp_path / "Makefile").exists()

    def test_auto_makefile_skips_non_python(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Test\n")

        changed = run_auto(str(tmp_path), target="makefile")

        assert changed == []
        assert not (tmp_path / "Makefile").exists()

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

    def test_auto_claude_target_removed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Regression: "punt auto claude" fails listing the remaining targets."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')

        with pytest.raises(SystemExit, match="1"):
            run_auto(str(tmp_path), target="claude")

        out = capsys.readouterr().out
        assert "unknown target 'claude'" in out
        assert "makefile" in out
        assert "settings" in out
