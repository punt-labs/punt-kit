"""Parse and render GitHub ``owner/repo`` identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self
from urllib.parse import urlparse, urlsplit

# GitHub owners and repositories are made of word characters, dots, and
# hyphens; "." and ".." are path components, never names.
_NAME = re.compile(r"[\w.-]+")
_PATH_COMPONENTS = frozenset({".", ".."})

# scp-style remotes: ``[user@]github.com:owner/repo``. The user is whatever the
# account was given (``git``, ``org-123``); the host is case-insensitive.
_SCP_GITHUB = re.compile(r"(?:[^@/:\s]+@)?github\.com:(?P<path>.*)", re.IGNORECASE)

# Credentials in free text (a command line, a git error): a URL with a scheme,
# an scp-style ``user@host:path``, and any ``word:word@`` left where a URL did
# not parse.
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
_SCP_IN_TEXT = re.compile(r"(?<![\w.@-])([^\s@/:]+)@(?=[\w.-]+:[^\s:])")
_USERINFO_IN_TEXT = re.compile(r"[\w.~%+-]+:[\w.~%+-]*@")


@dataclass(frozen=True, slots=True)
class RepoSlug:
    """Represent the owner and repository halves of a GitHub slug."""

    owner: str
    name: str

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Parse an ``owner/repo`` slug and discard surrounding whitespace and slashes.

        Strip an optional ``.git`` suffix.

        Raises:
            ValueError: The slug does not contain valid owner and repository names.
        """
        parts = raw.strip().strip("/").removesuffix(".git").split("/")
        if len(parts) != 2 or not all(
            _NAME.fullmatch(part) and part not in _PATH_COMPONENTS for part in parts
        ):
            msg = f"not an owner/repo slug: {raw!r}"
            raise ValueError(msg)
        return cls(parts[0], parts[1])

    @classmethod
    def from_remote_url(cls, url: str) -> Self | None:
        """Parse a github.com remote in HTTPS, SSH, or SCP-style form.

        Return ``None`` for URLs outside github.com or without a repository path.

        Raises:
            ValueError: URL parsing fails or the GitHub path is not a valid slug.
        """
        url = url.strip()
        if scp := _SCP_GITHUB.fullmatch(url):
            return cls.parse(scp.group("path"))
        parsed = urlparse(url)
        if parsed.hostname != "github.com" or not parsed.path.strip("/"):
            return None
        return cls.parse(parsed.path.lstrip("/"))

    def __str__(self) -> str:
        """Render the slug as ``owner/repo``."""
        return f"{self.owner}/{self.name}"

    @staticmethod
    def without_userinfo(url: str) -> str:
        """Strip credentials, query, and fragment from a URL before displaying it."""
        if "://" not in url:
            # scp-style ``[user@]host:path``: the user may itself be a token.
            head, colon, path = url.partition(":")
            user, at, host = head.partition("@")
            if at and "/" not in user:
                head = host
            return f"{head}{colon}{path.split('?')[0].split('#')[0]}"
        try:
            parts = urlsplit(url)
        except ValueError:
            return "<unparseable url>"  # never echo what could not be parsed
        host = parts.netloc.rpartition("@")[2]
        return parts._replace(netloc=host, query="", fragment="").geturl()

    @classmethod
    def redacted(cls, text: str) -> str:
        """Remove credentials from URL-shaped text.

        Redact URL userinfo, query strings, fragments, SCP-style user names,
        and stray credential fragments. Preserve the conventional SCP user
        ``git``.
        """
        text = _URL_IN_TEXT.sub(lambda m: cls.without_userinfo(m.group()), text)
        text = _SCP_IN_TEXT.sub(
            lambda m: m.group() if m.group(1) == "git" else "", text
        )
        return _USERINFO_IN_TEXT.sub("", text)
