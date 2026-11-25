"""Exercise real entry-point diagnostic files and local telemetry capture."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from punt_observe.telemetry import EnumAttr
from typer.core import TyperGroup
from typer.main import get_command

from punt_kit.__main__ import app
from punt_kit.command_span import CommandSpan
from punt_kit.paths import PuntPaths


def _run(
    home: Path, *args: str, code: str = "", off: bool = False, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, HOME=str(home), PUNT_TELEMETRY="off" if off else "on")
    command = (
        [sys.executable, "-c", code]
        if code
        else [sys.executable, "-m", "punt_kit", *args]
    )
    return subprocess.run(
        command, env=env, cwd=cwd, capture_output=True, text=True, check=False
    )


def _rows(home: Path) -> list[tuple[str, int, str, dict[str, object]]]:
    with sqlite3.connect(home / ".punt-labs/punt/telemetry.db") as connection:
        rows = connection.execute(
            "SELECT name, schema_version, status, attributes FROM spans"
        ).fetchall()
    return [
        (name, version, status, json.loads(attrs))
        for name, version, status, attrs in rows
    ]


def test_real_private_entrypoint_files(tmp_path: Path) -> None:
    result = _run(tmp_path, "--json", "version")
    assert result.returncode == 0, result.stderr
    assert "version" in json.loads(result.stdout)
    log = tmp_path / ".punt-labs/punt/logs/punt.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    for directory in (log.parent, log.parent.parent, log.parent.parent.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert "CLI invocation command=version" in log.read_text()
    assert _rows(tmp_path) == [
        (
            "punt.cli.command",
            1,
            "OK",
            {
                "command": "version",
                "json": True,
                "outcome": "ok",
            },
        )
    ]


def test_nested_parse_error_records_requested_json(tmp_path: Path) -> None:
    result = _run(tmp_path, "repo", "not-a-command", "--json")

    assert result.returncode == 2
    assert "No such command" in json.loads(result.stdout)["error"]
    assert _rows(tmp_path)[0][3] == {
        "command": "repo",
        "json": True,
        "outcome": "error",
    }


@pytest.mark.parametrize(
    "args,command,exit_code,outcome",
    [
        (["status", "/nonexistent-punt-observe-test"], "status", 1, "error"),
        (["--verbose", "--quiet", "version"], "version", 2, "error"),
        (["version", "--invalid-option"], "version", 2, "error"),
        ([], "punt", 0, "ok"),
        (["--help"], "punt", 0, "ok"),
        (["not-a-command"], "unknown", 2, "error"),
    ],
)
def test_outcomes(
    tmp_path: Path, args: list[str], command: str, exit_code: int, outcome: str
) -> None:
    result = _run(tmp_path, *args)
    assert result.returncode == exit_code, result.stderr
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3]["command"] == command
    assert rows[0][3]["outcome"] == outcome
    log = (tmp_path / ".punt-labs/punt/logs/punt.log").read_text()
    assert log.count("CLI invocation finished") == 1
    assert f"command={command} outcome={outcome} exit_code={exit_code}" in log


@pytest.mark.parametrize(
    "statement,expected",
    [
        ("raise typer.Exit(7)", 7),
        ("raise typer.Exit(0)", 0),
        ("raise RuntimeError('private content')", 1),
    ],
)
def test_command_exceptions(tmp_path: Path, statement: str, expected: int) -> None:
    code = f"""
import typer
from punt_kit.__main__ import app
@app.command()
def example():
    {statement}
