"""The modules the release runs start a process in exactly one place.

That place is ``CommandRunner.run`` in ``phases/shared/command_runner.py``;
``release._run`` delegates to it.

The scan is static: it watches the ``subprocess``, ``os``, ``pty``, ``asyncio``,
``multiprocessing`` and ``concurrent.futures`` process APIs and string-based
imports of them, in the modules reachable by absolute imports from
``release.py`` and from the ``release`` command's entry in ``__main__.py``. A
process started by a program those modules run, or by code the scan cannot
resolve, is outside it; the hook floor ``CommandRunner.run`` applies covers
everything that reaches it.
"""

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
        pytest.param(
            'import os\ngetattr(os, "system")(c)', ["getattr(os)"], id="getattr-os"
        ),
        pytest.param(
            'import subprocess as sp\ngetattr(sp, "run")(c)',
            ["getattr(subprocess)"],
            id="getattr-subprocess",
        ),
        pytest.param(
            'from importlib import import_module as im\nim("os").system(c)',
            ["import_module"],
            id="import-module-alias",
        ),
        pytest.param(
            'import importlib as il\nil.import_module("os")',
            ["import_module"],
            id="importlib-alias",
        ),
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
        pytest.param(
            "from asyncio import subprocess\nsubprocess.create_subprocess_exec(c)",
            ["asyncio.create_subprocess_exec"],
            id="asyncio-subprocess-module",
        ),
        pytest.param(
            "from asyncio import subprocess as sp\nsp.create_subprocess_shell(c)",
            ["asyncio.create_subprocess_shell"],
            id="asyncio-subprocess-module-alias",
        ),
        pytest.param(
            "from concurrent.futures import process\nprocess.ProcessPoolExecutor()",
            ["concurrent.ProcessPoolExecutor"],
            id="futures-process-module",
        ),
        pytest.param(
            "from concurrent.futures import process as p\np.ProcessPoolExecutor()",
            ["concurrent.ProcessPoolExecutor"],
            id="futures-process-module-alias",
        ),
        pytest.param(
            'import subprocess\nvars(subprocess)["run"](c)',
            ["vars(subprocess)"],
            id="vars-subprocess",
        ),
        pytest.param(
            'import os as o\nvars(o)["system"](c)', ["vars(os)"], id="vars-os-alias"
        ),
        pytest.param(
            'import sys\nsys.modules["subprocess"].run(c)',
            ["sys.modules[subprocess]"],
            id="sys-modules",
        ),
        pytest.param(
            'import sys\nsys.modules["os.path"]',
            ["sys.modules[os]"],
            id="sys-modules-dotted",
        ),
        pytest.param(
            'from sys import modules\nmodules["pty"].spawn(c)',
            ["sys.modules[pty]"],
            id="sys-modules-imported",
        ),
        pytest.param(
            'import sys\nsys.modules.get("subprocess").run(c)',
            ["sys.modules[subprocess]"],
            id="sys-modules-get",
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
        pytest.param('getattr(thing, "run")', id="getattr-unwatched"),
        pytest.param("vars(thing)", id="vars-unwatched"),
        pytest.param('import sys\nsys.modules["json"]', id="sys-modules-unwatched"),
        pytest.param(
            "from asyncio import subprocess\nsubprocess.PIPE", id="asyncio-pipe"
        ),
        pytest.param(
            "from concurrent.futures import process\nprocess.BrokenProcessPool",
            id="futures-process-error",
        ),
        pytest.param(
            "def import_module(n): ...\nimport_module('x')", id="own-function"
        ),
    ],
)
def test_the_scan_allows_the_types_and_unrelated_calls(source: str) -> None:
    assert SpawnScan.of_source(source).spawning_names() == []


def test_the_scan_follows_imports_inside_the_package() -> None:
    reached = {path.name for path in SpawnScan.reachable_from(_PACKAGE / "release.py")}
    assert {"release.py", "pr_merge.py", "timeouts.py", "detect.py"} <= reached


