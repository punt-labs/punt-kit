"""Legacy CLAUDE.md marker migration through punt init."""

import shutil
from pathlib import Path

import pytest

from punt_kit.init import run_init
from tests.helpers import no_bd


@pytest.fixture(autouse=True)
def _without_bd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep init from attempting to initialize the host's issue tracker."""
    monkeypatch.setattr(shutil, "which", no_bd)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", ["", "\ufeff"])
@pytest.mark.parametrize("references", ["", "## Standards References\nExisting\n"])
def test_init_strips_markers(
    tmp_path: Path, eol: str, bom: str, references: str
) -> None:
    """Strip multiple blocks, preserving imports, prose and file conventions."""
    before = "# My instructions\n@.punt-labs/biff/CLAUDE.md\n" + references
    after = "User-owned prose.\n@.punt-labs/punt/CLAUDE.md\n"
    blocks = (
        "<!-- punt:begin standards -->\n"
        "## Standards References\nObsolete\n<!-- punt:end standards -->\n"
        "<!-- punt:begin tools -->\nObsolete tools\n<!-- punt:end tools -->\n"
    )
    host = tmp_path / "CLAUDE.md"
    host.write_bytes((bom + before + blocks + after).replace("\n", eol).encode())
    makefile = tmp_path / "Makefile"
    makefile_content = b"# punt:begin help\nhelp:\n\t@echo help\n# punt:end help\n"
    makefile.write_bytes(makefile_content)

    run_init(str(tmp_path))

    migrated = host.read_bytes()
    expected = (bom + before + after).replace("\n", eol).encode()
    if references:
        assert migrated == expected
    else:
        assert migrated.startswith(expected.rstrip() + (eol * 2).encode())
        assert b"## Standards References" in migrated
    assert b"punt:begin" not in migrated
    assert b"Obsolete" not in migrated
    assert makefile.read_bytes() == makefile_content
    run_init(str(tmp_path))
    assert host.read_bytes() == migrated
    assert makefile.read_bytes() == makefile_content


@pytest.mark.parametrize(
    "content",
    [
        "<!-- punt:begin broken -->\nKeep me\n",
        "<!-- punt:begin a -->\nKeep me\n<!-- punt:end b -->\n",
        "<!-- punt:begin a -->\n<!-- punt:begin b -->\n<!-- punt:end a -->\n",
        "<!-- punt:end orphan -->\nKeep me\n",
        "<!-- punt:begin ok -->\nOld\n<!-- punt:end ok -->\n"
        "<!-- punt:begin broken -->\nKeep me",
    ],
)
def test_init_preserves_malformed_markers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    """An unsafe migration preserves original content while adding references."""
    host = tmp_path / "CLAUDE.md"
    original = ("\ufeff# User prose\r\n" + content).encode()
    host.write_bytes(original)

    run_init(str(tmp_path))

    migrated = host.read_bytes()
    assert migrated.startswith(original.rstrip() + b"\r\n\r\n")
    assert b"## Standards References" in migrated
    assert "Warning: Skipping CLAUDE.md marker migration:" in capsys.readouterr().out
    run_init(str(tmp_path))
    assert host.read_bytes() == migrated


@pytest.mark.parametrize(
    "mention",
    [
        "Describe punt:begin and punt:end here.",
        "Example: <!-- punt:begin example --> and <!-- punt:end example -->",
        "<!-- punt:begin -->",
        "    <!-- punt:begin example -->",
        "<!-- punt:end example --> trailing prose",
    ],
)
@pytest.mark.parametrize("fenced", [False, True])
def test_init_preserves_marker_mentions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mention: str, *, fenced: bool
) -> None:
    """Prose and code mentions are ordinary content, not malformed markers."""
    content = f"```text\n{mention}\n```\n" if fenced else mention + "\n"
    host = tmp_path / "CLAUDE.md"
    host.write_text(content)

    run_init(str(tmp_path))

    migrated = host.read_bytes()
    assert migrated.startswith(content.rstrip().encode() + b"\n\n")
    assert b"## Standards References" in migrated
    assert "Warning:" not in capsys.readouterr().out
    run_init(str(tmp_path))
    assert host.read_bytes() == migrated


@pytest.mark.parametrize("content", ["", "User prose", "@.punt-labs/biff/CLAUDE.md\n"])
def test_init_without_markers(tmp_path: Path, content: str) -> None:
    """Empty and marker-free files still receive references idempotently."""
    host = tmp_path / "CLAUDE.md"
    host.write_text(content)

    run_init(str(tmp_path))
    migrated = host.read_bytes()
    assert migrated.startswith(content.rstrip().encode())
    assert b"## Standards References" in migrated
    run_init(str(tmp_path))
    assert host.read_bytes() == migrated


@pytest.mark.parametrize("fence", ["```", "~~~", "````", "   ~~~"])
@pytest.mark.parametrize("closed", [False, True])
def test_init_preserves_fenced_marker_examples(
    tmp_path: Path, fence: str, *, closed: bool
) -> None:
    """Whole-line markers in code examples are never managed sections."""
    example = (
        f"{fence}markdown\n<!-- punt:begin example -->\n"
        "Keep this example.\n<!-- punt:end example -->\n"
    )
    if closed:
        example += fence + "\n"
    host = tmp_path / "CLAUDE.md"
    host.write_text(example)

    run_init(str(tmp_path))

    assert host.read_text().startswith(example)
    assert "Keep this example." in host.read_text()
