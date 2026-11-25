"""Select repository inputs, scan them, and report the results."""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Self

from rich.console import Console
from rich.markup import escape

from punt_kit.errors import CommandFailure, ReleaseError
from punt_kit.pii import ConfigSource, compile_allow_patterns
from punt_kit.pii_matcher import Finding, PiiConfig, PiiMatcher, ScanSource

console = Console()


class CheckoutScan:
    """Select worktree or index inputs, then report one scan."""

    _root: Path
    _staged: bool
    _config: PiiConfig
    _files_scanned: int
    _findings: list[Finding]

    def __new__(cls, root: Path, staged: bool, config: str | None) -> Self:
        """Bind repository, input source, and configured rules for one scan."""
        self = super().__new__(cls)
        self._root = root
        self._staged = staged
        source = ConfigSource(root, index_blob=self._index_config if staged else None)
        self._config = source.load(config)
        self._files_scanned = 0
        self._findings = []
        return self

    def run(self) -> dict[str, object]:
        """Scan selected files and return metadata without raw matches."""
        matcher = PiiMatcher(
            self._config, compile_allow_patterns(self._config.allow_patterns)
        )
        for path in self._included_paths():
            if (source := self._source(path)) is not None:
                self._files_scanned += 1
                self._findings.extend(matcher.scan(source))
        self._print_result()
        result = self._result()
        if self._findings:
            raise CommandFailure(f"{len(self._findings)} PII finding(s)", result)
        return result

    def _included_paths(self) -> list[str]:
        return [
            path
            for path in dict.fromkeys(self._files())
            if not any(
                fnmatch.fnmatch(path, rule) for rule in self._config.ignore_files
            )
        ]

    def _source(self, path: str) -> ScanSource | None:
        if self._staged:
            return self._index_source(path)
        return self._worktree_source(path)

    def _worktree_source(self, path: str) -> ScanSource | None:
        try:
            return self._read_worktree(path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ReleaseError(f"Cannot scan {path}: {exc.strerror}") from exc

    def _read_worktree(self, path: str) -> ScanSource | None:
        full_path = self._root / path
        if full_path.is_symlink():
            return ScanSource(path, os.readlink(full_path))
        if not full_path.is_file():
            return None
        text = self._read_text(full_path)
        return None if text is None else ScanSource(path, text)

    @staticmethod
    def _read_text(path: Path) -> str | None:
        with path.open("rb") as stream:
            head = stream.read(8192)
            if b"\0" in head:
                return None
            return (head + stream.read()).decode(errors="replace")

    def _index_source(self, path: str) -> ScanSource | None:
        blob = self._git(["show", f":./{path}"])
        if b"\0" in blob[:8192]:
            return None
        return ScanSource(path, blob.decode(errors="replace"))

    def _index_config(self, path: str) -> bytes | None:
        entries = self._git(["ls-files", "--stage", "-z", "--", path])
        if not entries:
            return None
        if entries.count(b"\0") != 1 or entries.split()[0] not in {
            b"100644",
            b"100755",
        }:
            raise ReleaseError(f"Staged {path} must be a single regular file")
        return self._git(["show", f":./{path}"])

    def _staged_files(self) -> list[str]:
        data = self._git(
            ["diff", "--cached", "--raw", "--no-renames", "--relative", "-z"]
        )
        return [
            path.decode(errors="surrogateescape")
            for header, path in self._staged_entries(data)
            if header.split()[1] in {b"100644", b"100755", b"120000"}
        ]

    @staticmethod
    def _staged_entries(data: bytes) -> list[tuple[bytes, bytes]]:
        entries = data.split(b"\0")
        if entries.pop() or len(entries) % 2:
            raise ReleaseError("Git returned an incomplete staged file list")
        return list(zip(entries[0::2], entries[1::2], strict=True))

    def _files(self) -> list[str]:
        if self._staged:
            return self._staged_files()
        return [
            path
            for path in self._git(["ls-files", "-z"])
            .decode(errors="surrogateescape")
            .split("\0")
            if path
        ]

    def _git(self, args: list[str]) -> bytes:
        """Read git data; never report a failed git scan as a clean result."""
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self._root,
                capture_output=True,
                check=True,
                timeout=10,
            ).stdout
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.decode(errors="replace").strip()
            raise ReleaseError(
                message or f"git {args[0]} failed ({exc.returncode})"
            ) from exc
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ReleaseError(f"Unable to read git data: {exc}") from exc

    def _result(self) -> dict[str, object]:
        return {
            "staged": self._staged,
            "files_scanned": self._files_scanned,
            "findings": [
                {"file": f.file, "line": f.line, "category": f.category}
                for f in self._findings
            ],
        }

    def _print_result(self) -> None:
        mode = "--staged" if self._staged else "all tracked"
        console.print(
            f"\n[bold]punt repo scan-pii[/bold] — {escape(self._root.name)} ({mode})"
        )
        if not self._files_scanned:
            console.print("  No files to scan.\n")
            return

        if not self._findings:
            console.print(
                f"  [green]✓[/green] Clean — {self._files_scanned} file(s) scanned,"
                " no PII found.\n"
            )
            return

        self._print_findings()

        self._print_hook_hint()

    def _print_hook_hint(self) -> None:
        if self._staged:
            console.print("  [dim]Commit blocked. Fix findings and re-stage.[/dim]\n")
        else:
            console.print(
                "  [dim]Tip: Add as pre-commit hook:[/dim]\n"
                "  [dim]  echo 'punt repo scan-pii --staged || exit 1'"
                " >> .git/hooks/pre-commit[/dim]\n"
            )

    def _print_findings(self) -> None:
        by_file: dict[str, list[Finding]] = {}
        for f in self._findings:
            by_file.setdefault(f.file, []).append(f)

        for file_path, file_findings in sorted(by_file.items()):
            console.print(f"\n  [bold]{escape(file_path)}[/bold]")
            for f in file_findings:
                console.print(
                    f"    [red]✗[/red] line {f.line}: \\[{f.category}] "
                    f"{escape(f.match)}"
                )

        console.print(
            f"\n  [red]{len(self._findings)} finding(s)[/red]"
            f" in {len(by_file)} file(s)"
            f" ({self._files_scanned} scanned)\n"
        )


def run_pii(
    path: str,
    *,
    staged: bool = False,
    config: str | None = None,
) -> dict[str, object]:
    """Scan checkout files and report any configured PII matches."""
    root = Path(path).resolve()
    if not root.is_dir():
        message = f"{root} is not a directory"
        console.print(f"[red]Error:[/red] {escape(message)}")
        raise CommandFailure(message)
    try:
        scan = CheckoutScan(root, staged, config)
        return scan.run()
    except ReleaseError as exc:
        console.print(f"[red]Error:[/red] {escape(str(exc))}")
        raise CommandFailure(str(exc)) from exc