def _release_modules() -> list[Path]:
    """Every module on the release path: the CLI's ``release`` command and below."""
    cli = SpawnScan.reachable_from(_PACKAGE / "__main__.py", entry_point="release")
    return sorted({*cli, *SpawnScan.reachable_from(_PACKAGE / "release.py")})


def test_the_release_command_reaches_release_py() -> None:
    assert _PACKAGE / "release.py" in SpawnScan.reachable_from(
        _PACKAGE / "__main__.py", entry_point="release"
    )


def test_the_release_command_does_not_pull_in_other_commands() -> None:
    reached = {
        p.name
        for p in SpawnScan.reachable_from(
            _PACKAGE / "__main__.py", entry_point="release"
        )
    }
    assert "audit.py" not in reached


def test_only_run_spawns_a_release_process() -> None:
    """Across the release path, the one spawn site is ``CommandRunner.run``."""
    sites = {
        (str(path.relative_to(_PACKAGE)), function)
        for path in _release_modules()
        for _name, function in SpawnScan.of_file(path).spawn_sites()
    }
    assert sites == {("phases/shared/command_runner.py", "run")}


def test_a_second_spawn_site_in_the_same_file_is_reported() -> None:
    source = (
        "import subprocess\n"
        "def _run(c):\n    return subprocess.run(c)\n"
        "def sneaky(c):\n    return subprocess.Popen(c)\n"
    )
    assert SpawnScan.of_source(source).spawn_sites() == [
        ("subprocess.Popen", "sneaky"),
        ("subprocess.run", "_run"),
    ]


def test_a_spawn_at_module_level_is_reported_as_such() -> None:
    sites = SpawnScan.of_source("import os\nos.system('x')").spawn_sites()
    assert sites == [("os.system", "<module>")]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from . import helper", id="dot-import"),
        pytest.param("from .shared import gh", id="dot-module"),
        pytest.param("from ..phases import x", id="two-dots"),
    ],
)
def test_a_relative_import_fails_the_scan_instead_of_hiding_a_module(
    source: str,
) -> None:
    with pytest.raises(ValueError, match="relative import"):
        SpawnScan.of_source(source)


@pytest.mark.parametrize(
    ("source", "found"),
    [
        pytest.param(
            "from concurrent.futures import ProcessPoolExecutor",
            ["concurrent.ProcessPoolExecutor"],
            id="from-import",
        ),
        pytest.param(
            "import concurrent.futures\nconcurrent.futures.ProcessPoolExecutor()",
            ["concurrent.ProcessPoolExecutor"],
            id="dotted",
        ),
        pytest.param(
            "import concurrent.futures as cf\ncf.ProcessPoolExecutor()",
            ["concurrent.ProcessPoolExecutor"],
            id="alias",
        ),
        pytest.param(
            "from concurrent import futures\nfutures.ProcessPoolExecutor()",
            ["concurrent.ProcessPoolExecutor"],
            id="from-concurrent",
        ),
        pytest.param(
            "import multiprocessing as mp\nmp.Pool(2)",
            ["multiprocessing.Pool"],
            id="multiprocessing-pool",
        ),
    ],
)
def test_the_scan_catches_process_pools(source: str, found: list[str]) -> None:
    assert SpawnScan.of_source(source).spawning_names() == found


def test_a_thread_pool_is_not_a_process() -> None:
    source = "from concurrent.futures import ThreadPoolExecutor, Future"
    assert SpawnScan.of_source(source).spawning_names() == []


def test_every_phase_module_is_reached_so_none_goes_unscanned() -> None:
    """A phase loaded dynamically would not be followed by imports, so pin them."""
    reached = set(SpawnScan.reachable_from(_PACKAGE / "release.py"))
    phases = set((_PACKAGE / "phases").rglob("*.py"))
    assert phases - reached == set()
