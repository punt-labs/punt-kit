"""Pinning README's install-URL SHA to the commit that last touched
install.sh, and landing that pin via its own PR right after the release
squash-merge lands on main."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, cast, final
from urllib.parse import unquote, urlparse

from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps


@final
class ReadmeShaPin:
    """Keeps README's SHA-pinned install URL current with install.sh's commit."""

    __slots__ = ("_info", "_ops")

    # Single source of truth for the SHA charclass in a pinned install URL.
    # bump()'s SHA-refresh substitution and classify_install_urls()'s
    # authority-validated read-back both build their pattern from this
    # constant — neither hand-copies the shape, so the two can never
    # silently diverge.
    _SHA_SHAPE: str = r"[0-9a-fA-F]{7,40}"

    # Every URL-shaped token in free-form text (a README, an installCommand
    # string). Matches http OR https, case-insensitively — curl fetches
    # HTTPS://, Https://, and http://, all just as readily as https://, and
    # a token filter that misses them lets that URL evade classification
    # entirely (no check at all, worse than "untrusted").
    #
    # Deliberately NOT anchored on a literal "install.sh" substring (the
    # prior design): an attacker who percent-encodes even one character of
    # "install.sh" — "%69nstall.sh", where %69 decodes to "i" — produces a
    # URL with no such substring anywhere in the raw text, so a filter that
    # requires it finds zero tokens and the URL evades classification
    # entirely. Every URL-shaped token is captured here; deciding whether
    # a token is an install.sh reference happens after percent-decoding,
    # in classify_install_urls().
    #
    # Bounded by real text/shell delimiters — whitespace, a quote, a shell
    # pipe, or a shell command separator — not by that literal substring.
    # This still keeps two invocations glued by a zero-whitespace shell
    # trick (`${IFS}` in place of a literal space) as separate tokens:
    # `${IFS}` itself contains no quote/pipe/semicolon, but the literal
    # `|` a real payload needs to pipe into a shell does, and that `|` is
    # one of the stop characters.
    _URL_TOKEN = re.compile(r"""https?://[^\s"'|;]+""", re.IGNORECASE)

    # Where, within a percent-decoded token, an install.sh reference ends.
    # Matches "install.sh" case-insensitively only when followed by a
    # non-word character or the end of the string — never by another
    # letter, digit, or underscore. That boundary is what lets
    # classify_install_urls() find the reference and discard everything
    # after it, rather than requiring the token to end there: a
    # zero-whitespace shell trick can glue non-URL noise (e.g. "${IFS}")
    # directly onto a genuine ".../install.sh" with no delimiter between
    # them, and the trailing "$" of "${IFS}" is itself a non-word
    # character, so the boundary still lands exactly at the end of
    # "install.sh" and the glued noise is dropped. A different real
    # filename that merely starts with "install" — "install.shellscript"
    # — is correctly NOT matched, because "e" (a word character)
    # immediately follows "install.sh" there.
    _INSTALL_SH_BOUNDARY = re.compile(r"install\.sh(?=$|\W)", re.IGNORECASE)

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        return self

    @staticmethod
    def _url_prefix(owner: str, repo_name: str) -> str:
        """The regex prefix common to every install URL for this repo.

        ``raw.githubusercontent.com/<owner>/<repo>/`` — everything before the
        SHA-or-tag segment. Used by ``bump()``'s two substitutions, which
        rewrite this project's OWN already-trusted README content, so a
        plain regex prefix is sufficient there. ``classify_install_urls()``
        (the read-back used for verification) does NOT build from this
        prefix — a bare substring/regex match on the trusted host string
        can appear inside an attacker host's PATH (see its docstring), so
        verification parses each candidate URL with ``urlparse`` and checks
        its authority instead.
        """
        esc_owner = re.escape(owner)
        esc_repo = re.escape(repo_name)
        return rf"raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/"

    @classmethod
    def classify_install_urls(
        cls, content: str, owner: str, repo_name: str
    ) -> tuple[list[str], bool]:
        """Classify every install.sh URL in ``content`` as trusted or not.

        Returns ``(trusted_shas, has_untrusted)``.

        Every URL-shaped token (``_URL_TOKEN``) is percent-decoded via
        ``urllib.parse.unquote`` BEFORE any comparison — raw, undecoded
        text is never compared against ``owner``/``repo_name`` or the
        trusted host. Two evasions live in comparing encoded text: percent-
        encoding one character of ``install.sh`` (``%69nstall.sh``, where
        ``%69`` decodes to ``i``) hides the reference from a literal-text
        search, and percent-encoding a character of the repo segment
        (``%77idget``, where ``%77`` decodes to ``w``) hides it from a
        plain-text "does this reference our project" test — both decode to
        the real characters before curl ever requests them, so decoding
        first is what a real HTTP client effectively does too. Each
        decoded token is then searched for an install.sh reference
        (``_INSTALL_SH_BOUNDARY``) and truncated right after it, discarding
        anything the boundary regex's own docstring explains was glued on
        afterward; a token with no such reference isn't an install.sh URL
        at all and is skipped.

        A truncated token is TRUSTED only when the FULL token is exactly
        ``https://raw.githubusercontent.com/<owner>/<repo>/<segment>/
        install.sh`` — parsed with ``urllib.parse.urlparse`` (which
        normalizes scheme case, so ``HTTPS://`` and ``https://`` are
        equivalent) and accepted only when ``scheme == "https"`` and
        ``hostname == "raw.githubusercontent.com"`` EXACTLY (not
        ``endswith``, which would accept the attacker host
        ``raw.githubusercontent.com.evil.com``), with the PATH required to
        FULLY match ``/<owner>/<repo>/<segment>/install.sh`` end to end,
        comparing ``owner``/``repo_name`` CASE-INSENSITIVELY — GitHub
        routes repository URLs case-insensitively, so a real pin to
        ``.../PUNT-KIT/...`` is exactly as trusted as ``.../punt-kit/...``,
        and a case-sensitive comparison would false-fail the former. A
        prefix match is not enough: a token whose path merely STARTS with
        the trusted ``/<owner>/<repo>/`` prefix but carries trailing
        garbage (e.g. two URLs glued together with no separating
        whitespace) would otherwise be misclassified as "trusted but not
        SHA-shaped" and tolerated, hiding whatever follows. A bare
        substring/regex match on the trusted host string is not enough
        either: ``https://evil.example/raw.githubusercontent.com/<owner>/
        <repo>/<sha>/install.sh`` carries the trusted string inside an
        attacker host's PATH, and curl would download from evil.example,
        not GitHub.

        A trusted (fully-matching) token whose segment is SHA-shaped is a
        trusted SHA, collected into ``trusted_shas`` for the caller to
        verify currency against. A trusted token whose segment is NOT
        SHA-shaped (a version tag or branch) is tolerated with no further
        check — that shape is not a SHA pin and has nothing to go stale.

        EVERY token with an install.sh reference — not just the ones that
        fail the trusted-prefix test — is independently checked for
        whether it "references this project": the DECODED path contains
        ``/<repo_name>/``, compared CASE-INSENSITIVELY for the same
        GitHub-routing reason as the trusted check. (The repo name alone,
        not owner+repo together: an attacker can register their own
        same-named repo on the genuine raw.githubusercontent.com host, so
        requiring both would let ``.../attacker-org/<repo_name>/...``
        silently evade detection.) A token that references this project
        but did NOT achieve a clean, fully-matching trusted URL — trailing
        garbage, extra path, wrong host, wrong scheme, wrong owner — sets
        ``has_untrusted``, independently of whether any trusted pin was
        ALSO found in the same content and regardless of whether the
        untrusted token's segment is SHA-shaped or a version tag/branch (a
        SHA-pin-to-version-tag downgrade onto an untrusted host must fail
        exactly like an untrusted SHA does, or it would evade the check
        entirely by no longer looking like a SHA). A token that does not
        reference this project at all — some unrelated tool's install.sh
        URL — is ignored.
        """
        esc_owner = re.escape(owner)
        esc_repo = re.escape(repo_name)
        trusted_full = re.compile(
            rf"/{esc_owner}/{esc_repo}/([^/]+)/install\.sh", re.IGNORECASE
        )
        reference_pattern = re.compile(rf"/{esc_repo}/", re.IGNORECASE)
        trusted_shas: list[str] = []
        has_untrusted = False
        tokens = cast("list[str]", cls._URL_TOKEN.findall(content))
        for token in tokens:
            decoded = unquote(token)
            boundary = cls._INSTALL_SH_BOUNDARY.search(decoded)
            if boundary is None:
                continue  # not an install.sh reference at all — not a candidate
            candidate = decoded[: boundary.end()]
            parsed = urlparse(candidate)
            full_match = (
                trusted_full.fullmatch(parsed.path)
                if parsed.scheme == "https"
                and parsed.hostname == "raw.githubusercontent.com"
                else None
            )
            if full_match is not None:
                segment = full_match.group(1)
                if re.fullmatch(cls._SHA_SHAPE, segment):
                    trusted_shas.append(segment)
            elif reference_pattern.search(parsed.path):
                has_untrusted = True
        return trusted_shas, has_untrusted

    @classmethod
    def find_pinned_shas(cls, content: str, owner: str, repo_name: str) -> list[str]:
        """Return every trusted, SHA-pinned install.sh URL's commit SHA.

        Thin wrapper over ``classify_install_urls()`` — catches every pin
        in a README with several separate install snippets (curl | bash,
        curl -o, --no-plugin variants, ...) rather than just the first.
        """
        trusted_shas, _ = cls.classify_install_urls(content, owner, repo_name)
        return trusted_shas

    def bump(
        self,
        version: str,
        *,
        dry_run: bool,
        resolve_repo: Callable[[Path], str | None],
    ) -> None:
        """Update SHA-pinned install.sh URLs in README to the install.sh commit.

        ``resolve_repo`` is injected rather than composing ``GithubRepo``
        directly — ``test_readme_sha_pin_survives_tag`` monkeypatches
        ``punt_kit.release._get_github_repo`` and calls
        ``punt_kit.release._land_readme_sha_pin``/``_bump_readme_install_sha``
        expecting the patch to be observed (§0's mechanism).
        """
        root = self._info.root
        readme_path = root / "README.md"
        install_sh = root / "install.sh"
        if not readme_path.exists() or not install_sh.exists():
            return

        tag = f"v{version}"
        github_repo = resolve_repo(root)
        if github_repo:
            owner, repo_name = github_repo.split("/", 1)
        else:
            owner, repo_name = "punt-labs", root.name

        # Get the short SHA of the commit that last modified install.sh
        short_sha = (
            "<SHA>"
            if dry_run
            else ReleaseProject(self._info, ops=self._ops).install_sh_sha()
        )

        content = readme_path.read_text(encoding="utf-8")
        prefix = self._url_prefix(owner, repo_name)

        # Replace SHA-pinned install URLs: <owner>/<repo>/<hex-sha>/install.sh
        new_content = re.sub(
            rf"({prefix}){self._SHA_SHAPE}(/install\.sh)",
            rf"\g<1>{short_sha}\2",
            content,
        )

        # Also replace version-tag install URLs: <owner>/<repo>/v1.2.3/install.sh
        new_content = re.sub(
            rf"({prefix})v[0-9]+\.[0-9]+\.[0-9]+(/install\.sh)",
            rf"\g<1>{short_sha}\2",
            new_content,
        )

        if new_content == content:
            return

        if dry_run:
            self._ops.dry(f"README.md: install URLs → {short_sha} ({tag})")
            return

        readme_path.write_text(new_content, encoding="utf-8")
        self._ops.ok(f"README.md: install URLs → {short_sha} ({tag})")

    def land(
        self,
        version: str,
        *,
        dry_run: bool,
        merge: Callable[..., str],
        resolve_repo: Callable[[Path], str | None],
    ) -> None:
        """Pin README's install-URL SHA via its own PR, right after the squash-merge.

        Must run after the release PR's squash-merge lands on main, not
        during the version-bump phase on the release branch. ``gh pr merge
        --squash --delete-branch`` makes one new commit on main and deletes
        the release branch — any SHA pinned from a commit that only ever
        existed on that branch becomes unreachable the moment it is
        deleted, and a subsequent CI checkout of the release tag will not
        contain it. Reading ``install.sh``'s SHA here, with the working
        tree on the just-merged main, pins a commit that is main's own
        permanent history.

        ``merge`` is injected rather than composing ``PrMerger`` directly —
        tests monkeypatch ``punt_kit.release._pr_merge`` and call
        ``punt_kit.release._land_readme_sha_pin`` expecting the patch to be
        observed (§0's mechanism, same reasoning as ``PrMerger.merge``'s
        injected ``wait_for_checks``/``resolve_threads``).
        """
        root = self._info.root
        branch = f"release-readme-pin/v{version}"

        # No README or no install.sh means there is nothing to pin — the
        # subsequent bump() would be a no-op. Skip the whole branch/checkout/
        # PR dance rather than churn git and print a misleading "README
        # already pins..." line for a repo where pinning is not even
        # possible.
        if not (root / "README.md").exists() or not (root / "install.sh").exists():
            self._ops.ok("No README.md or install.sh — nothing to pin")
            return

        if dry_run:
            self._ops.dry("bump(...)")
            self._ops.dry(
                f'git commit -m "chore: update README install SHA to v{version}"'
            )
            self._ops.dry(
                f"merge(branch={branch}, "
                f'title="chore: update README install SHA v{version}")'
            )
            return

        workspace = GitWorkspace(root, ops=self._ops)
        workspace.ensure_on_main()

        if workspace.checkout_or_create(branch):
            self._ops.info(f"Checked out existing branch {branch}")

        self.bump(version, dry_run=False, resolve_repo=resolve_repo)
        status = self._ops.run(
            ["git", "status", "--porcelain", "--", "README.md"], cwd=str(root)
        ).stdout.strip()
        if not status:
            # Resume case: a prior run already committed the pin on this
            # branch, or the README already carried the correct SHA —
            # either way there is nothing new to land.
            ahead = self._ops.run(
                ["git", "log", "main..HEAD", "--oneline"], cwd=str(root)
            ).stdout.strip()
            if not ahead:
                # Hook-firing checkout + local branch delete — same
                # diagnosed convention as Phase 9's identical cleanup path
                # (pkit-f85t.7 round 2).
                checkout = self._ops.run(
                    ["git", "checkout", "main"],
                    cwd=str(root),
                    check=False,
                    timeout=GIT_HOOK,
                )
                if checkout.returncode != 0:
                    self._ops.fail(
                        f"git checkout main failed:\n{checkout.stderr.strip()}"
                    )
                delete = self._ops.run(
                    ["git", "branch", "-D", branch], cwd=str(root), check=False
                )
                if delete.returncode != 0:
                    self._ops.fail(
                        f"git branch -D {branch} failed:\n{delete.stderr.strip()}"
                    )
                self._ops.ok("README already pins the current install SHA")
                return
        else:
            workspace.commit_if_staged(
                ["README.md"], f"chore: update README install SHA to v{version}"
            )

        merge(
            cwd=root,
            branch=branch,
            title=f"chore: update README install SHA v{version}",
            dry_run=False,
        )
        self._ops.ok("README SHA pin PR merged")
