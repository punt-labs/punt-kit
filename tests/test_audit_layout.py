"""The `.punt-labs/` layout findings of `punt audit`, against real git repos.

Each test builds a repository under ``tmp_path`` with one of the gitignore
fixtures in ``tests/fixtures/punt_labs_dir/`` and asserts the exact finding
each check of standards/punt-labs-dir.md § 8 produces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_kit.audit_layout import WARN, LayoutAudit
from punt_kit.audit_verdict import FAIL, PASS
from punt_kit.detect import detect
from tests.helpers import git, init_git_repo

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "punt_labs_dir"

CANONICAL_PASS = "18 probes: 2 tool(s), 2 interim path(s)"


def _repo(
    tmp_path: Path,
    gitignore: str,
    files: dict[str, str] | None = None,
    *,
    tracked: tuple[str, ...] = (),
    forced: tuple[str, ...] = (),
) -> Path:
    """A git repo whose .gitignore is the named fixture, with two tool subtrees.

    ``files`` are written relative to the root; ``tracked`` and ``forced`` name
    the ones to commit, the latter with ``git add -f``.
    """
    root = tmp_path / "repo"
    root.mkdir()
    init_git_repo(root)
    (root / ".gitignore").write_text((FIXTURES / gitignore).read_text())
    contents = {
        ".punt-labs/vox/CLAUDE.md": "# vox\n",
        ".punt-labs/biff/enabled": "",
        **(files or {}),
    }
    for rel, text in contents.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    # Forced: under a deny-all fixture that lacks the bare-directory line the
    # subtree is ignored, and that is exactly what the probe test observes.
    git(["add", "-f", ".gitignore", ".punt-labs/vox/CLAUDE.md"], cwd=str(root))
    if tracked:
        git(["add", *tracked], cwd=str(root))
    if forced:
        git(["add", "-f", *forced], cwd=str(root))
    git(["commit", "-m", "layout"], cwd=str(root))
    return root


def _findings(root: Path) -> list[tuple[str, str, str]]:
    return LayoutAudit(detect(root)).findings()


def _finding(root: Path, label: str) -> tuple[str, str, str]:
    matches = [f for f in _findings(root) if f[1] == label]
    assert len(matches) == 1, matches
    return matches[0]


def _findings_for(root: Path, label: str) -> list[tuple[str, str, str]]:
    return [f for f in _findings(root) if f[1] == label]


# --- Gitignore behaves correctly ---------------------------------------------


@pytest.mark.parametrize("fixture", ["normal.gitignore", "deny-all.gitignore"])
def test_canonical_block_passes_every_probe(tmp_path: Path, fixture: str) -> None:
    root = _repo(tmp_path, fixture)
    assert _finding(root, "Gitignore behaves correctly") == (
        PASS,
        "Gitignore behaves correctly",
        CANONICAL_PASS,
    )


def test_deny_all_without_bare_directory_line_fails_with_diagnostic(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, "deny-all-no-bare-dir.gitignore")
    assert _finding(root, "Gitignore behaves correctly") == (
        FAIL,
        "Gitignore behaves correctly",
        ".punt-labs/biff/CLAUDE.md should not be ignored (.gitignore:1:*); "
        ".punt-labs/biff/config.yaml should not be ignored (.gitignore:1:*); "
        ".punt-labs/biff/locales/en.yaml should not be ignored (.gitignore:1:*); "
        ".punt-labs/biff/config.locales.yaml should not be ignored (.gitignore:1:*); "
        ".punt-labs/vox/config.yaml should not be ignored (.gitignore:1:*); "
        ".punt-labs/vox/locales/en.yaml should not be ignored (.gitignore:1:*); "
        ".punt-labs/vox/config.locales.yaml should not be ignored (.gitignore:1:*)"
        " — deny-all .gitignore lacks the bare-directory line !.punt-labs/"
        " before !.punt-labs/**",
    )


def test_overmatching_glob_fails_the_counterexample_probe(tmp_path: Path) -> None:
    root = _repo(tmp_path, "overmatching-glob.gitignore")
    assert _finding(root, "Gitignore behaves correctly") == (
        FAIL,
        "Gitignore behaves correctly",
        ".punt-labs/biff/config.locales.yaml should not be ignored"
        " (.gitignore:3:.punt-labs/**/*.local*); "
        ".punt-labs/vox/config.locales.yaml should not be ignored"
        " (.gitignore:3:.punt-labs/**/*.local*)"
        " — canonical block lacks .punt-labs/**/*.local, .punt-labs/**/*.local.*;"
        " a *.local* glob anchors only the leading boundary: the block needs"
        " *.local and *.local.* as two lines",
    )


def test_missing_block_fails_every_local_convention_probe(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    init_git_repo(root)
    (root / ".gitignore").write_text("*.pyc\n")
    (root / ".punt-labs" / "vox").mkdir(parents=True)
    (root / ".punt-labs" / "vox" / "CLAUDE.md").write_text("# vox\n")
    git(["add", "."], cwd=str(root))
    git(["commit", "-m", "no block"], cwd=str(root))
    assert _finding(root, "Gitignore behaves correctly") == (
        FAIL,
        "Gitignore behaves correctly",
        ".punt-labs/vox/local/x should be ignored; "
        ".punt-labs/vox/foo.local should be ignored; "
        ".punt-labs/vox/config.local.yaml should be ignored; "
        ".punt-labs/local/vox/x should be ignored; "
        ".punt-labs/quarry/captures/ should be ignored; "
        ".punt-labs/vox/ephemeral/ should be ignored"
        " — canonical block missing from .gitignore",
    )


def test_interim_paths_are_probed_without_their_tool_present(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    (root / ".gitignore").write_text(
        (FIXTURES / "normal.gitignore")
        .read_text()
        .replace(".punt-labs/quarry/captures/\n", "")
    )
    assert _finding(root, "Gitignore behaves correctly") == (
        FAIL,
        "Gitignore behaves correctly",
        ".punt-labs/quarry/captures/ should be ignored",
    )


def test_force_added_local_file_fails_the_probe_as_tracked(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {".punt-labs/vox/foo.local": "x\n"},
        forced=(".punt-labs/vox/foo.local",),
    )
    assert _finding(root, "Gitignore behaves correctly") == (
        FAIL,
        "Gitignore behaves correctly",
        ".punt-labs/vox/foo.local should be ignored (git-tracked)",
    )


# --- No tracked local-convention path ----------------------------------------


def test_no_tracked_local_path_passes(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {
            ".punt-labs/vox/locales/en.yaml": "x\n",
            ".punt-labs/vox/config.locales.yaml": "x\n",
            ".punt-labs/vox/mylocal.txt": "x\n",
        },
        tracked=(
            ".punt-labs/vox/locales/en.yaml",
            ".punt-labs/vox/config.locales.yaml",
            ".punt-labs/vox/mylocal.txt",
        ),
    )
    assert _finding(root, "No tracked local-convention path") == (
        PASS,
        "No tracked local-convention path",
        "4 tracked path(s) under .punt-labs/",
    )


def test_force_added_local_paths_fail(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {
            ".punt-labs/vox/foo.local": "x\n",
            ".punt-labs/vox/config.local.yaml": "x\n",
            ".punt-labs/vox/local/x": "x\n",
        },
        forced=(
            ".punt-labs/vox/foo.local",
            ".punt-labs/vox/config.local.yaml",
            ".punt-labs/vox/local/x",
        ),
    )
    assert _finding(root, "No tracked local-convention path") == (
        FAIL,
        "No tracked local-convention path",
        "Tracked: .punt-labs/vox/config.local.yaml, .punt-labs/vox/foo.local,"
        " .punt-labs/vox/local/x",
    )


# --- No gitignored non-local-convention path ---------------------------------


def test_ignored_local_and_interim_paths_pass(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {
            ".punt-labs/vox/foo.local": "x\n",
            ".punt-labs/vox/local/x": "x\n",
            ".punt-labs/vox/ephemeral/stream": "x\n",
            ".punt-labs/local/vox/x": "x\n",
        },
    )
    assert _finding(root, "No gitignored non-local-convention path") == (
        PASS,
        "No gitignored non-local-convention path",
        "",
    )


def test_stray_tool_specific_ignore_line_fails(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {".punt-labs/vox/vox.md": "x\n", ".punt-labs/vox/call/a.mp3": ""},
    )
    with (root / ".gitignore").open("a") as f:
        f.write(".punt-labs/vox/vox.md\n.punt-labs/vox/call/\n")
    assert _finding(root, "No gitignored non-local-convention path") == (
        FAIL,
        "No gitignored non-local-convention path",
        "Ignored: .punt-labs/vox/call/a.mp3 (.gitignore:8:.punt-labs/vox/call/),"
        " .punt-labs/vox/vox.md (.gitignore:7:.punt-labs/vox/vox.md)",
    )


def test_ignored_bare_file_is_the_bare_file_checks_business(tmp_path: Path) -> None:
    """§ 8 scopes check 3 to ``.punt-labs/<tool>/``; a bare file is graded once."""
    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/lux.md": "x\n"})
    with (root / ".gitignore").open("a") as f:
        f.write("*.pyc\n.punt-labs/lux.md\n")
    assert _finding(root, "No gitignored non-local-convention path") == (
        PASS,
        "No gitignored non-local-convention path",
        "",
    )
    assert _findings_for(root, "No bare file under .punt-labs/") == [
        (
            WARN,
            "No bare file under .punt-labs/",
            ".punt-labs/lux.md — migration pending (§ 9.2 → .punt-labs/lux/)",
        )
    ]


# --- Tool ignore files are committed -----------------------------------------


def test_no_tool_ignore_file_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    assert _finding(root, "Tool ignore files are committed") == (
        PASS,
        "Tool ignore files are committed",
        "no tool ships a .gitignore",
    )


def test_tracked_tool_ignore_files_pass(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {
            ".punt-labs/vox/.gitignore": "ephemeral/\n",
            ".punt-labs/biff/local/.gitignore": "*\n",
        },
        tracked=(".punt-labs/vox/.gitignore",),
        forced=(".punt-labs/biff/local/.gitignore",),
    )
    assert _finding(root, "Tool ignore files are committed") == (
        PASS,
        "Tool ignore files are committed",
        "2 tracked",
    )


def test_untracked_tool_ignore_file_fails(tmp_path: Path) -> None:
    root = _repo(
        tmp_path, "normal.gitignore", {".punt-labs/vox/.gitignore": "ephemeral/\n"}
    )
    assert _finding(root, "Tool ignore files are committed") == (
        FAIL,
        "Tool ignore files are committed",
        "Untracked: .punt-labs/vox/.gitignore",
    )


def test_untracked_and_ignored_tool_ignore_file_fails(tmp_path: Path) -> None:
    """An ignored .gitignore is still live drift: ignore status is no excuse."""
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {
            ".punt-labs/vox/local/.gitignore": "*\n",
            ".punt-labs/biff/.gitignore": "x\n",
        },
        tracked=(".punt-labs/biff/.gitignore",),
    )
    assert _finding(root, "Tool ignore files are committed") == (
        FAIL,
        "Tool ignore files are committed",
        "Untracked: .punt-labs/vox/local/.gitignore",
    )


# --- No legacy root sentinel -------------------------------------------------


def test_no_root_sentinel_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    assert _findings_for(root, "No legacy root sentinel") == [
        (PASS, "No legacy root sentinel", "")
    ]


@pytest.mark.parametrize(
    ("sentinel", "detail"),
    [
        (
            ".biff",
            ".biff — migration pending (§ 9.1 .biff → .punt-labs/biff/config.yaml)",
        ),
        (
            ".vox/config.md",
            ".vox — migration pending (§ 9.1 .vox/config.md → .punt-labs/vox/vox.md)",
        ),
        (".vox/", ".vox — migration pending (§ 9.1 .vox → delete)"),
        (
            ".lux/config.md",
            ".lux — migration pending"
            " (§ 9.1 .lux/config.md → .punt-labs/lux/config.md)",
        ),
        (".lux/", ".lux — migration pending (§ 9.1 .lux → delete)"),
        (
            ".ethos/missions.jsonl",
            ".ethos — migration pending"
            " (§ 9.1 .ethos/missions.jsonl → .punt-labs/local/ethos/missions.jsonl)",
        ),
        (
            ".ethos/",
            ".ethos — migration pending"
            " (§ 9.1 .ethos/missions.jsonl → .punt-labs/local/ethos/missions.jsonl)",
        ),
    ],
)
def test_sentinel_named_by_a_row_warns(
    tmp_path: Path, sentinel: str, detail: str
) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    target = root / sentinel
    if sentinel.endswith("/"):
        target.mkdir()
    else:
        target.parent.mkdir(exist_ok=True)
        target.write_text("")
    assert _findings_for(root, "No legacy root sentinel") == [
        (WARN, "No legacy root sentinel", detail)
    ]


def test_dangling_symlink_sentinel_is_present(tmp_path: Path) -> None:
    """A sentinel occupies its path even when it is a symlink to nothing."""
    root = _repo(tmp_path, "normal.gitignore")
    (root / ".vox").symlink_to(root / "nowhere")
    assert _findings_for(root, "No legacy root sentinel") == [
        (
            WARN,
            "No legacy root sentinel",
            ".vox — migration pending (§ 9.1 .vox → delete)",
        )
    ]


def test_sentinel_with_no_migration_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    (root / ".quarry.toml").write_text("")
    assert _findings_for(root, "No legacy root sentinel") == [
        (
            FAIL,
            "No legacy root sentinel",
            ".quarry.toml — a stray, not a sentinel (§ 9.1: no migration)",
        )
    ]


def test_sentinel_check_runs_outside_git(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / ".vox").mkdir()
    assert _findings(root) == [
        (
            WARN,
            "No legacy root sentinel",
            ".vox — migration pending (§ 9.1 .vox → delete)",
        )
    ]


def test_no_findings_without_punt_labs_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    init_git_repo(root)
    assert _findings(root) == [(PASS, "No legacy root sentinel", "")]


# --- Live-state migration pending --------------------------------------------


def test_untracked_live_path_grades_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/vox/ephemeral/s": ""})
    assert _findings_for(root, "Live-state migration pending") == [
        (PASS, "Live-state migration pending", "no § 9.4 live path is git-tracked")
    ]


def test_tracked_live_path_warns(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {
            ".punt-labs/vox/ephemeral/s": "",
            ".punt-labs/quarry/captures/c": "",
            ".punt-labs/quarry/captures/d": "",
        },
        forced=(
            ".punt-labs/vox/ephemeral/s",
            ".punt-labs/quarry/captures/c",
            ".punt-labs/quarry/captures/d",
        ),
    )
    assert _findings_for(root, "Live-state migration pending") == [
        (
            WARN,
            "Live-state migration pending",
            ".punt-labs/quarry/captures/ is git-tracked (2 files) — migration"
            " pending (§ 9.4 → ~/.punt-labs/quarry/captures/)",
        ),
        (
            WARN,
            "Live-state migration pending",
            ".punt-labs/vox/ephemeral/ is git-tracked (1 file) — migration"
            " pending (§ 9.4 → ~/.punt-labs/vox/)",
        ),
    ]


# --- No interim exclude survives a completed migration -----------------------


def test_only_table_backed_excludes_pass(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    with (root / ".gitignore").open("a") as f:
        f.write(
            "!.punt-labs/vox/keep\n.punt-labs/local/\n.punt-labs/vox/vox.local.md\n"
        )
    assert _finding(root, "No interim exclude survives a completed migration") == (
        PASS,
        "No interim exclude survives a completed migration",
        "2 interim exclude(s), each named by a § 9.4 row",
    )


def test_interim_exclude_no_row_names_fails(tmp_path: Path) -> None:
    """A line inside the canonical block for a path § 9.4 no longer names."""
    root = _repo(tmp_path, "normal.gitignore")
    text = (root / ".gitignore").read_text()
    (root / ".gitignore").write_text(text + ".punt-labs/ethos/sessions/\n")
    assert _finding(root, "No interim exclude survives a completed migration") == (
        FAIL,
        "No interim exclude survives a completed migration",
        "Stale: .punt-labs/ethos/sessions/ (.gitignore:7) — no § 9.4 row names"
        " this path; the migration is finished yet its old location is still"
        " ignored",
    )


def test_ignore_line_outside_the_block_is_not_an_interim_exclude(
    tmp_path: Path,
) -> None:
    """A stray .punt-labs/ line elsewhere is check 3's or the bare-file check's."""
    root = _repo(tmp_path, "normal.gitignore")
    with (root / ".gitignore").open("a") as f:
        f.write("*.pyc\n.punt-labs/lux.md\n.punt-labs/ethos/.biff\n")
    assert _finding(root, "No interim exclude survives a completed migration") == (
        PASS,
        "No interim exclude survives a completed migration",
        "2 interim exclude(s), each named by a § 9.4 row",
    )


def test_block_line_for_a_bare_file_row_is_that_rows_business(
    tmp_path: Path,
) -> None:
    """``.punt-labs/lux.md`` in the block is graded by the bare-file row, not here."""
    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/lux.md": "x\n"})
    text = (root / ".gitignore").read_text()
    (root / ".gitignore").write_text(text + ".punt-labs/lux.md\n")
    findings = _findings(root)
    assert (
        PASS,
        "No interim exclude survives a completed migration",
        "2 interim exclude(s), each named by a § 9.4 row",
    ) in findings
    assert (
        WARN,
        "No bare file under .punt-labs/",
        ".punt-labs/lux.md — migration pending (§ 9.2 → .punt-labs/lux/)",
    ) in findings
    assert (
        PASS,
        "No gitignored non-local-convention path",
        "",
    ) in findings


def test_block_missing_means_no_interim_excludes(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore")
    (root / ".gitignore").write_text(".punt-labs/ethos/sessions/\n")
    assert _finding(root, "No interim exclude survives a completed migration") == (
        PASS,
        "No interim exclude survives a completed migration",
        "no canonical block, so no interim excludes",
    )


# --- No bare file under .punt-labs/ ------------------------------------------


def test_subtrees_and_named_exception_pass(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        "normal.gitignore",
        {".punt-labs/ethos.yaml": "agent: claude\n", ".punt-labs/local/vox/x": ""},
    )
    assert _findings_for(root, "No bare file under .punt-labs/") == [
        (PASS, "No bare file under .punt-labs/", "")
    ]


def test_bare_file_named_by_a_row_warns(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/lux.md": "display\n"})
    assert _findings_for(root, "No bare file under .punt-labs/") == [
        (
            WARN,
            "No bare file under .punt-labs/",
            ".punt-labs/lux.md — migration pending (§ 9.2 → .punt-labs/lux/)",
        )
    ]


def test_bare_file_with_no_row_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/foo": ""})
    assert _findings_for(root, "No bare file under .punt-labs/") == [
        (
            FAIL,
            "No bare file under .punt-labs/",
            ".punt-labs/foo — no § 9 row names it",
        )
    ]


def test_local_zone_must_be_a_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/local": ""})
    assert _findings_for(root, "No bare file under .punt-labs/") == [
        (
            FAIL,
            "No bare file under .punt-labs/",
            ".punt-labs/local is not a directory — it blocks the local zone",
        )
    ]


# --- Registration ------------------------------------------------------------


def test_run_audit_prints_layout_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from punt_kit.audit import run_audit

    root = _repo(tmp_path, "normal.gitignore")
    (root / ".vox").mkdir()
    with pytest.raises(SystemExit):
        run_audit(str(root))
    out = capsys.readouterr().out
    assert "Gitignore behaves correctly" in out
    assert ".vox — migration pending" in out


def test_run_audit_prints_gitignore_lines_and_globs_verbatim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``:100:`` is not an emoji code and ``[abc]`` is a glob, not markup."""
    from punt_kit.audit import run_audit

    root = _repo(tmp_path, "normal.gitignore")
    lines = (root / ".gitignore").read_text().splitlines()
    lines += [""] * (99 - len(lines))
    lines.append(".punt-labs/vox/[abc].md")
    (root / ".gitignore").write_text("\n".join(lines) + "\n")
    with pytest.raises(SystemExit):
        run_audit(str(root))
    out = capsys.readouterr().out
    assert ".punt-labs/vox/[abc].md (.gitignore:100)" in out


def test_run_audit_prints_a_check3_line_100_citation_verbatim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check 3 cites ``source:line:pattern``, so ``:100:`` must not become an emoji."""
    from punt_kit.audit import run_audit

    root = _repo(tmp_path, "normal.gitignore", {".punt-labs/vox/vox.md": "x\n"})
    lines = (root / ".gitignore").read_text().splitlines()
    lines += [""] * (99 - len(lines))
    lines.append(".punt-labs/vox/vox.md")
    (root / ".gitignore").write_text("\n".join(lines) + "\n")
    with pytest.raises(SystemExit):
        run_audit(str(root))
    out = capsys.readouterr().out
    assert ".punt-labs/vox/vox.md (.gitignore:100:.punt-labs/vox/vox.md)" in out


def test_findings_run_from_any_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probes run with cwd at the repo root, so the caller's cwd is irrelevant."""
    root = _repo(tmp_path, "normal.gitignore")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert _finding(root, "Gitignore behaves correctly")[0] == PASS
