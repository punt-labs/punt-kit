"""punt pii — scan repository for personally identifiable information."""

from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from rich.console import Console

console = Console()

# ---------------------------------------------------------------------------
# Built-in patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
)

_HOME_PATH_RE = re.compile(
    r"(?:/Users/|/home/)[\w.-]+/",
)

_HOSTNAME_RE = re.compile(
    r"\b[\w.-]+@[\w][\w-]*\.local\b",
)

# Emails that are never flagged.
_BUILTIN_ALLOW_EMAILS: set[str] = {
    "noreply@github.com",
    "noreply@anthropic.com",
    # SSH URL prefixes (not actual emails)
    "git@github.com",
    "git@gitlab.com",
    "git@bitbucket.org",
}

_BUILTIN_ALLOW_EMAIL_SUFFIXES: tuple[str, ...] = (
    "@users.noreply.github.com",
    "@example.com",
    "@example.org",
    "@example.net",
)

# Path prefixes that are never flagged (CI runners).
_BUILTIN_ALLOW_PATHS: tuple[str, ...] = (
    "/home/runner/",
    "/Users/runner/",
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PiiConfig:
    """User-configurable PII scanning settings."""

    allow_emails: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    allow_patterns: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    deny: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    ignore_files: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


@dataclass(frozen=True)
class Finding:
    """A single PII match in a file."""

    file: str
    line: int
    category: str  # "email", "path", "hostname", "deny"
    match: str


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(root: Path, config_path: str | None = None) -> PiiConfig:
    """Load PII config from pyproject.toml or .punt-pii.toml."""
    if config_path is not None:
        p = Path(config_path)
        if p.exists():
            return _parse_toml_config(p)
        console.print(f"[yellow]Warning:[/yellow] config not found: {config_path}")
        return PiiConfig()

    # Try pyproject.toml first
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        pii_section = _drill(data, "tool", "punt", "pii")
        if pii_section is not None:
            return _config_from_dict(pii_section)

    # Fallback to standalone file
    standalone = root / ".punt-pii.toml"
    if standalone.exists():
        return _parse_toml_config(standalone)

    return PiiConfig()


def _parse_toml_config(path: Path) -> PiiConfig:
    """Parse a standalone .punt-pii.toml file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _config_from_dict(data)


def _config_from_dict(data: dict[str, object]) -> PiiConfig:
    """Build PiiConfig from a dict (either pyproject section or standalone)."""
    return PiiConfig(
        allow_emails=_str_list(data.get("allow_emails")),
        allow_patterns=_str_list(data.get("allow_patterns")),
        deny=_str_list(data.get("deny")),
        ignore_files=_str_list(data.get("ignore_files")),
    )


def _str_list(val: object) -> list[str]:
    """Coerce a value to a list of strings."""
    if isinstance(val, list):
        return [str(x) for x in cast("list[object]", val)]
    return []


def _drill(data: dict[str, object], *keys: str) -> dict[str, object] | None:
    """Walk nested dicts by key sequence, returning None if any key is missing."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    if isinstance(current, dict):
        return cast("dict[str, object]", current)
    return None


# ---------------------------------------------------------------------------
# File enumeration
# ---------------------------------------------------------------------------


def get_files(root: Path, *, staged: bool) -> list[str]:
    """List files to scan, relative to root."""
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=d"]
    else:
        cmd = ["git", "ls-files"]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, OSError):
        return []


def is_binary(path: Path) -> bool:
    """Check if a file is binary by looking for null bytes in the first 8KB."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_file(
    rel_path: str,
    root: Path,
    config: PiiConfig,
) -> list[Finding]:
    """Scan a single file for PII. Returns findings."""
    full_path = root / rel_path

    if not full_path.is_file() or is_binary(full_path):
        return []

    try:
        content = full_path.read_text(errors="replace")
    except OSError:
        return []

    findings: list[Finding] = []
    allow_email_set = _BUILTIN_ALLOW_EMAILS | set(config.allow_emails)
    allow_regexes = [re.compile(p) for p in config.allow_patterns]

    for line_num, line in enumerate(content.splitlines(), start=1):
        # --- Email detector ---
        for m in _EMAIL_RE.finditer(line):
            email = m.group()
            # Skip .local addresses — those are hostnames, not emails
            if email.endswith(".local"):
                continue
            if email in allow_email_set:
                continue
            if any(email.endswith(suffix) for suffix in _BUILTIN_ALLOW_EMAIL_SUFFIXES):
                continue
            if _suppressed(email, allow_regexes):
                continue
            findings.append(Finding(rel_path, line_num, "email", email))

        # --- Home path detector ---
        for m in _HOME_PATH_RE.finditer(line):
            path_match = m.group()
            if any(path_match.startswith(ap) for ap in _BUILTIN_ALLOW_PATHS):
                continue
            if _suppressed(path_match, allow_regexes):
                continue
            findings.append(Finding(rel_path, line_num, "path", path_match))

        # --- Hostname detector ---
        for m in _HOSTNAME_RE.finditer(line):
            hostname = m.group()
            if _suppressed(hostname, allow_regexes):
                continue
            findings.append(Finding(rel_path, line_num, "hostname", hostname))

        # --- Custom deny patterns ---
        for pattern in config.deny:
            if pattern in line:
                if _suppressed(pattern, allow_regexes):
                    continue
                findings.append(Finding(rel_path, line_num, "deny", pattern))

    return findings


def _suppressed(text: str, allow_regexes: list[re.Pattern[str]]) -> bool:
    """Check if a match is suppressed by an allow_patterns regex."""
    return any(r.search(text) for r in allow_regexes)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_pii(
    path: str,
    *,
    staged: bool = False,
    config: str | None = None,
) -> None:
    """Scan repository for personally identifiable information."""
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    cfg = load_config(root, config)
    mode = "--staged" if staged else "all tracked"
    console.print(f"\n[bold]punt pii[/bold] — {root.name} ({mode})")

    files = get_files(root, staged=staged)
    if not files:
        console.print("  No files to scan.\n")
        return

    # Filter by ignore_files globs
    if cfg.ignore_files:
        files = [
            f for f in files if not any(fnmatch.fnmatch(f, g) for g in cfg.ignore_files)
        ]

    all_findings: list[Finding] = []
    for rel_path in files:
        all_findings.extend(scan_file(rel_path, root, cfg))

    if not all_findings:
        console.print(
            f"  [green]✓[/green] Clean — {len(files)} file(s) scanned, no PII found.\n"
        )
        return

    # Group by file
    by_file: dict[str, list[Finding]] = {}
    for f in all_findings:
        by_file.setdefault(f.file, []).append(f)

    for file_path, file_findings in sorted(by_file.items()):
        console.print(f"\n  [bold]{file_path}[/bold]")
        for f in file_findings:
            console.print(f"    [red]✗[/red] line {f.line}: [{f.category}] {f.match}")

    console.print(
        f"\n  [red]{len(all_findings)} finding(s)[/red]"
        f" in {len(by_file)} file(s)"
        f" ({len(files)} scanned)\n"
    )

    if staged:
        console.print("  [dim]Commit blocked. Fix findings and re-stage.[/dim]\n")
    else:
        console.print(
            "  [dim]Tip: Add as pre-commit hook:[/dim]\n"
            "  [dim]  echo 'punt pii --staged || exit 1'"
            " >> .git/hooks/pre-commit[/dim]\n"
        )

    raise SystemExit(1)