app(['example'])
"""
    result = _run(tmp_path, code=code)
    assert result.returncode == expected
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3]["outcome"] == ("ok" if expected == 0 else "error")
    assert "private content" not in json.dumps(rows)
    log = (tmp_path / ".punt-labs/punt/logs/punt.log").read_text()
    assert log.count("CLI invocation finished") == 1
    assert f"exit_code={expected}" in log
    assert "private content" not in log


def test_utf8_opt_out_under_ascii_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("PYTHONCOERCECLOCALE", "0")
    monkeypatch.setenv("PYTHONUTF8", "0")
    config = tmp_path / ".punt-labs/punt/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[telemetry]\nenabled = false # café\n", encoding="utf-8")

    result = _run(tmp_path, "version")

    assert result.returncode == 0, result.stderr
    assert not (config.parent / "telemetry.db").exists()


def test_disabled_creates_no_store(tmp_path: Path) -> None:
    assert _run(tmp_path, "version", off=True).returncode == 0
    assert not (tmp_path / ".punt-labs/punt/telemetry.db").exists()
    assert not (tmp_path / ".punt-labs/telemetry.salt").exists()


def test_user_settings_read_from_home_not_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "checkout"
    for directory, enabled in ((home, "false"), (checkout, "true")):
        config = directory / ".punt-labs/punt/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(f"[telemetry]\nenabled = {enabled}\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(checkout)

    paths = PuntPaths()
    assert paths.home == home / ".punt-labs" / "punt"
    assert not PuntPaths.telemetry_config().enabled


def test_relative_home_does_not_use_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", ".")

    with pytest.raises(RuntimeError, match="user home directory must be absolute"):
        PuntPaths()


def test_relative_home_keeps_cli_running_without_local_capture(tmp_path: Path) -> None:
    config = tmp_path / ".punt-labs/punt/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[telemetry]\nenabled = true\n")

    result = _run(Path("."), "version", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("punt ")
    assert "Check telemetry configuration: home unavailable" in result.stderr
    assert not (config.parent / "telemetry.db").exists()
    assert not (tmp_path / ".punt-labs/telemetry.salt").exists()


def test_unavailable_home_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with (
        patch.object(
            Path,
            "home",
            side_effect=RuntimeError("Could not determine home directory."),
        ),
        pytest.raises(RuntimeError, match="Could not determine home directory"),
    ):
        PuntPaths()

    with patch.object(Path, "home", side_effect=RuntimeError("No home")):
        assert not PuntPaths.telemetry_config().enabled


@pytest.mark.parametrize(
    "enabled,off,newline",
    [
        (False, False, "\n"),
        (True, True, "\n"),
        (False, True, "\n"),
        (False, False, "\r"),
    ],
)
def test_persistent_and_environment_opt_outs_are_any_off_wins(
    tmp_path: Path, enabled: bool, off: bool, newline: str
) -> None:
    config = tmp_path / ".punt-labs/punt/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f"[telemetry]\nenabled = {str(enabled).lower()}\n", newline=newline
    )
    result = _run(tmp_path, "version", off=off)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("punt ")
    assert not (config.parent / "telemetry.db").exists()
    assert not (tmp_path / ".punt-labs/telemetry.salt").exists()


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"[telemetry]\nenabled = true\n",
        b"[telemetry]\nenabled = 'private-content'\n",
        b"telemetry = 'private-content'\n",
        b"[telemetry\nprivate-content",
        b"\xffprivate-content",
    ],
)
def test_user_settings_defaults_and_invalid_input_preserve_command(
    tmp_path: Path, source: bytes
) -> None:
    config = tmp_path / ".punt-labs/punt/config.toml"
    config.parent.mkdir(parents=True)
    config.write_bytes(source)
    result = _run(tmp_path, "version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("punt ")
    assert _rows(tmp_path)[0][3]["outcome"] == "ok"
    assert "private-content" not in (config.parent / "logs/punt.log").read_text()
    assert "private-content" not in result.stderr


def test_unreadable_user_settings_preserve_command(tmp_path: Path) -> None:
    config = tmp_path / ".punt-labs/punt/config.toml"
    config.mkdir(parents=True)
    result = _run(tmp_path, "version")
    assert result.returncode == 0, result.stderr
    assert _rows(tmp_path)[0][3]["outcome"] == "ok"


def test_nonstandalone_exit_code(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        code="""
import typer
from punt_kit.__main__ import app
@app.command()
def example():
    raise typer.Exit(7)
