"""Legacy CLAUDE.md marker migration through punt init."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from punt_kit.claude_md import ClaudeMdImport
from punt_kit.claude_markers import ClaudeMarkers
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


def test_migration_serializes_with_import_writers(tmp_path: Path) -> None:
    """A migration waits for the shared lock, then reads the latest content."""
    host = tmp_path / "CLAUDE.md"
    host.write_text("User prose.\n")
    script = (
        "import sys; from pathlib import Path; "
        "from punt_kit.claude_markers import ClaudeMarkers; "
        "print('ready', flush=True); "
        "ClaudeMarkers(Path(sys.argv[1])).update('## Standards References')"
    )
    with ClaudeMdImport.locked(host):
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(host)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdout is not None
            assert process.stdout.readline().strip() == "ready"
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=0.2)
            host.write_text("User prose.\n@.punt-labs/punt/CLAUDE.md\n")
        except BaseException:
            process.kill()
            process.communicate()
            raise
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, (stdout, stderr)
    content = host.read_text()
    assert "@.punt-labs/punt/CLAUDE.md\n" in content
    assert "## Standards References" in content


def test_migration_replaces_atomically(tmp_path: Path) -> None:
    """Atomic replacement retains a symlink, target mode, BOM and line endings."""
    target = tmp_path / "instructions.md"
    target.write_bytes(b"\xef\xbb\xbfUser prose.\r\n")
    target.chmod(0o640)
    inode = target.stat().st_ino
    host = tmp_path / "CLAUDE.md"
    host.symlink_to(target.name)

    ClaudeMarkers(host).update("## Standards References")

    assert host.is_symlink()
    assert target.stat().st_ino != inode
    assert target.stat().st_mode & 0o777 == 0o640
    assert target.read_bytes() == (
        b"\xef\xbb\xbfUser prose.\r\n\r\n## Standards References\r\n"
    )


def test_migration_failed_replace_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed atomic rename leaves the original intact with no temporary file."""
    host = tmp_path / "CLAUDE.md"
    original = b"User prose.\n"
    host.write_bytes(original)

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        ClaudeMarkers(host).update("## Standards References")

    assert host.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "example",
    [
        "Mention ## Standards References in prose.\n",
        "## Standards References extra words\n",
        "### Standards References\n",
        "    ## Standards References\n",
        "```markdown\n## Standards References\n```\n",
        "~~~markdown\n## Standards References\n~~~\n",
    ],
)
def test_reference_examples_do_not_suppress_references(
    tmp_path: Path, example: str
) -> None:
    """Only a real, unfenced heading prevents appending references."""
    host = tmp_path / "CLAUDE.md"
    host.write_text(example)

    run_init(str(tmp_path))

    migrated = host.read_text()
    assert migrated.startswith(example.rstrip() + "\n\n## Standards References\n")
    run_init(str(tmp_path))
    assert host.read_text() == migrated


@pytest.mark.parametrize(
    "heading",
    [
        "## Standards References",
        "  ## Standards References",
        "## Standards References ##",
    ],
)
def test_real_reference_headings_are_preserved(tmp_path: Path, heading: str) -> None:
    """Existing top-level reference headings remain byte-identical."""
    host = tmp_path / "CLAUDE.md"
    original = heading + "\nExisting references.\n"
    host.write_text(original)

    run_init(str(tmp_path))

    assert host.read_text() == original
