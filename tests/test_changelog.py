"""Tests for the one CHANGELOG.md parser and the readers built on it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.changelog_parser import ChangelogDocument
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.timeouts import DEFAULT_RUN
from tests.harness.fault_ops import FaultInjectingOps

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


def _suggest(text: str, current: str = "1.2.3") -> str:
    return ChangelogDocument(text).suggest_next_version(current)


# --- suggest_next_version ---


def test_suggest_version_minor_bump() -> None:
    """Suggests minor bump when [Unreleased] has ### Added."""
    cl = "## [Unreleased]\n\n### Added\n\n- Feature\n\n## [1.2.3]\n"
    assert _suggest(cl) == "1.3.0"


def test_suggest_version_patch_bump() -> None:
    """Suggests patch bump when [Unreleased] has only ### Fixed."""
    cl = "## [Unreleased]\n\n### Fixed\n\n- Bug fix\n\n## [1.2.3]\n"
    assert _suggest(cl) == "1.2.4"


def test_suggest_version_ignores_the_next_release_after_an_empty_unreleased() -> None:
    """An empty [Unreleased] suggests no bump and ignores the next release's notes."""
    cl = (
        "# Changelog\n\n## [Unreleased]\n\n"
        "## [1.2.3] - 2026-01-01\n\n### Added\n\n- x\n"
    )
    assert _suggest(cl) == "1.2.3"


def test_suggest_version_major_bump() -> None:
    """Suggests major bump for breaking changes."""
    cl = "## [Unreleased]\n\n### Changed\n\n- BREAKING: removed old API\n\n## [1.2.3]\n"
    assert _suggest(cl) == "2.0.0"


def test_suggest_version_detects_breaking_change_in_crlf_changelog() -> None:
    """A CRLF changelog's breaking ### Changed entry still bumps the major."""
    cl = (
        "# Changelog\r\n\r\n## [Unreleased]\r\n\r\n### Changed\r\n\r\n"
        "- BREAKING: drop the old flag\r\n\r\n### Added\r\n\r\n- new flag\r\n"
    )
    assert _suggest(cl) == "2.0.0"


def test_suggest_version_empty_unreleased_at_eof_without_newline_suggests_no_bump() -> (
    None
):
    """A changelog ending in a bare ``## [Unreleased]`` has nothing to release."""
    assert _suggest("# Changelog\n\n## [Unreleased]") == "1.2.3"


def test_suggest_version_tolerates_trailing_whitespace_after_changed_heading() -> None:
    """``### Changed`` followed by spaces is still the Changed heading."""
    cl = "## [Unreleased]\n\n### Changed  \t\n\n- BREAKING: drop the old flag\n"
    assert _suggest(cl) == "2.0.0"


def test_suggest_version_breaking_in_fixed_not_major() -> None:
    """'breaking' in Fixed section does not trigger major bump."""
    cl = "## [Unreleased]\n\n### Fixed\n\n- Fixed breaking regression\n\n## [1.2.3]\n"
    assert _suggest(cl) == "1.2.4"


@pytest.mark.parametrize(
    "unreleased",
    [
        pytest.param("### Added\n\n### Fixed\n", id="headings-only"),
        pytest.param("<!-- nothing yet -->\n", id="comment-only"),
        pytest.param("<!--\nnothing\nyet\n-->\n", id="multi-line-comment-only"),
        pytest.param(
            "### Added\n\n<!-- entries go here -->\n\n### Fixed\n",
            id="headings-and-comment",
        ),
        pytest.param(
            "[Unreleased]: https://example.test/compare/v1.2.3...HEAD\n",
            id="link-definition-only",
        ),
    ],
)
def test_unreleased_without_entries_suggests_no_bump(unreleased: str) -> None:
    cl = f"## [Unreleased]\n\n{unreleased}\n## [1.2.3] - 2026-01-01\n\n- x\n"
    assert _suggest(cl) == "1.2.3"


