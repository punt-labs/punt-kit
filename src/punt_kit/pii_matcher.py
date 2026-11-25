"""Apply compiled PII rules to text independently of checkout I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

from punt_kit.phases.shared.errors import ReleaseError

if TYPE_CHECKING:
    from collections.abc import Generator


# One pass finds emails and ``.local`` hostnames. A JSON escape (``\\n``,
# ``\\u003c``) is consumed whole, so no address starts at its letter; a domain
# checks for another address once before splitting a hyphen-glued local part.
# Runs that hold no address are consumed whole, so the scan stays linear.
_ADDRESS_RE = re.compile(
    r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])'
    r"|(?P<address>[\w%+][\w.%+-]*+@(?:"
    r"(?=[\w.%+-]*+@[\w-]++(?:\.[\w-]++)*\.[a-zA-Z]{2,}\b)"
    r"[\w-]++(?:\.[\w-]++)*?\.[a-zA-Z]{2,}\b(?=-)"
    r"|[\w-]++(?:\.[\w-]++)*\.[a-zA-Z]{2,}\b))"
    r"|[.-]|[\w.%+-]++",
)

_HOME_PATH_RE = re.compile(
    r"(?:/Users/|/home/)[\w.-]+/",
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


@dataclass(frozen=True)
class PiiConfig:
    """User-configurable PII scanning settings."""

    allow_emails: list[str] = field(default_factory=list[str])
    allow_patterns: list[str] = field(default_factory=list[str])
    deny: list[str] = field(default_factory=list[str])
    ignore_files: list[str] = field(default_factory=list[str])

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Self:
        """Validate decoded PII rules before scanning."""
        return cls(
            allow_emails=cls._str_list(data, "allow_emails"),
            allow_patterns=cls._str_list(data, "allow_patterns"),
            deny=cls._str_list(data, "deny"),
            ignore_files=cls._str_list(data, "ignore_files"),
        )

    @staticmethod
    def _str_list(data: dict[str, object], key: str) -> list[str]:
        val = data.get(key, [])
        if not isinstance(val, list) or not all(
            isinstance(item, str) for item in cast("list[object]", val)
        ):
            raise ReleaseError(f"PII setting {key} must be a list of strings")
        return cast("list[str]", val)


@dataclass(frozen=True)
class Finding:
    """A single PII match in a file."""

    file: str
    line: int
    category: str  # "email", "path", "hostname", "deny"
    match: str


@dataclass(frozen=True, slots=True)
class ScanSource:
    """A named input and its decoded text."""

    path: str
    text: str


class PiiMatcher:
    """Apply compiled privacy rules to text from either the index or worktree."""

    _config: PiiConfig
    _allowed: set[str]
    _allow_regexes: list[re.Pattern[str]]

    def __new__(cls, config: PiiConfig, compiled: list[re.Pattern[str]]) -> Self:
        """Compile this scan's allow rules once."""
        self = super().__new__(cls)
        self._config = config
        self._allowed = _BUILTIN_ALLOW_EMAILS | set(self._config.allow_emails)
        self._allow_regexes = compiled
        return self

    def scan(self, source: ScanSource) -> list[Finding]:
        """Return every match not suppressed by the selected rules."""
        findings: list[Finding] = []
        for line_num, line in enumerate(source.text.splitlines(), 1):
            for category, value in self._addresses(line):
                findings.append(Finding(source.path, line_num, category, value))
            for value in self._home_paths(line):
                findings.append(Finding(source.path, line_num, "path", value))
            for pattern in self._config.deny:
                if pattern in line and not self._suppressed(pattern):
                    findings.append(Finding(source.path, line_num, "deny", pattern))
        return findings

    def _addresses(self, line: str) -> Generator[tuple[str, str]]:
        for match in _ADDRESS_RE.finditer(line):
            value = match["address"]
            if value is None or self._suppressed(value):
                continue
            if value.endswith(".local"):
                yield "hostname", value
            elif value not in self._allowed and not value.endswith(
                _BUILTIN_ALLOW_EMAIL_SUFFIXES
            ):
                yield "email", value

    def _home_paths(self, line: str) -> list[str]:
        return [
            value
            for match in _HOME_PATH_RE.finditer(line)
            if not (value := match.group()).startswith(_BUILTIN_ALLOW_PATHS)
            and not self._suppressed(value)
        ]

    def _suppressed(self, text: str) -> bool:
        """Check if a match is suppressed by an allow_patterns regex."""
        return any(r.search(text) for r in self._allow_regexes)
