"""Exercise local test selection and enforcement of quarantine metadata."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools.test_changed import select_tests
from tools.test_quarantine import pytest_collection_modifyitems, quarantine_is_valid

_ROOT = Path(__file__).resolve().parents[1]


def test_precommit_tests_the_index_not_the_working_tree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Tester",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    (tmp_path / "tests").mkdir()
    probe = tmp_path / "tests/test_probe.py"
    probe.write_text(
        "import subprocess\n"
        "def test_probe():\n"
        "    current = subprocess.check_output("
        "['git', 'rev-parse', 'HEAD'], text=True)\n"
        f"    assert current.strip() == {head!r}\n"
        "    assert False, 'index-only failure'\n"
    )
    subprocess.run(["git", "add", "tests/test_probe.py"], cwd=tmp_path, check=True)
    probe.write_text("def test_probe():\n    assert True\n")

    result = subprocess.run(
        [sys.executable, str(_ROOT / "tools/test_changed.py")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTEST_ADDOPTS": shlex.join(["--basetemp", str(tmp_path / "child")]),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert "AssertionError: index-only failure" in result.stdout
    assert probe.read_text() == "def test_probe():\n    assert True\n"


@pytest.fixture
def prepush_hook(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Tester",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "probe",
        ],
        cwd=tmp_path,
        check=True,
    )
    hooks = tmp_path / ".githooks"
    hooks.mkdir()
    installed = hooks / "pre-push"
    installed.write_bytes((_ROOT / ".githooks/pre-push").read_bytes())
    installed.chmod(0o755)
    (tmp_path / "Makefile").write_text("test-push:\n\t@echo ran-push-gate\n")
    return installed


def test_prepush_refuses_to_test_a_different_commit(
    tmp_path: Path, prepush_hook: Path
) -> None:
    result = subprocess.run(
        [str(prepush_hook)],
        cwd=tmp_path,
        input=f"refs/heads/other {'1' * 40} refs/heads/other {'0' * 40}\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert "check it out and push it separately" in result.stderr


def test_prepush_accepts_tag_at_head(tmp_path: Path, prepush_hook: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Tester",
            "-c",
            "user.email=test@example.com",
            "tag",
            "-a",
            "v1",
            "-m",
            "probe",
        ],
        cwd=tmp_path,
        check=True,
    )
    tag = subprocess.check_output(
        ["git", "rev-parse", "refs/tags/v1"], cwd=tmp_path, text=True
    ).strip()
    result = subprocess.run(
        [str(prepush_hook)],
        cwd=tmp_path,
        input=f"refs/tags/v1 {tag} refs/tags/v1 {'0' * len(tag)}\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ran-push-gate" in result.stdout


def test_prepush_replays_refs_and_args_to_chained_hook(
    tmp_path: Path, prepush_hook: Path
) -> None:
    custom_hook = tmp_path / "custom-hook"
    custom_hook.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > args\ncat > refs\n')
    custom_hook.chmod(0o755)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    refs = f"HEAD {head} refs/heads/main {'0' * len(head)}\n"
    result = subprocess.run(
        [str(prepush_hook), "--chain", str(custom_hook), "origin", "remote-url"],
        cwd=tmp_path,
        input=refs,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ran-push-gate" in result.stdout
    assert (tmp_path / "args").read_text() == "origin\nremote-url\n"
    assert (tmp_path / "refs").read_text() == refs


def test_prepush_skips_gate_for_empty_ref_list_but_chains(
    tmp_path: Path, prepush_hook: Path
) -> None:
    custom_hook = tmp_path / "custom-hook"
    custom_hook.write_text("#!/bin/sh\ncat\nprintf 'ran-custom-hook\\n'\n")
    custom_hook.chmod(0o755)
    result = subprocess.run(
        [str(prepush_hook), "--chain", str(custom_hook)],
        cwd=tmp_path,
        input="",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ran-push-gate" not in result.stdout
    assert result.stdout == "ran-custom-hook\n"


def test_prepush_wrapper_falls_through_in_older_worktree(
    tmp_path: Path, prepush_hook: Path
) -> None:
    legacy = tmp_path / "legacy"
    subprocess.run(
        ["git", "worktree", "add", "--quiet", "--detach", str(legacy), "HEAD"],
        cwd=prepush_hook.parents[1],
        check=True,
    )
    assert not (legacy / ".githooks/pre-push").exists()
    custom_hook = tmp_path / "custom hook"
    custom_hook.write_text("#!/bin/sh\ncat\n")
    custom_hook.chmod(0o755)
    docs = (_ROOT / "TESTING.md").read_text()
    blocks = (block.split("```", 1)[0] for block in docs.split("```bash\n")[1:])
    script = next(block for block in blocks if ".githooks/pre-push --chain" in block)
    script = script.replace("/path/to/custom-hook", shlex.quote(str(custom_hook)))
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=legacy,
        input="refs forwarded to the custom hook\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "refs forwarded to the custom hook\n"
    assert "gate not present in this worktree" in result.stderr


def test_prepush_buffers_refs_even_when_checkout_tmpdir_is_missing(
    tmp_path: Path, prepush_hook: Path
) -> None:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    result = subprocess.run(
        [str(prepush_hook)],
        cwd=tmp_path,
        env={**os.environ, "TMPDIR": str(tmp_path / ".tmp")},
        input=f"HEAD {head} refs/heads/main {'0' * len(head)}\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ran-push-gate" in result.stdout
    assert not (tmp_path / ".tmp").exists()


def test_changed_module_and_test_select_relevant_paths(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    matching = tests / "test_pii.py"
    matching.write_text("from punt_kit.pii import scan\n")
    unrelated = tests / "test_audit.py"
    unrelated.write_text("from punt_kit.audit import run_audit\n")
    staged = {Path("src/punt_kit/pii.py"), unrelated.relative_to(tmp_path)}

    assert select_tests(tmp_path, staged) == sorted(
        path.relative_to(tmp_path) for path in (matching, unrelated)
    )


@pytest.mark.parametrize(
    "path", ["tests/conftest.py", "src/punt_kit/unmapped.py", "uv.lock"]
)
def test_shared_or_unmapped_changes_select_default_suite(
    tmp_path: Path, path: str
) -> None:
    assert select_tests(tmp_path, {Path(path)}) is None


def test_docs_only_changes_do_not_select_python_tests(tmp_path: Path) -> None:
    assert select_tests(tmp_path, {Path("README.md")}) == []


@pytest.mark.parametrize(
    ("path", "test"),
    [
        (".gitignore", "tests/test_repo_gitignore.py"),
        ("TESTING.md", "tests/test_test_gates.py"),
    ],
)
def test_root_files_select_the_tests_that_read_them(path: str, test: str) -> None:
    assert select_tests(_ROOT, {Path(path)}) == [Path(test)]


@pytest.mark.parametrize(
    "path", ["standards/testing.md", "lang-rules/python/python-testing.md"]
)
def test_standards_changes_select_default_suite(tmp_path: Path, path: str) -> None:
    assert select_tests(tmp_path, {Path(path)}) is None


def test_indirect_source_consumers_select_default_suite(tmp_path: Path) -> None:
    source = tmp_path / "src/punt_kit"
    source.mkdir(parents=True)
    (source / "command.py").write_text("from .audit import run_audit\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_audit.py").write_text("from punt_kit.audit import run_audit\n")

    assert select_tests(tmp_path, {Path("src/punt_kit/audit.py")}) is None


@pytest.mark.parametrize(
    ("issue", "owner", "reason", "expires", "valid"),
    [
        ("PL-12", "tester", "intermittent timeout", "2026-11-24", True),
        ("PL-12", "tester", "intermittent timeout", "2026-12-08", True),
        ("#12", "tester", "intermittent timeout", "2026-11-25", False),
        ("PL-12", " ", "intermittent timeout", "2026-11-25", False),
        ("PL-12", "tester", "", "2026-11-25", False),
        ("PL-12", "tester", "intermittent timeout", "2026-11-23", False),
        ("PL-12", "tester", "intermittent timeout", "2026-12-09", False),
        ("PL-12", "tester", "intermittent timeout", "2026-11-31", False),
    ],
)
def test_quarantine_requires_an_owned_and_near_term_deadline(
    issue: str, owner: str, reason: str, expires: str, valid: bool
) -> None:
    mark = pytest.mark.quarantine(
        issue=issue, owner=owner, reason=reason, expires=expires
    ).mark
    assert quarantine_is_valid(mark, date(2026, 11, 24)) is valid


def test_collection_rejects_invalid_quarantine() -> None:
    item = Mock(spec=pytest.Item, nodeid="tests/test_example.py::test_flaky")
    item.iter_markers.return_value = [pytest.mark.quarantine().mark]

    with pytest.raises(pytest.UsageError, match="test_flaky: quarantine requires"):
        pytest_collection_modifyitems([item])


@pytest.mark.parametrize("expired", [True, False])
def test_quarantine_is_enforced_during_real_collection(
    tmp_path: Path, expired: bool
) -> None:
    (tmp_path / "conftest.py").write_bytes((_ROOT / "tests/conftest.py").read_bytes())
    expires = "2000-01-01" if expired else datetime.now(UTC).date().isoformat()
    (tmp_path / "test_probe.py").write_text(
        "import pytest\n"
        f"@pytest.mark.quarantine(issue='PL-1', owner='tester', "
        f"reason='probe', expires={expires!r})\n"
        "def test_quarantined():\n    pass\n"
        "def test_default():\n    pass\n"
    )
    args = ["--collect-only"] if expired else ["-m", "quarantine"]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(_ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            *args,
            "test_probe.py",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(_ROOT),
            "PYTEST_ADDOPTS": shlex.join(["--basetemp", str(tmp_path / "child")]),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if expired:
        assert result.returncode == pytest.ExitCode.USAGE_ERROR
        assert "test_quarantined: quarantine requires" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert "1 passed, 1 deselected" in result.stdout


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        text=True,
    ).strip()


def _push(
    hook: Path, cwd: Path, ref: str, oid: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(hook)],
        cwd=cwd,
        input=f"{ref} {oid} {ref} {'0' * 40}\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("on_main", [True, False])
def test_prepush_lets_a_tag_on_an_earlier_main_commit_through(
    tmp_path: Path, prepush_hook: Path, on_main: bool
) -> None:
    _git(tmp_path, "tag", "-a", "v1", "-m", "release")
    tag = _git(tmp_path, "rev-parse", "refs/tags/v1")
    if on_main:
        _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(tmp_path, "commit", "--quiet", "--allow-empty", "-m", "later")

    result = _push(prepush_hook, tmp_path, "refs/tags/v1", tag)
    assert "ran-push-gate" not in result.stdout
    if on_main:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "check it out and push it separately" in result.stderr


def test_prepush_refuses_uncommitted_changes(
    tmp_path: Path, prepush_hook: Path
) -> None:
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("committed\n")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "tracked")
    tracked.write_text("uncommitted\n")

    result = _push(
        prepush_hook, tmp_path, "refs/heads/main", _git(tmp_path, "rev-parse", "HEAD")
    )
    assert result.returncode == 1
    assert "commit or stash them" in result.stderr


_TOKEN_BINDING = re.compile(
    r"^ +BIFF_RELAY_TOKEN: \$\{\{ secrets\.BIFF_RELAY_TOKEN \}\}$", re.MULTILINE
)


def _job(workflow: str, name: str) -> str:
    start = workflow.index(f"\n  {name}:\n")
    end = re.search(r"\n  [a-z-]+:\n", workflow[start + 1 :])
    return workflow[start : start + 1 + end.start()] if end else workflow[start:]


def test_nightly_runs_on_main_and_alerts_biff_on_failure() -> None:
    workflow = (_ROOT / ".github/workflows/nightly.yml").read_text()
    nightly, notify = _job(workflow, "nightly"), _job(workflow, "notify")
    assert "github.ref == 'refs/heads/main'" in nightly
    assert re.search(r"^ +run: make test-nightly$", nightly, re.MULTILINE)
    assert "needs.nightly.result == 'failure'" in notify
    assert _TOKEN_BINDING.search(notify)
    assert re.search(
        r"^ +uvx --from punt-biff==\S+ biff --user github-actions wall$",
        notify,
        re.MULTILINE,
    )


def test_biff_notify_binds_the_relay_token_and_trusted_config() -> None:
    workflow = (_ROOT / ".github/workflows/biff-notify.yml").read_text()
    assert _TOKEN_BINDING.search(workflow)
    assert re.search(
        r"^ +ref: \$\{\{ github\.event\.repository\.default_branch \}\}$",
        workflow,
        re.MULTILINE,
    )