def test_non_breaking_entry_is_not_a_breaking_change() -> None:
    """'Non-breaking' must never trigger a major bump."""
    cl = "## [Unreleased]\n\n### Changed\n\n- Non-breaking tweak\n\n## [1.2.3]\n"
    assert _suggest(cl) == "1.2.4"


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("- **Breaking:** `ingest` renamed", id="bold-colon"),
        pytest.param("- **BREAKING — module path changed**", id="bold-dash"),
        pytest.param("- **Breaking**: dropped the flag", id="bold-then-colon"),
        pytest.param("- BREAKING: removed old API", id="bullet-lead"),
        pytest.param("* Breaking change: new default", id="star-bullet-lead"),
    ],
)
def test_fleet_breaking_markers_bump_the_major(entry: str) -> None:
    cl = f"## [Unreleased]\n\n### Changed\n\n{entry}\n\n## [1.2.3]\n"
    assert _suggest(cl) == "2.0.0"


def test_breaking_changed_heading_bumps_the_major() -> None:
    cl = "## [Unreleased]\n\n### Changed (BREAKING)\n\n- new format\n\n## [1.2.3]\n"
    assert _suggest(cl) == "2.0.0"


def test_empty_changed_heading_does_not_swallow_the_next_subsection() -> None:
    """A bare ``### Changed`` owns nothing; the next block's text is not its."""
    cl = (
        "## [Unreleased]\n\n### Changed\n### Fixed\n\n"
        "- A breaking regression\n\n## [1.2.3]\n"
    )
    assert _suggest(cl) == "1.2.4"


def test_fenced_version_heading_does_not_end_the_section() -> None:
    """A ``## [`` line inside a code fence is content, not a section start."""
    cl = (
        "## [Unreleased]\n\n### Added\n\n"
        "```markdown\n## [9.9.9] - 2030-01-01\n```\n\n"
        "- real entry after the fence\n\n## [1.2.3]\n"
    )
    doc = ChangelogDocument(cl)
    unreleased = doc.section("Unreleased")
    assert unreleased is not None
    assert "real entry after the fence" in unreleased.notes
    assert doc.section("9.9.9") is None


def test_fenced_heading_alone_still_counts_as_an_entry() -> None:
    cl = "## [Unreleased]\n\n```\ncode\n```\n\n## [1.2.3]\n"
    assert _suggest(cl) == "1.2.4"


def test_tilde_fence_with_a_longer_opener_needs_a_matching_closer() -> None:
    cl = "## [Unreleased]\n\n~~~~\n## [9.9.9]\n~~~\n## [8.8.8]\n~~~~\n\n## [1.2.3]\n"
    doc = ChangelogDocument(cl)
    assert [doc.section(v) is not None for v in ("9.9.9", "8.8.8")] == [False, False]


def test_utf8_bom_before_the_unreleased_heading_is_accepted() -> None:
    cl = "\ufeff## [Unreleased]\n\n### Added\n\n- x\n\n## [1.2.3]\n"
    assert _suggest(cl) == "1.3.0"


# --- notes_for ---


def test_extract_version_notes() -> None:
    """Extracts notes for a specific version."""
    changelog = (
        "## [Unreleased]\n\n"
        "## [0.2.0] - 2026-03-01\n\n"
        "### Added\n\n- New feature\n\n"
        "## [0.1.0] - 2026-01-01\n\n"
        "### Added\n\n- Initial\n"
    )
    notes = ChangelogDocument(changelog).notes_for("0.2.0")
    assert "New feature" in notes
    assert "Initial" not in notes


def test_extract_version_notes_missing() -> None:
    """Returns default when version not found."""
    notes = ChangelogDocument("## [Unreleased]\n").notes_for("9.9.9")
    assert "v9.9.9" in notes


