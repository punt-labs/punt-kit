"""The release spawns a process in exactly one place, so the hook floor is total."""

from __future__ import annotations

from pathlib import Path

import pytest

import punt_kit
from tests.harness.spawn_scan import SpawnScan

_PACKAGE = Path(punt_kit.__file__).parent


@pytest.mark.parametrize(
    ("source", "found"),
    [
        pytest.param(
            "import subprocess\nsubprocess.run(c)", ["subprocess.run"], id="run"
        ),
        pytest.param(
            "import subprocess as sp\nsp.run(c)", ["subprocess.run"], id="alias"
        ),
        pytest.param(
            "import subprocess as sp\nsp.Popen(c)", ["subprocess.Popen"], id="popen"
        ),
        pytest.param(
            "from subprocess import run", ["subprocess.run"], id="from-import"
        ),
        pytest.param(
            "from subprocess import run as r", ["subprocess.run"], id="from-import-as"
        ),
        pytest.param("from subprocess import *", ["subprocess.*"], id="star"),
        pytest.param('__import__("subprocess")', ["__import__"], id="dunder-import"),
        pytest.param(
            'import importlib\nimportlib.import_module("os")',
            ["import_module"],
            id="import-module",
        ),
        pytest.param("__import__(name)", ["__import__"], id="computed-import"),
        pytest.param("import os\nos.system(c)", ["os.system"], id="os-system"),
        pytest.param("import os as o\no.execvp(a, b)", ["os.execvp"], id="os-exec"),
        pytest.param("from os import fork", ["os.fork"], id="os-fork"),
        pytest.param("import os\nos.spawnl(1, a)", ["os.spawnl"], id="os-spawn"),
        pytest.param("import pty\npty.spawn(c)", ["pty.spawn"], id="pty"),
        pytest.param(
            "import asyncio\nasyncio.create_subprocess_exec(c)",
            ["asyncio.create_subprocess_exec"],
            id="asyncio",
        ),
        pytest.param(
            "import multiprocessing\nmultiprocessing.Process(target=f)",
            ["multiprocessing.Process"],
            id="multiprocessing",
        ),
    ],
)
def test_the_scan_catches_every_way_to_start_a_process(
    source: str, found: list[str]
) -> None:
    assert SpawnScan.of_source(source).spawning_names() == found


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import subprocess\nsubprocess.TimeoutExpired", id="timeout"),
        pytest.param("import subprocess\nsubprocess.CalledProcessError", id="called"),
        pytest.param("import subprocess as sp\nsp.CompletedProcess", id="completed"),
        pytest.param("from subprocess import TimeoutExpired", id="from-timeout"),
        pytest.param("import os\nos.path.join(a, b)", id="os-path"),
        pytest.param("import asyncio\nasyncio.sleep(1)", id="asyncio-sleep"),
    ],
)
def test_the_scan_allows_the_types_and_unrelated_calls(source: str) -> None:
    assert SpawnScan.of_source(source).spawning_names() == []


def test_the_scan_follows_imports_inside_the_package() -> None:
    reached = {path.name for path in SpawnScan.reachable_from(_PACKAGE / "release.py")}
    assert {"release.py", "pr_merge.py", "timeouts.py", "detect.py"} <= reached


def test_only_run_spawns_a_release_process() -> None:
    """Across release.py and every module it reaches, only ``_run`` spawns."""
    spawners = {
        path.name: SpawnScan.of_file(path).spawning_names()
        for path in SpawnScan.reachable_from(_PACKAGE / "release.py")
        if SpawnScan.of_file(path).spawning_names()
    }
    assert spawners == {"release.py": ["subprocess.run"]}