assert app(['example'], standalone_mode=False) == 7
""",
    )
    assert result.returncode == 0, result.stderr
    assert _rows(tmp_path)[0][3]["outcome"] == "error"
    log = (tmp_path / ".punt-labs/punt/logs/punt.log").read_text()
    assert log.count("CLI invocation finished") == 1
    assert "command=example outcome=error exit_code=7" in log


def test_installed_console_entrypoint(tmp_path: Path) -> None:
    executable = Path(sys.executable).parent / "punt"
    env = dict(os.environ, HOME=str(tmp_path), PUNT_TELEMETRY="on")
    result = subprocess.run(
        [str(executable), "version"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert _rows(tmp_path)[0][3]["command"] == "version"


def test_unavailable_store_preserves_result(tmp_path: Path) -> None:
    (tmp_path / ".punt-labs/punt/telemetry.db").mkdir(parents=True)
    result = _run(tmp_path, "version")
    assert result.returncode == 0
    assert result.stdout.startswith("punt ")


def test_closed_schema_drops_unknown_values(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        code="""
from punt_observe.telemetry import open_telemetry
from punt_kit.command_span import CommandSpan
t = open_telemetry('punt', [CommandSpan.command_schema(('version',))])
with t.span('punt.cli.command', 1, command='unregistered'):
    pass
with t.span('punt.cli.command', 1, command='version', secret='private content'):
    pass
with t.span('punt.cli.command', 1, command='version'):
    pass
""",
    )
    assert result.returncode == 0, result.stderr
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3]["command"] == "version"
    assert "private content" not in json.dumps(rows)


def test_schema_matches_registered_commands() -> None:
    group = get_command(app)
    assert isinstance(group, TyperGroup)
    schema = CommandSpan.command_schema(tuple(group.commands))
    command = schema.attributes["command"]
    assert isinstance(command, EnumAttr)
    assert set(command.values) == {"punt", "unknown", *group.commands}


def test_concurrent_entrypoint_logging_rolls_over_without_loss(tmp_path: Path) -> None:
    workers, records = 4, 100
    payload = ("x" * 1000 + " ") * 20
    code = """
import json
import logging
import sys
from punt_kit.logging_config import EntryPointLogging
EntryPointLogging().configure()
sys.stdout.write('ready\\n')
sys.stdout.flush()
sys.stdin.readline()
logger = logging.getLogger('rotation')
for index in range(100):
    logger.info(json.dumps({
        'worker': int(sys.argv[1]), 'index': index,
        'payload': ('x' * 1000 + ' ') * 20,
    }))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(worker)],
            env=dict(os.environ, HOME=str(tmp_path)),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker in range(workers)
    ]
    try:
        for process in processes:
            assert process.stdout is not None
            assert process.stdout.readline() == "ready\n"
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("go\n")
            process.stdin.flush()
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, stderr
            assert stdout == stderr == ""
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    directory = tmp_path / ".punt-labs/punt/logs"
    files = list(directory.iterdir())
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
    backups = [path for path in files if path.suffix[1:].isdigit()]
    assert 1 <= len(backups) <= 5
    logs = [directory / "punt.log", *backups]
    file_bound = 5 * 1024 * 1024
    assert all(path.stat().st_size <= file_bound for path in logs)
    assert sum(path.stat().st_size for path in files) <= 6 * file_bound
    seen: list[tuple[int, int]] = []
    for path in logs:
        for line in path.read_text().splitlines(keepends=True):
            assert line.endswith("\n")
            prefix, message = line.split(" [INFO] rotation: ", 1)
            assert len(prefix) == 19
            record = json.loads(message)
            assert record["payload"] == payload
            seen.append((record["worker"], record["index"]))
    assert len(seen) == workers * records
    assert set(seen) == {
        (worker, index) for worker in range(workers) for index in range(records)
    }