def test_notes_keep_a_fenced_version_heading() -> None:
    changelog = "## [0.2.0] - 2026-03-01\n\n```\n## [0.1.0]\n```\n\n- tail\n"
    notes = ChangelogDocument(changelog).notes_for("0.2.0")
    assert "## [0.1.0]" in notes
    assert "- tail" in notes


# --- stamped / is_stamped ---


def test_stamped_inserts_the_dated_heading_under_unreleased() -> None:
    cl = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- x\n"
    assert ChangelogDocument(cl).stamped("0.2.0", "2026-03-01") == (
        "# Changelog\n\n## [Unreleased]\n\n"
        "## [0.2.0] - 2026-03-01\n\n### Added\n\n- x\n"
    )


def test_stamped_ignores_an_unreleased_look_alike_inside_a_fence() -> None:
    cl = "```\n## [Unreleased]\n```\n\n## [Unreleased]\n\n- x\n"
    stamped = ChangelogDocument(cl).stamped("0.2.0", "2026-03-01")
    assert stamped.startswith("```\n## [Unreleased]\n```\n")
    assert stamped.endswith("## [Unreleased]\n\n## [0.2.0] - 2026-03-01\n\n- x\n")


def test_stamped_preserves_crlf_and_the_bom() -> None:
    cl = "\ufeff## [Unreleased]\r\n\r\n- x\r\n"
    stamped = ChangelogDocument(cl).stamped("0.2.0", "2026-03-01")
    assert stamped == (
        "\ufeff## [Unreleased]\r\n\r\n## [0.2.0] - 2026-03-01\r\n\r\n- x\r\n"
    )


def test_stamped_without_unreleased_keeps_the_bom() -> None:
    cl = "\ufeff# Changelog\n\n## [0.1.0] - 2026-01-01\n"
    assert ChangelogDocument(cl).stamped("0.2.0", "2026-03-01") == cl


def test_stamped_leaves_a_changelog_without_unreleased_unchanged() -> None:
    cl = "# Changelog\n\n## [0.1.0] - 2026-01-01\n"
    assert ChangelogDocument(cl).stamped("0.2.0", "2026-03-01") == cl


def test_is_stamped_requires_a_dated_heading() -> None:
    doc = ChangelogDocument("## [0.2.0] - 2026-03-01\n\n## [0.3.0]\n")
    assert [doc.is_stamped("0.2.0"), doc.is_stamped("0.3.0")] == [True, False]


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("  ", id="trailing-spaces"),
        pytest.param(" (yanked)", id="trailing-text"),
        pytest.param(" \t", id="trailing-tab"),
    ],
)
def test_a_dated_heading_with_trailing_text_is_still_stamped(suffix: str) -> None:
    """A published release must not read as unstamped over trailing text."""
    doc = ChangelogDocument(f"## [1.0.0] - 2026-01-01{suffix}\n\n- x\n")
    assert doc.is_stamped("1.0.0")


@pytest.mark.parametrize("heading", ["## [1.0.0] - 2026-1-1", "## [1.0.0] 2026-01-01"])
def test_a_malformed_date_is_not_stamped(heading: str) -> None:
    assert not ChangelogDocument(f"{heading}\n").is_stamped("1.0.0")


# --- CommonMark decides what is a fence, a comment, or a heading ---


_CANDIDATES = ("Unreleased", "1.0.0", "0.9.0", "fake", "x")


def _versions(text: str) -> list[str]:
    """The candidate versions that parse as sections, in candidate order."""
    doc = ChangelogDocument(text)
    return [v for v in _CANDIDATES if doc.section(v) is not None]


def test_commented_out_version_heading_is_not_a_section() -> None:
    cl = (
        "## [Unreleased]\n\n- x\n\n<!--\n## [0.9.0] - 2025-01-01\n-->\n\n"
        "## [1.2.3] - 2026-01-01\n\n- y\n"
    )
    doc = ChangelogDocument(cl)
    assert doc.section("0.9.0") is None
    assert doc.section("Unreleased") is not None
    assert doc.is_stamped("1.2.3")


