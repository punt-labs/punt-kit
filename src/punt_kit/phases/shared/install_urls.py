"""Recognizing a project's pinned install.sh URLs in free-form text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final
from urllib.parse import ParseResult, unquote, urlparse

from punt_kit.phases.shared.pin_rules import FILENAME_END
from punt_kit.phases.shared.repo_slug import RepoSlug

if TYPE_CHECKING:
    from collections.abc import Callable

_SHA_SHAPE = re.compile(r"[0-9a-fA-F]{7,40}")
_RELEASE_TAG_SHAPE = re.compile(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", re.IGNORECASE)

_INSTALL_SH = "install.sh"
_TRUSTED_HOST = "raw.githubusercontent.com"


@dataclass(frozen=True, slots=True)
class InstallUrl:
    """One install.sh URL reference found in text, already classified.

    ``url`` is the percent-decoded URL of the reference — for a token whose
    decoding never settles, the raw token. ``segment`` is the pinned path
    segment (a commit SHA, a release tag, a branch) and is empty unless the
    URL is trusted. ``segment_span`` locates that segment in the scanned
    text so a caller can rewrite it; it is ``None`` when the token carried
    any percent-encoding (the decoded offsets do not map onto the raw text)
    or when the URL is untrusted.
    """

    url: str
    is_trusted: bool
    segment: str
    segment_span: tuple[int, int] | None

    @property
    def is_sha_pin(self) -> bool:
        """True for a trusted URL pinned to a commit SHA."""
        return self.is_trusted and InstallUrlRecognizer.is_sha_segment(self.segment)

    @property
    def is_pin(self) -> bool:
        """True for a trusted URL pinned to a commit SHA or a release tag."""
        return self.is_sha_pin or (
            self.is_trusted and _RELEASE_TAG_SHAPE.fullmatch(self.segment) is not None
        )


@final
class InstallUrlRecognizer:
    """The single definition of "a pinned install URL for this repository".

    ``ReadmeShaPin.bump`` (which rewrites pins and then verifies its own
    output), the website propagator, Phase 11 (which verifies the published
    README and the website's ``installCommand``) and ``punt audit`` recognize
    pins through this class, so they cannot disagree about what a pin is. A
    test fails if any other module builds a regex for an install URL.

    In scope — a URL is TRUSTED when, after percent-decoding to a fixed
    point, it is exactly ``https://raw.githubusercontent.com/<owner>/
    <repo>/<segment>/install.sh``: no userinfo and no port, because a
    trusted pin URL has neither and either one can hide the real host from
    a reader. Scheme, host, owner, repo and the file name compare
    case-insensitively (GitHub routes them that way).
    The segment is a *pin* when it is a 7-40 hex commit SHA or a release
    tag ``vX.Y.Z[-prerelease]``; ``ReadmeShaPin.bump`` rewrites both. Any
    other segment (``main``, a branch) is tolerated and never rewritten:
    it is not a pin and has nothing to go stale.

    In scope as UNTRUSTED — any other install.sh URL that references this
    repository (the decoded path contains ``/<repo>/``): a different
    owner, a different host, userinfo or a port on the right host, a
    percent-encoding chain that never settles. Non-URL noise glued directly
    after ``install.sh`` (``${IFS}``) is dropped before classifying. A longer
    file name (``install.sh.bak``,
    ``install.sh-old``) is not an install.sh reference at all. The repo
    name alone is the reference test because an attacker can register a
    same-named repo under their own owner on the genuine host.
    ``all_urls_relevant``
    drops that test for text already known to describe this project
    (the website's ``installCommand``), where every install.sh URL counts.

    Out of scope — install.sh URLs that do not reference this repository
    (a README documents other tools too), and anything that is not an
    ``http(s)`` URL ending in ``install.sh``: relative scripts
    (``./install.sh``), ``git clone``, and other download hosts that do
    not name the repo.
    """

    __slots__ = ("_owner", "_reference", "_repo", "_trusted")

    # Every URL-shaped token in free-form text. http OR https,
    # case-insensitively: curl fetches HTTPS://, Https://, and http:// as
    # readily as https://, and a filter that misses them lets that URL
    # evade classification entirely.
    #
    # Deliberately NOT anchored on a literal "install.sh" substring: an
    # attacker who percent-encodes one character of it ("%69nstall.sh")
    # produces a URL with no such substring in the raw text. Whether a
    # token is an install.sh reference is decided after decoding.
    #
    # Bounded by whitespace, a quote, a pipe, or a command separator, so
    # two invocations glued by a zero-whitespace shell trick (`${IFS}`)
    # stay separate tokens: the `|` a real payload needs to pipe into a
    # shell is a stop character.
    _URL_TOKEN = re.compile(r"""https?://[^\s"'|;]+""", re.IGNORECASE)

    # Where, in a decoded token, an install.sh reference ends: "install.sh"
    # followed by the end of the string or a non-word character, but never
    # by a word character or by a dot or hyphen that continues the file name
    # ("install.sh.bak", "install.sh-old"). Punctuation that merely ends a
    # sentence ("install.sh.") still closes the reference. Non-URL noise
    # glued directly onto a real URL ("${IFS}") is dropped, because the "$"
    # is itself a non-word character; "install.shellscript" is not matched.
    _INSTALL_SH_BOUNDARY = re.compile(rf"install\.sh{FILENAME_END}", re.IGNORECASE)

    # Locates both ends of every install.sh reference in a fully decoded
    # token: a scheme start (group 1) or an install.sh boundary (group 2,
    # built from ``_INSTALL_SH_BOUNDARY`` so the two cannot diverge). One
    # token can hide several references once decoded — ``%0A`` reveals a
    # second "https://.../install.sh" glued to the first with no delimiter
    # in the raw text — so every scheme/boundary pair is walked.
    _SCHEME_OR_BOUNDARY = re.compile(
        rf"(https?://)|({_INSTALL_SH_BOUNDARY.pattern})", re.IGNORECASE
    )

    # Depth cap for percent-decoding to a fixed point. ``unquote()`` never
    # lengthens a string, so decoding always terminates; the cap only
    # bounds the work against a pathological input.
    _MAX_DECODE_DEPTH = 5

    _owner: str
    _repo: str
    _trusted: re.Pattern[str]
    _reference: re.Pattern[str]

    def __new__(cls, owner: str, repo_name: str) -> Self:
        if not owner or not repo_name:
            msg = f"owner and repo must both be non-empty: {owner!r}/{repo_name!r}"
            raise ValueError(msg)
        self = super().__new__(cls)
        self._owner = owner
        self._repo = repo_name
        esc_owner, esc_repo = re.escape(owner), re.escape(repo_name)
        self._trusted = re.compile(
            rf"/{esc_owner}/{esc_repo}/([^/]+)/install\.sh", re.IGNORECASE
        )
        self._reference = re.compile(rf"/{esc_repo}/", re.IGNORECASE)
        return self

    @property
    def slug(self) -> str:
        """The ``owner/repo`` this recognizer trusts."""
        return f"{self._owner}/{self._repo}"

    @classmethod
    def for_slug(cls, slug: str) -> Self:
        """Build a recognizer from an ``owner/repo`` slug.

        Surrounding slashes and whitespace are stripped (a remote URL such
        as ``https://github.com/owner/repo/`` resolves to ``owner/repo/``).
        Raises ``ValueError`` unless exactly one non-empty owner and one
        non-empty repo remain.
        """
        parsed = RepoSlug.parse(slug)
        return cls(parsed.owner, parsed.name)

    def scan(
        self, content: str, *, all_urls_relevant: bool = False
    ) -> list[InstallUrl]:
        """Return every relevant install.sh reference in ``content``, in order.

        Each URL-shaped token is percent-decoded to a fixed point BEFORE any
        comparison; raw or partly decoded text is never compared. A token
        still changing at the depth cap is reported untrusted
        unconditionally: a legitimate committed install URL carries zero
        encoding layers, and silently dropping the token would be the
        zero-candidate evasion this class exists to close.

        Every install.sh reference within a decoded token is classified
        independently. A reference is trusted only when the whole span
        matches ``https://raw.githubusercontent.com/<owner>/<repo>/
        <segment>/install.sh``, parsed with ``urlparse`` and accepted only
        when the network location equals ``raw.githubusercontent.com``
        exactly (not ``endswith``, which would accept
        ``raw.githubusercontent.com.evil.com``, and with no userinfo or
        port) and the PATH fully matches. A bare substring match is not
        enough: ``https://evil.example/raw.githubusercontent.com/<owner>/
        <repo>/<sha>/install.sh`` carries the trusted string in an attacker
        host's path.
        """
        refs: list[InstallUrl] = []
        for token_match in self._URL_TOKEN.finditer(content):
            token = token_match.group()
            decoded, settled = self._decode_to_fixed_point(token)
            if not settled:
                refs.append(InstallUrl(token, False, "", None))
                continue
            for start, end in self._install_sh_spans(decoded):
                candidate = decoded[start:end]
                try:
                    parsed = urlparse(candidate)
                except ValueError:
                    # An unbalanced "[" in the authority: no client can fetch
                    # this, so it is not an install URL to classify.
                    continue
                trusted = self._trusted_match(parsed)
                if trusted is not None:
                    segment = trusted.group(1)
                    span = None
                    if decoded == token:
                        seg_end = token_match.start() + end - len(_INSTALL_SH) - 1
                        span = (seg_end - len(segment), seg_end)
                    refs.append(InstallUrl(candidate, True, segment, span))
                elif all_urls_relevant or self._reference.search(parsed.path):
                    refs.append(InstallUrl(candidate, False, "", None))
        return refs

    def classify(
        self, content: str, *, all_urls_relevant: bool = False
    ) -> tuple[list[str], bool]:
        """Return ``(trusted_pins, has_untrusted)`` for ``content``.

        A pin is a trusted URL pinned to a commit SHA or a release tag, the
        same pins ``repinned`` rewrites, so a verifier sees every pin a
        writer could leave behind. Trusted and untrusted references are
        reported independently: a text can carry a current trusted pin AND
        an injected untrusted one, and the latter must never be skipped
        because a trusted pin was found. A trusted URL whose segment is a
        branch (``main``) is not a pin and has nothing to go stale.
        """
        refs = self.scan(content, all_urls_relevant=all_urls_relevant)
        return (
            [ref.segment for ref in refs if ref.is_pin],
            any(not ref.is_trusted for ref in refs),
        )

    @staticmethod
    def is_sha_segment(segment: str) -> bool:
        """True when ``segment`` is shaped like a 7-40 hex commit SHA."""
        return _SHA_SHAPE.fullmatch(segment) is not None

    def repinned(
        self, content: str, sha: str, *, is_current: Callable[[str], bool]
    ) -> str:
        """Return ``content`` with every plain, trusted pin moved to ``sha``.

        Only the pinned segment changes, so the surrounding text and the
        original casing of owner, repo and file name are preserved. A pin
        for which ``is_current`` is true is left alone: the caller supplies
        the one test of currency, ``PinCurrency.is_current``, so this writer
        rewrites exactly the pins that the verifier would flag. A reference
        that is untrusted, percent-encoded, or not a pin (``main``) is never
        touched — callers verify the result with ``scan`` to find those.
        """
        spans = sorted(
            (
                ref.segment_span
                for ref in self.scan(content)
                if ref.is_pin
                and ref.segment_span is not None
                and not is_current(ref.segment)
            ),
            reverse=True,
        )
        for low, high in spans:
            content = content[:low] + sha + content[high:]
        return content

    def _trusted_match(self, parsed: ParseResult) -> re.Match[str] | None:
        """The path match when ``parsed`` is exactly this repo's trusted install URL."""
        if parsed.scheme != "https" or parsed.netloc.lower() != _TRUSTED_HOST:
            return None
        return self._trusted.fullmatch(parsed.path)

    @classmethod
    def _decode_to_fixed_point(cls, token: str) -> tuple[str, bool]:
        """Percent-decode ``token`` until it stops changing.

        Returns ``(decoded, reached_fixed_point)``. One ``unquote()`` pass
        unwraps one encoding layer; a double-encoded ``%2569nstall.sh``
        needs two. Decoding to a fixed point closes every depth uniformly
        instead of hard-coding a pass count. ``reached_fixed_point`` is
        ``False`` when the cap is hit while the string is still changing;
        the caller must not trust that partial decode.
        """
        current = token
        for _ in range(cls._MAX_DECODE_DEPTH):
            nxt = unquote(current)
            if nxt == current:
                return current, True
            current = nxt
        return current, False

    @classmethod
    def _install_sh_spans(cls, decoded: str) -> list[tuple[int, int]]:
        """Every ``(start, end)`` span of a complete install.sh URL in ``decoded``.

        Pairs each install.sh boundary with the CLOSEST preceding scheme
        start — not necessarily position 0, since only the first URL in a
        token starts there. Walking the whole string and collecting every
        span is what lets a second reference revealed only by decoding
        (behind a decoded ``%0A``) still be classified.
        """
        spans: list[tuple[int, int]] = []
        last_scheme_start: int | None = None
        for match in cls._SCHEME_OR_BOUNDARY.finditer(decoded):
            if match.group(1) is not None:
                last_scheme_start = match.start()
            elif last_scheme_start is not None:
                spans.append((last_scheme_start, match.end()))
        return spans
