"""The release pipeline: a Protocol every phase satisfies, a value object
describing one step, and the runner that iterates them."""

from __future__ import annotations

from concurrent.futures import as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from rich.console import Console

from punt_kit.phases.shared.errors import ReleaseError

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Sequence
    from concurrent.futures import Future

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.project_info import ReleaseProject
    from punt_kit.phases.shared.siblings import SkipRecorder

# Separate from release.py's own `console` and Reporter's singleton — this
# module's only user is the plain-formatted end-of-run summary banner, which
# uses raw console.print() with rich markup rather than the _ok/_info/_warn
# vocabulary.
_console = Console()


@runtime_checkable
class Phase(Protocol):
    """Anything with a no-arg ``run() -> None``.

    The 11 release phases share zero implementation — each phase's ``run()``
    body is entirely distinct control flow calling distinct collaborators.
    There is no template method any phase would inherit, so a Protocol
    (structural interface) is the right shape, not an ABC.
    """

    def run(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PhaseStep:
    """One named, numbered step in the pipeline.

    A pure value object: ``release.py`` builds one ``PhaseStep`` per phase
    using a closure defined in ``release.py`` (so the bare-name lookup rule
    from ``ReleaseOps`` still applies to the ``_phaseN_xxx(...)`` wrapper it
    calls) rather than a bound method on a ``phases/*`` class — this is what
    lets ``ReleasePipeline`` stay fully generic (it does not know about 11
    specific phase classes) while ``monkeypatch.setattr(release_mod,
    "_phase3_build", ...)`` still intercepts correctly.
    """

    number: int
    name: str
    run: Callable[[], None]


@final
class ThreadedStep:
    """Collects results from phases run concurrently in a thread pool."""

    __slots__ = ("_ops",)

    _ops: ReleaseOps

    def __new__(cls, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        return self

    def collect(
        self,
        futures: dict[Future[None], str],
        *,
        interrupted: threading.Event,
    ) -> None:
        """Wait for all futures, collect errors, and fail if any occurred.

        If ``interrupted`` is set after threads drain, raises
        ``KeyboardInterrupt`` so the caller's ``finally`` block handles
        cleanup (avoiding double-cleanup with ``run_release``).
        """
        errors: list[tuple[str, BaseException]] = []
        for f in as_completed(futures):
            name = futures[f]
            try:
                f.result()
            except ReleaseError as e:
                errors.append((name, RuntimeError(str(e))))
            except SystemExit as e:
                if isinstance(e.code, int):
                    msg = f"{name} failed (exit code {e.code})"
                elif isinstance(e.code, str) and e.code.strip():
                    msg = e.code
                else:
                    msg = f"{name} failed"
                errors.append((name, RuntimeError(msg)))
            except BaseException as e:  # noqa: BLE001
                errors.append((name, e))
        if interrupted.is_set():
            raise KeyboardInterrupt
        if errors:
            for name, err in errors:
                _console.print(f"  [red]✗[/red] {name}: {err}")
            # Carries each task's own error text, not just its name — this
            # message is what callers like Phase10Propagate record into
            # SkipRecorder for the end-of-run recap, and "install-all.sh:
            # boom" tells the operator more than ".github" alone does.
            details = "; ".join(f"{name}: {err}" for name, err in errors)
            self._ops.fail(f"{len(errors)} task(s) failed: {details}")


@final
class ReleasePipeline:
    """Runs the numbered release phases in order, honoring a resume point."""

    __slots__ = ("_ops", "_steps")

    _steps: Sequence[PhaseStep]
    _ops: ReleaseOps

    def __new__(cls, steps: Sequence[PhaseStep], *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._steps = steps
        self._ops = ops
        return self

    def run(self, *, start: int) -> None:
        """Run every step numbered ``>= start``, in order."""
        for step in self._steps:
            if step.number < start:
                continue
            step.run()

    @staticmethod
    def print_manual_actions(skips: SkipRecorder) -> None:
        """Drain and print every retained skip/failure notice, if any.

        Shared between the success-path summary (``summarize``, below) and
        ``run_release``'s incomplete-release reporting — an interrupted or
        partially-failed run never reaches ``summarize``, but the operator
        still needs the same recap of outstanding manual actions, including
        any Phase 10 leg failure ``Phase10Propagate`` recorded here before
        re-raising.
        """
        skipped = skips.drain()
        if skipped:
            _console.print("[bold yellow]⚠ Manual action required[/bold yellow]")
            for notice in skipped:
                _console.print(f"  [yellow]•[/yellow] {notice}")
            _console.print()

    def summarize(
        self,
        info: ProjectInfo,
        version: str,
        *,
        dry_run: bool,
        project: ReleaseProject,
        skips: SkipRecorder,
    ) -> None:
        """Print the end-of-run summary and recap any recorded skips.

        Takes ``version`` explicitly (not re-derived from ``project``)
        because the phase that calls this has the release's own version in
        hand — re-deriving from disk would trust a different source of
        truth than the rest of the run used.
        """
        tag = f"v{version}"
        package = (
            project.package_name() if info.language == "python" else info.root.name
        )
        if info.is_hybrid:
            ptype = "hybrid"
        elif info.is_plugin:
            ptype = "plugin"
        else:
            ptype = "CLI-only"

        dr = "(dry run) " if dry_run else ""
        _console.print(f"\n[bold green]Release {tag} {dr}Complete[/bold green]\n")
        _console.print(f"  Package:        {package}")
        _console.print(f"  Version:        {version}")
        _console.print(f"  Type:           {ptype}")
        _console.print(f"  Tag:            {tag}")
        _console.print()
        if not dry_run and (info.is_plugin or info.is_hybrid):
            _console.print("  Restart Claude Code to pick up marketplace changes.")
        _console.print()

        # Recap every propagation/verification step skipped mid-run — the
        # operator sees outstanding manual actions as the last thing
        # printed, even if the inline warnings scrolled past during
        # concurrent Phase 10 work.
        self.print_manual_actions(skips)