def test_unclosed_fence_runs_to_the_end_and_hides_later_releases() -> None:
    """CommonMark: an unclosed fence is a code block to the end of the document.

    Later releases are hidden, so a reader that needs one (Phase 11) fails
    loudly instead of reading a phantom section.
    """
    cl = "## [Unreleased]\n\n```\n- x\n\n## [1.0.0] - 2026-01-01\n\n- y\n"
    doc = ChangelogDocument(cl)
    assert not doc.is_stamped("1.0.0")
    unreleased = doc.section("Unreleased")
    assert unreleased is not None
    assert unreleased.has_entries


def test_unclosed_comment_runs_to_the_end_and_hides_later_releases() -> None:
    """CommonMark: an HTML comment block ends at the first line holding ``-->``."""
    cl = "## [Unreleased]\n\n<!-- todo\n- x\n\n## [1.0.0] - 2026-01-01\n\n- y\n"
    doc = ChangelogDocument(cl)
    assert _versions(cl) == ["Unreleased"]
    unreleased = doc.section("Unreleased")
    assert unreleased is not None
    assert not unreleased.has_entries


def test_a_fence_inside_a_comment_does_not_open_a_fence() -> None:
    cl = "## [Unreleased]\n\n<!--\n```\n-->\n\n## [1.0.0] - 2026-01-01\n\n- y\n"
    assert ChangelogDocument(cl).is_stamped("1.0.0")


def test_a_stray_fence_does_not_pair_with_a_later_closer() -> None:
    """The fence opened at the stray line closes at the next bare fence line.

    The ``sh`` fence line carries an info string, so it cannot close; the last
    bare fence does. Everything between, including both releases, is code.
    """
    cl = (
        "## [Unreleased]\n- a\n```\n## [1.0.0] - 2026-01-01\n- b\n"
        "## [0.9.0] - 2025-01-01\n- c\n```sh\nls\n```\n"
    )
    assert _versions(cl) == ["Unreleased"]


def test_a_stray_arrow_in_prose_does_not_close_a_comment_early_or_late() -> None:
    """The comment block ends at the first line containing ``-->``, prose or not.

    Here that is the ``- use --> here`` line, so both releases above it are
    inside the comment and hidden.
    """
    cl = (
        "## [Unreleased]\n<!-- todo\n## [1.0.0] - 2026-01-01\n- b\n"
        "## [0.9.0] - 2025-01-01\n- use --> here\n"
    )
    assert _versions(cl) == ["Unreleased"]


def test_a_four_backtick_fence_is_not_closed_by_three_backticks() -> None:
    """A four-backtick fence never closes, so ``## [fake]`` is code, not a section."""
    cl = "## [Unreleased]\n- a\n````md\n## [fake]\n- x\n```\n- y\n"
    assert _versions(cl) == ["Unreleased"]


def test_a_fence_of_the_other_character_inside_a_fence_is_content() -> None:
    cl = "## [Unreleased]\n- a\n```\n~~~\n## [x]\n```\n## [1.0.0] - 2026-01-01\n"
    assert _versions(cl) == ["Unreleased", "1.0.0"]


def test_an_indented_fence_marker_is_a_code_block_not_a_fence() -> None:
    """Four spaces make an indented code block, so the marker opens nothing."""
    cl = "## [Unreleased]\n    ```\n- a\n## [1.0.0] - 2026-01-01\n- b\n    ```\n"
    assert _versions(cl) == ["Unreleased", "1.0.0"]


def test_an_empty_fence_pair_is_an_entry_and_ends_cleanly() -> None:
    cl = "## [Unreleased]\n```\n```\n## [1.0.0]\n"
    assert _versions(cl) == ["Unreleased", "1.0.0"]


