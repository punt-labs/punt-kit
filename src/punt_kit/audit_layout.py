"""The `.punt-labs/` layout findings of `punt audit` (punt-labs-dir.md § 8).

Verdicts come from git, not from reading `.gitignore`: `git check-ignore`
probes decide whether the canonical block behaves, `git ls-files` decides what
is tracked and what is ignored. The block's text is read only to explain a
failed probe. Every path the checks grade comes from the § 9 migration tables
in :mod:`punt_kit.adoption_table`.

Not implemented: the seal-manifest check ("No unsanctioned live state"), which
depends on an ethos seal-manifest format this package does not read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from punt_kit.adoption_table import MIGRATION_TABLE, RowKind
from punt_kit.audit_verdict import FAIL, PASS

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo

    Finding = tuple[str, str, str]

WARN = "[yellow]![/yellow]"

CANONICAL_BLOCK = (
    ".punt-labs/**/local",
    ".punt-labs/**/local/**",
    ".punt-labs/**/*.local",
    ".punt-labs/**/*.local.*",
)
ROOT_SENTINELS = (".biff", ".vox", ".lux", ".ethos", ".quarry.toml")
LOCAL_ZONE = "local"
NAMED_EXCEPTION = "ethos.yaml"

# Set (a) of the gitignore probe, per present tool: (relative path, must be ignored).
_TOOL_PROBES = (
    ("{tool}/CLAUDE.md", False),
    ("{tool}/config.yaml", False),
    ("{tool}/local/x", True),
    ("{tool}/foo.local", True),
    ("{tool}/config.local.yaml", True),
    ("{tool}/locales/en.yaml", False),
    ("{tool}/config.locales.yaml", False),
    ("local/{tool}/x", True),
)


def _is_local_convention(path: str) -> bool:
    """True when a path segment is exactly ``local``, ends in ``.local``, or
    carries ``.local.`` inside it — the boundary-aware forms of § 4, never a
    substring scan, so ``locales/`` and ``config.locales.yaml`` stay shared."""
    return any(
        segment == LOCAL_ZONE or segment.endswith(".local") or ".local." in segment
        for segment in path.strip("/").split("/")
    )


@final
class GitignoreText:
    """The root ``.gitignore`` as patterns, for diagnostics only."""

    __slots__ = ("_patterns",)

    _patterns: tuple[tuple[int, str], ...]

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._patterns = tuple(
            (number, line.strip())
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip() and not line.lstrip().startswith("#")
        )
        return self

    @property
    def deny_all(self) -> bool:
        return bool(self._patterns) and self._patterns[0][1] in {"*", "/*"}

    def punt_labs_excludes(self) -> tuple[tuple[int, str], ...]:
        """Every non-negated pattern under ``.punt-labs/``, with its line number."""
        return tuple(
            (number, pattern)
            for number, pattern in self._patterns
            if pattern.startswith(".punt-labs/")
        )

    def diagnostic(self) -> str:
        """Why a probe may have failed, from the block's text; ``""`` if no clue."""
        patterns = [pattern for _, pattern in self._patterns]
        missing = [line for line in CANONICAL_BLOCK if line not in patterns]
        if len(missing) == len(CANONICAL_BLOCK):
            return "canonical block missing from .gitignore"
        notes: list[str] = []
        if missing:
            note = "canonical block lacks " + ", ".join(missing)
            if any(pattern.endswith("*.local*") for pattern in patterns):
                note += (
                    "; a *.local* glob anchors only the leading boundary:"
                    " the block needs *.local and *.local.* as two lines"
                )
            notes.append(note)
        if self.deny_all and not self._reincludes_bare_directory(patterns):
            notes.append(
                "deny-all .gitignore lacks the bare-directory line !.punt-labs/"
                " before !.punt-labs/**"
            )
        return "; ".join(notes)

    @staticmethod
    def _reincludes_bare_directory(patterns: list[str]) -> bool:
        if "!.punt-labs/" not in patterns:
            return False
        if "!.punt-labs/**" not in patterns:
            return True
        return patterns.index("!.punt-labs/") < patterns.index("!.punt-labs/**")


