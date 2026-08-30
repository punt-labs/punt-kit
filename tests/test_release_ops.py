"""Tests for the ReleaseOps adapter — the phases/ package's testability seam."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from punt_kit import release
from punt_kit.phases.shared.ops import ReleaseOps

if TYPE_CHECKING:
    import pytest


def test_release_ops_adapter_satisfies_protocol() -> None:
    ops: ReleaseOps = release._ops  # pyright: ignore[reportPrivateUsage]
    assert isinstance(ops, ReleaseOps)


def test_release_ops_run_reaches_monkeypatched_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """monkeypatch.setattr(release_mod, "_run", ...) must reach _ops.run.

    This is the mechanism every phases/* collaborator depends on: forwarding
    through release.py's own globals means a test patching release._run
    intercepts calls made via the ReleaseOps adapter too.
    """
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr(release, "_run", fake_run)  # pyright: ignore[reportPrivateUsage]

    result = release._ops.run(["echo", "hi"])  # pyright: ignore[reportPrivateUsage]

    assert calls == [["echo", "hi"]]
    assert result.stdout == "ok"


def test_release_ops_report_methods_reach_monkeypatched_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    def fake_ok(msg: str) -> None:
        seen["ok"] = msg

    def fake_info(msg: str) -> None:
        seen["info"] = msg

    def fake_dry(msg: str) -> None:
        seen["dry"] = msg

    def fake_warn(msg: str) -> None:
        seen["warn"] = msg

    monkeypatch.setattr(release, "_ok", fake_ok)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(release, "_info", fake_info)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(release, "_dry", fake_dry)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(release, "_warn", fake_warn)  # pyright: ignore[reportPrivateUsage]

    release._ops.ok("a")  # pyright: ignore[reportPrivateUsage]
    release._ops.info("b")  # pyright: ignore[reportPrivateUsage]
    release._ops.dry("c")  # pyright: ignore[reportPrivateUsage]
    release._ops.warn("d")  # pyright: ignore[reportPrivateUsage]

    assert seen == {"ok": "a", "info": "b", "dry": "c", "warn": "d"}


def test_release_ops_fail_reaches_monkeypatched_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fail(msg: str) -> None:
        raise release.ReleaseError(f"patched: {msg}")

    monkeypatch.setattr(release, "_fail", fake_fail)  # pyright: ignore[reportPrivateUsage]

    try:
        release._ops.fail("boom")  # pyright: ignore[reportPrivateUsage]
    except release.ReleaseError as exc:
        assert str(exc) == "patched: boom"
    else:
        raise AssertionError("expected ReleaseError")
