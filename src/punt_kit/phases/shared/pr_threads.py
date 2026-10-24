"""Resolving a PR's unresolved review threads, page by page."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.errors import RemoteLookupError

if TYPE_CHECKING:
    from punt_kit.phases.shared.github_repo import GithubRepo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.repo_slug import RepoSlug


@dataclass(frozen=True, slots=True)
class _ThreadPage:
    """One page of a PR's review threads: what is unresolved, and where next."""

    unresolved: tuple[str, ...]
    # ``hasNextPage`` as the server reported it, and the cursor to ask with. A
    # next page the cursor cannot reach is a listing that stops short.
    has_more: bool
    next_cursor: str | None


@final
class PrThreadResolver:
    """Resolves unresolved review threads on a PR (Copilot/Bugbot auto-review)."""

    __slots__ = ("_ops", "_repo")

    _repo: GithubRepo
    _ops: ReleaseOps

    def __new__(cls, repo: GithubRepo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._repo = repo
        self._ops = ops
        return self

    def resolve(self, gh: str, cwd: str, pr_number: int) -> None:
        """Resolve all unresolved review threads on a PR.

        Copilot and Bugbot auto-post reviews on every PR. With
        required_review_thread_resolution=true, unresolved threads block
        merge. Every page of threads is read, not only the first.
        """
        slug = self._slug_or_warn(pr_number)
        if slug is None:
            return

        unresolved: list[str] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while (page := self._fetch_page(gh, cwd, slug, pr_number, cursor)) is not None:
            unresolved.extend(page.unresolved)
            cursor = page.next_cursor
            if not page.has_more:
                break
            if cursor is None or cursor in seen_cursors:
                self._ops.warn(
                    f"PR #{pr_number} has more review threads than could be "
                    "listed (the next page has no new cursor) — merge may fail"
                )
                break
            seen_cursors.add(cursor)

        self._resolve_all(gh, cwd, pr_number, unresolved)

    def _slug_or_warn(self, pr_number: int) -> RepoSlug | None:
        """The repository's slug; ``None`` after warning that there is none."""
        try:
            slug = self._repo.slug()
        except (ValueError, RemoteLookupError) as exc:
            self._ops.warn(
                f"Review threads on PR #{pr_number} not resolved: {exc} "
                "— merge may fail"
            )
            return None
        if slug is None:
            self._ops.warn(
                f"Review threads on PR #{pr_number} not resolved: no github.com "
                "origin remote — merge may fail"
            )
        return slug

    def _fetch_page(
        self, gh: str, cwd: str, slug: RepoSlug, pr_number: int, cursor: str | None
    ) -> _ThreadPage | None:
        """One page of threads; ``None`` after warning that the listing failed."""
        result = self._ops.run(
            [
                gh,
                "api",
                "graphql",
                "-f",
                f"query={self._threads_query(slug, pr_number, cursor)}",
            ],
            cwd=cwd,
            check=False,
        )
        if result.returncode != 0:
            # gh exits 1 on a GraphQL error, with the message on stderr.
            reason = result.stderr.strip() or result.stdout[:200]
            self._ops.warn(
                f"Could not fetch review threads on PR #{pr_number}: {reason} "
                "— merge may fail"
            )
            return None
        try:
            return self._page_of(json.loads(result.stdout))
        except json.JSONDecodeError:
            self._ops.warn(
                f"Could not parse review thread response for PR #{pr_number} "
                f"({result.stdout[:100]!r}) — thread resolution skipped, merge "
                "may fail"
            )
        except ValueError as exc:
            self._ops.warn(
                f"Review threads on PR #{pr_number} not resolved: {exc} "
                "— merge may fail"
            )
        return None

    def _resolve_all(
        self, gh: str, cwd: str, pr_number: int, unresolved: list[str]
    ) -> None:
        """Resolve each thread id; say so plainly when any of them was not."""
        if not unresolved:
            return
        resolved = 0
        for tid in unresolved:
            mutation = (
                f'mutation {{ resolveReviewThread(input: {{threadId: "{tid}"}})'
                " { thread { isResolved } } }"
            )
            res = self._ops.run(
                [gh, "api", "graphql", "-f", f"query={mutation}"],
                cwd=cwd,
                check=False,
            )
            if res.returncode == 0:
                resolved += 1
            else:
                self._ops.info(f"Could not resolve thread {tid}: {res.stderr.strip()}")
        if resolved == len(unresolved):
            self._ops.ok(f"Resolved {resolved}/{len(unresolved)} review thread(s)")
        else:
            self._ops.warn(
                f"Resolved only {resolved}/{len(unresolved)} review thread(s) on "
                f"PR #{pr_number} — merge may fail"
            )

    @staticmethod
    def _threads_query(slug: RepoSlug, pr_number: int, cursor: str | None) -> str:
        """The GraphQL query for one page of a PR's review threads."""
        after = f", after: {json.dumps(cursor)}" if cursor is not None else ""
        return (
            f'{{ repository(owner: "{slug.owner}", name: "{slug.name}") {{'
            f" pullRequest(number: {pr_number}) {{"
            f" reviewThreads(first: 100{after}) {{"
            " pageInfo { hasNextPage endCursor }"
            " nodes { id isResolved } } } } }"
        )

    @staticmethod
    def _child(node: object, key: str) -> object:
        """``node[key]``, or ``None`` when ``node`` is not an object (a JSON null)."""
        if isinstance(node, dict):
            return cast("dict[str, object]", node).get(key)
        return None

    @classmethod
    def _page_of(cls, data: object) -> _ThreadPage:
        """The unresolved ids and next cursor of a ``_threads_query`` response.

        Raises ``ValueError`` saying why when the response has no
        ``reviewThreads`` object: that is a query that failed, not a PR with
        nothing to resolve. GraphQL ``errors`` never reach here: gh exits 1
        for them, and ``resolve`` reports that exit. A ``null`` ``nodes``
        inside a real ``reviewThreads`` object reads as an empty page.
        """
        threads: object = data
        for key in ("data", "repository", "pullRequest", "reviewThreads"):
            threads = cls._child(threads, key)
        if not isinstance(threads, dict):
            msg = "the response has no reviewThreads object"
            raise ValueError(msg)
        threads = cast("dict[str, object]", threads)
        nodes = cls._child(threads, "nodes")
        ids: list[str] = []
        if isinstance(nodes, list):
            for thread in cast("list[object]", nodes):
                thread_id = cls._child(thread, "id")
                if isinstance(thread_id, str) and not cls._child(thread, "isResolved"):
                    ids.append(thread_id)
        page_info = cls._child(threads, "pageInfo")
        cursor = cls._child(page_info, "endCursor")
        has_more = cls._child(page_info, "hasNextPage") is True
        return _ThreadPage(
            tuple(ids), has_more, cursor if isinstance(cursor, str) else None
        )
