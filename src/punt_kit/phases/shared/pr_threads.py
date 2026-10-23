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
    # The cursor of the following page; ``None`` is the answer for "no more".
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
        try:
            slug = self._repo.slug()
        except (ValueError, RemoteLookupError) as exc:
            self._ops.warn(
                f"Review threads on PR #{pr_number} not resolved: {exc} "
                "— merge may fail"
            )
            return
        if slug is None:
            self._ops.warn(
                f"Review threads on PR #{pr_number} not resolved: no github.com "
                "origin remote — merge may fail"
            )
            return

        unresolved: list[str] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
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
                self._ops.info("Could not fetch review threads — merge may fail")
                break
            try:
                page = self._page_of(json.loads(result.stdout))
            except json.JSONDecodeError:
                self._ops.info(
                    f"Could not parse review thread response for PR #{pr_number} "
                    f"({result.stdout[:100]!r}) — thread resolution skipped, merge "
                    "may fail"
                )
                break
            unresolved.extend(page.unresolved)
            cursor = page.next_cursor
            if cursor is None or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)

        self._resolve_all(gh, cwd, unresolved)

    def _resolve_all(self, gh: str, cwd: str, unresolved: list[str]) -> None:
        """Resolve each thread id, reporting how many succeeded."""
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
        if resolved:
            self._ops.ok(f"Resolved {resolved}/{len(unresolved)} review thread(s)")

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

        GitHub answers ``null`` for any level it cannot resolve (an inaccessible
        repository, a deleted PR); each such level reads as an empty page.
        """
        threads: object = data
        for key in ("data", "repository", "pullRequest", "reviewThreads"):
            threads = cls._child(threads, key)
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
            tuple(ids), cursor if has_more and isinstance(cursor, str) else None
        )