@final
class LayoutAudit:
    """Checks a repository's ``.punt-labs/`` layout against punt-labs-dir.md § 8."""

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, info: ProjectInfo) -> Self:
        self = super().__new__(cls)
        self._root = info.root
        return self

    def findings(self) -> list[Finding]:
        """Every layout finding; the root-sentinel check runs even outside git."""
        if not self._is_git_root() or not (self._root / ".punt-labs").is_dir():
            return [self._root_sentinel_finding()]
        return [
            self._gitignore_finding(),
            self._tracked_local_finding(),
            self._ignored_shared_finding(),
            self._root_sentinel_finding(),
            *self._live_state_findings(),
            self._interim_exclude_finding(),
            *self._bare_file_findings(),
        ]

    # --- git ---------------------------------------------------------------

    def _git(self, *args: str, stdin: bytes = b"") -> bytes:
        return subprocess.run(
            ["git", *args],
            cwd=str(self._root),
            input=stdin,
            capture_output=True,
            check=False,
        ).stdout

    def _is_git_root(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(self._root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return self._root.resolve() == Path(result.stdout.strip()).resolve()

    def _ls_files(self, *args: str) -> list[str]:
        out = self._git("ls-files", "-z", *args, "--", ".punt-labs")
        return [entry.decode() for entry in out.split(b"\0") if entry]

    def _check_ignore(self, paths: list[str]) -> dict[str, str]:
        """Each path to the ``source:line:pattern`` that ignores it, or ``""``.

        Asked against the real index on purpose: a force-added local-convention
        file is tracked, so git reports it not ignored, and the probe fails
        exactly as the standard intends. With ``-v`` git also reports a path
        re-included by a ``!`` pattern; that path is not ignored.
        """
        args = ["check-ignore", "-v", "-n", "-z", "--stdin"]
        out = self._git(*args, stdin=b"\0".join(p.encode() for p in paths))
        fields = out.split(b"\0")
        verdicts: dict[str, str] = {}
        for i in range(0, len(fields) - 3, 4):
            source, line, pattern, path = (f.decode() for f in fields[i : i + 4])
            ignored = bool(source) and not pattern.startswith("!")
            verdicts[path] = f"{source}:{line}:{pattern}" if ignored else ""
        return verdicts

    # --- the checks ----------------------------------------------------------

    def _gitignore_finding(self) -> Finding:
        label = "Gitignore behaves correctly"
        tools = sorted(
            entry.name
            for entry in (self._root / ".punt-labs").iterdir()
            if entry.is_dir() and entry.name != LOCAL_ZONE
        )
        probes = [
            (f".punt-labs/{template.format(tool=tool)}", ignored)
            for tool in tools
            for template, ignored in _TOOL_PROBES
        ]
        live = MIGRATION_TABLE.live_paths()
        probes.extend((path, True) for path in live)
        verdicts = self._check_ignore([path for path, _ in probes])
        tracked = set(self._ls_files())
        failures = [
            self._probe_failure(path, ignored, verdicts[path], tracked=path in tracked)
            for path, ignored in probes
            if bool(verdicts[path]) != ignored
        ]
        if not failures:
            summary = f"{len(tools)} tool(s), {len(live)} interim path(s)"
            return (PASS, label, f"{len(probes)} probes: {summary}")
        detail = "; ".join(failures)
        if diagnostic := self._gitignore().diagnostic():
            detail += f" — {diagnostic}"
        return (FAIL, label, detail)

    @staticmethod
    def _probe_failure(path: str, ignored: bool, why: str, *, tracked: bool) -> str:
        if not ignored:
            return f"{path} should not be ignored ({why})"
        if tracked:
            return f"{path} should be ignored (git-tracked)"
        return f"{path} should be ignored"

    def _gitignore(self) -> GitignoreText:
        path = self._root / ".gitignore"
        return GitignoreText(path.read_text(encoding="utf-8") if path.is_file() else "")

    def _tracked_local_finding(self) -> Finding:
        label = "No tracked local-convention path"
        tracked = self._ls_files()
        offenders = sorted(path for path in tracked if _is_local_convention(path))
        if offenders:
            return (FAIL, label, "Tracked: " + ", ".join(offenders))
        return (PASS, label, f"{len(tracked)} tracked path(s) under .punt-labs/")

    def _ignored_shared_finding(self) -> Finding:
        label = "No gitignored non-local-convention path"
        live = MIGRATION_TABLE.live_paths()
        ignored = self._ls_files("--others", "--ignored", "--exclude-standard")
        offenders = sorted(
            path
            for path in ignored
            if not _is_local_convention(path) and not path.startswith(live)
        )
        if not offenders:
            return (PASS, label, "")
        why = self._check_ignore(offenders)
        return (
            FAIL,
            label,
            "Ignored: " + ", ".join(f"{p} ({why[p]})" for p in offenders),
        )

    def _root_sentinel_finding(self) -> Finding:
        label = "No legacy root sentinel"
        present = [name for name in ROOT_SENTINELS if (self._root / name).exists()]
        if not present:
            return (PASS, label, "")
        graded = [self._sentinel_grade(name) for name in present]
        status = FAIL if any(s == FAIL for s, _ in graded) else WARN
        return (status, label, "; ".join(detail for _, detail in graded))

    def _sentinel_grade(self, name: str) -> tuple[str, str]:
        rows = MIGRATION_TABLE.rows_naming_sentinel(name)
        if not rows:
            return (FAIL, f"{name} — no § 9 row names it")
        existing = [r for r in rows if (self._root / r.path_naming(name)).exists()]
        row = existing[0] if existing else rows[0]
        if not row.migrates:
            return (FAIL, f"{name} — a stray, not a sentinel (§ 9.1: no migration)")
        destination = row.destination or "delete"
        return (
            WARN,
            f"{name} — migration pending"
            f" (§ {row.section} {row.path_naming(name)} → {destination})",
        )

    def _live_state_findings(self) -> list[Finding]:
        label = "Live-state migration pending"
        findings: list[Finding] = []
        for row in MIGRATION_TABLE.rows_of(RowKind.LIVE_STATE):
            for path in row.paths:
                count = len(self._git("ls-files", "-z", "--", path).split(b"\0")) - 1
                if count:
                    findings.append(
                        (
                            WARN,
                            label,
                            f"{path} is git-tracked ({count} file) — migration"
                            f" pending (§ {row.section} → {row.destination})",
                        )
                    )
        if findings:
            return findings
        return [(PASS, label, "no § 9.4 live path is git-tracked")]

    def _interim_exclude_finding(self) -> Finding:
        label = "No interim exclude survives a completed migration"
        live = {path.rstrip("/") for path in MIGRATION_TABLE.live_paths()}
        backed: list[str] = []
        stale: list[str] = []
        for number, pattern in self._gitignore().punt_labs_excludes():
            if pattern in CANONICAL_BLOCK or _is_local_convention(pattern):
                continue
            if pattern.rstrip("/") in live:
                backed.append(pattern)
            else:
                stale.append(f"{pattern} (.gitignore:{number})")
        if stale:
            detail = "Stale: " + ", ".join(stale) + " — no § 9.4 row names these paths"
            return (FAIL, label, detail)
        return (
            PASS,
            label,
            f"{len(backed)} interim exclude(s), each named by a § 9.4 row",
        )

    def _bare_file_findings(self) -> list[Finding]:
        label = "No bare file under .punt-labs/"
        findings: list[Finding] = []
        for entry in sorted((self._root / ".punt-labs").iterdir()):
            rel = f".punt-labs/{entry.name}"
            if entry.name == LOCAL_ZONE:
                if not entry.is_dir():
                    findings.append(
                        (
                            FAIL,
                            label,
                            f"{rel} is not a directory — it blocks the local zone",
                        )
                    )
                continue
            if entry.is_dir() or entry.name == NAMED_EXCEPTION:
                continue
            row = MIGRATION_TABLE.row_naming_path(RowKind.BARE_FILE, rel)
            if row is None:
                findings.append((FAIL, label, f"{rel} — no § 9 row names it"))
            else:
                pending = f"migration pending (§ {row.section} → {row.destination})"
                findings.append((WARN, label, f"{rel} — {pending}"))
        return findings or [(PASS, label, "")]