def test_an_unclosed_inline_comment_opener_stays_text() -> None:
    """``<!--`` mid-paragraph is not an HTML block; the next heading ends it."""
    cl = "## [Unreleased]\n- a <!-- x\n## [1.0.0] - d\n- b\n"
    assert _versions(cl) == ["Unreleased", "1.0.0"]


def test_a_comment_after_the_version_does_not_change_the_version() -> None:
    doc = ChangelogDocument("## [Unreleased] <!-- x -->\n- a\n")
    unreleased = doc.section("Unreleased")
    assert unreleased is not None
    assert unreleased.has_entries


def test_an_empty_bullet_holding_only_a_comment_is_not_an_entry() -> None:
    cl = "## [Unreleased]\n\n- <!-- later -->\n"
    assert _suggest(cl) == "1.2.3"


def test_a_nested_breaking_bullet_bumps_the_major() -> None:
    cl = "## [Unreleased]\n\n### Changed\n\n- The CLI\n  - Breaking: no flag\n"
    assert _suggest(cl) == "2.0.0"


def test_a_setext_underline_does_not_make_a_version_section() -> None:
    """A setext heading cannot be stamped by a one-line insertion, so it is not one."""
    assert _versions("## [Unreleased]\n- a\n\n[1.0.0]\n---\n- b\n") == ["Unreleased"]


def test_line_breaks_commonmark_ignores_do_not_shift_the_sections() -> None:
    """U+2028 and form feed are not line ends, so the line maps must not move."""
    cl = "## [Unreleased]\n- a\u2028b\x0cc\n\n## [1.0.0] - 2026-01-01\n- d\n"
    doc = ChangelogDocument(cl)
    section = doc.section("1.0.0")
    assert section is not None
    assert section.notes == "- d"


def test_a_bare_carriage_return_is_a_line_end() -> None:
    cl = "## [Unreleased]\r- a\r\r## [1.0.0] - 2026-01-01\r- d\r"
    assert ChangelogDocument(cl).is_stamped("1.0.0")


# --- Changelog (file access and the preflight gate) ---


def _changelog(root: Path, text: str) -> Changelog:
    (root / "CHANGELOG.md").write_text(text, encoding="utf-8")
    ops = FaultInjectingOps(real_run=_unused_run, rules=[])
    return Changelog(root, ops=ops)


def _unused_run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = DEFAULT_RUN,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"reading a changelog runs no commands: {cmd!r}")


def test_require_unreleased_entries_accepts_real_entries(tmp_path: Path) -> None:
    changelog = _changelog(tmp_path, "## [Unreleased]\n\n### Fixed\n\n- x\n")

    changelog.require_unreleased_entries()


def test_require_unreleased_entries_accepts_a_bom(tmp_path: Path) -> None:
    _changelog(tmp_path, "\ufeff## [Unreleased]\n\n- x\n").require_unreleased_entries()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("## [Unreleased]\n\n### Added\n\n### Fixed\n", id="headings-only"),
        pytest.param("## [Unreleased]\n\n<!-- later -->\n", id="comment-only"),
        pytest.param("## [Unreleased]\n", id="bare-heading"),
    ],
)
def test_require_unreleased_entries_rejects_an_empty_section(
    tmp_path: Path, text: str
) -> None:
    with pytest.raises(ReleaseError, match=r"nothing to release"):
        _changelog(tmp_path, text).require_unreleased_entries()


def test_require_unreleased_entries_rejects_a_missing_section(tmp_path: Path) -> None:
    changelog = _changelog(tmp_path, "# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- x\n")

    with pytest.raises(ReleaseError, match=r"No \[Unreleased\] section in CHANGELOG"):
        changelog.require_unreleased_entries()


def test_require_unreleased_entries_ignores_a_fenced_unreleased(tmp_path: Path) -> None:
    text = "```\n## [Unreleased]\n\n- x\n```\n"
    with pytest.raises(ReleaseError, match=r"No \[Unreleased\] section"):
        _changelog(tmp_path, text).require_unreleased_entries()
