"""Exercise the handoff runtime installer without a release or network."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path(".punt-labs/ethos/checks/snapshots/punt-kit.yaml")
INSTALLER = Path("scripts/install-handoff-runtime.sh")
ARCHIVE = b"fixture runtime archive"
SHA256 = hashlib.sha256(ARCHIVE).hexdigest()

pytestmark = pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="Linux x86-64 handoff runtime",
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / INSTALLER).parent.mkdir(parents=True)
    (root / PROFILE).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / INSTALLER, root / INSTALLER)
    pin = json.loads((ROOT / PROFILE).read_text())
    pin["checks"]["full-gate"]["runtime"]["platforms"]["linux-amd64"]["sha256"] = SHA256
    (root / PROFILE).write_text(json.dumps(pin))
    return root


def _install(
    checkout: Path, home: Path, *args: str | Path, bin_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    path = "/usr/local/bin:/usr/bin:/bin"
    if bin_dir is not None:
        path = f"{bin_dir}:{path}"
    return subprocess.run(
        ["bash", str(checkout / INSTALLER), *(str(arg) for arg in args)],
        env={"HOME": str(home), "PATH": path},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_installer_help_does_not_write(
    checkout: Path, tmp_path: Path, flag: str
) -> None:
    result = _install(checkout, tmp_path, flag)
    assert result.returncode == 0
    assert "usage" in result.stdout
    assert not (tmp_path / ".punt-labs").exists()


def test_installer_rejects_unknown_flags(checkout: Path, tmp_path: Path) -> None:
    result = _install(checkout, tmp_path, "--unknown")
    assert result.returncode == 2
    assert "usage" in result.stderr
    assert not (tmp_path / ".punt-labs").exists()


def test_installer_previews_without_arguments(checkout: Path, tmp_path: Path) -> None:
    profile = json.loads((checkout / PROFILE).read_text())
    pin = profile["checks"]["full-gate"]["runtime"]["platforms"]["linux-amd64"]
    sha = pin["sha256"]
    result = _install(checkout, tmp_path)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"Bundle: {pin['bundle']}",
        f"URL: {pin['url']}",
        f"SHA-256: {sha}",
        f"Destination: {tmp_path}/.punt-labs/ethos/runtimes/{sha}.tar.gz",
        "Use --apply to install this runtime.",
    ]
    assert not (tmp_path / ".punt-labs").exists()


def test_installer_applies_download(checkout: Path, tmp_path: Path) -> None:
    curl = tmp_path / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        "while [[ $1 != --output ]]; do shift; done\n"
        f"printf '%s' '{ARCHIVE.decode()}' > \"$2\"\n"
    )
    curl.chmod(0o755)
    result = _install(checkout, tmp_path, "--apply", bin_dir=tmp_path)
    assert result.returncode == 0, result.stderr
    installed = tmp_path / ".punt-labs/ethos/runtimes" / f"{SHA256}.tar.gz"
    assert installed.read_bytes() == ARCHIVE


def test_installs_and_reuses_verified_archive(checkout: Path, tmp_path: Path) -> None:
    source = tmp_path / "source.tar.gz"
    source.write_bytes(ARCHIVE)
    result = _install(checkout, tmp_path, source)
    assert result.returncode == 0, result.stderr
    installed = tmp_path / ".punt-labs/ethos/runtimes" / f"{SHA256}.tar.gz"
    assert result.stdout.strip() == str(installed)
    assert installed.read_bytes() == ARCHIVE
    source.unlink()
    assert _install(checkout, tmp_path, source).returncode == 0


@pytest.mark.parametrize("contents", [b"", b"wrong archive"])
def test_rejects_wrong_digest(checkout: Path, tmp_path: Path, contents: bytes) -> None:
    source = tmp_path / "source.tar.gz"
    source.write_bytes(contents)
    result = _install(checkout, tmp_path, source)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not list((tmp_path / ".punt-labs/ethos/runtimes").iterdir())


def test_rejects_symlink_store(checkout: Path, tmp_path: Path) -> None:
    store = tmp_path / ".punt-labs/ethos/runtimes"
    store.parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.mkdir()
    store.symlink_to(target, target_is_directory=True)
    result = _install(checkout, tmp_path, tmp_path / "unused")
    assert result.returncode != 0
    assert "not a symlink" in result.stderr
    assert not list(target.iterdir())


def test_rejects_mismatched_release_version(checkout: Path, tmp_path: Path) -> None:
    pin = checkout / PROFILE
    pin.write_text(pin.read_text().replace("/handoff-runtime-v", "/handoff-runtime-v9"))
    result = _install(checkout, tmp_path, tmp_path / "unused")
    assert result.returncode != 0
    assert "Invalid punt-kit snapshot runtime pin" in result.stderr
    assert not (tmp_path / ".punt-labs").exists()


def test_builder_requires_an_output_directory() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/build-handoff-runtime.sh")],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 2
    assert "OUTPUT_DIRECTORY" in result.stderr
