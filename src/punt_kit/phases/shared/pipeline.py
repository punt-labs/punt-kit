"""The release pipeline: a Protocol every phase satisfies, a value object
describing one step, and the runner that iterates them."""

from __future__ import annotations

from concurrent.futures import as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, cast, final, runtime_checkable

from rich.console import Console
from rich.markup import escape

from punt_kit.phases.shared.errors import (
    OperationalFailure,
    ReleaseError,
    ReportedReleaseError,
)
from punt_kit.phases.shared.phase_order import PhaseOrder
from punt_kit.phases.shared.repo_slug import RepoSlug

if TYPE_CHECKING:
    import subprocess
    import threading
    from collections.abc import Callable, Sequence
    from concurrent.futures import Future

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.project_info import ReleaseProject
    from punt_kit.phases.shared.skips import SkipRecorder

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
        errors: list[tuple[str, str]] = []
        reported: set[str] = set()  # tasks whose failure Reporter.fail printed
        collected: set[Future[None]] = set()
        try:
            for f in as_completed(futures):
                collected.add(f)
                self._collect_one(f, futures[f], errors, reported)
        except KeyboardInterrupt:
            # The interrupt skipped the futures the loop had not reached; any
            # that already finished still hold a failure to show.
            for f, name in futures.items():
                if f.done() and f not in collected:
                    self._collect_one(f, name, errors, reported)
            self._print_unreported(errors, reported)
            raise
        if interrupted.is_set():
            # The interrupt report replaces the failure summary below, so
            # what the tasks reported must be shown before it is lost.
            self._print_unreported(errors, reported)
            raise KeyboardInterrupt
        if errors:
            # Carries each task's own error text, not just its name, and does
            # not print it: the caller records the failure and the end-of-run
            # recap prints it once. "install-all.sh: boom" tells the operator
            # more than ".github" alone does.
            details = "; ".join(f"{name}: {text}" for name, text in errors)
            msg = f"{len(errors)} task(s) failed: {details}"
            raise ReleaseError(msg)

    def _collect_one(
        self,
        future: Future[None],
        name: str,
        errors: list[tuple[str, str]],
        reported: set[str],
    ) -> None:
        """Record the failure ``future`` holds, if any, under ``name``."""
        try:
            future.result()
        except ReleaseError as e:
            errors.append((name, str(e)))
            if isinstance(e, ReportedReleaseError):
                reported.add(name)
        except SystemExit as e:
            errors.append((name, self._describe_exit(name, e)))
        except BaseException as e:
            # Thread-pool boundary: whatever a task raised is collected so
            # its siblings finish, then every error is re-raised together.
            errors.append((name, OperationalFailure.report(e)))

    @staticmethod
    def _print_unreported(errors: list[tuple[str, str]], reported: set[str]) -> None:
        """Print each collected error that ``Reporter.fail`` did not already show."""
        for name, text in errors:
            if name not in reported:
                _console.print(f"[red]Error:[/red] {escape(f'{name}: {text}')}")

    @staticmethod
    def _describe_exit(name: str, exc: SystemExit) -> str:
        """Return the error text for a task that called ``sys.exit``."""
        if isinstance(exc.code, int):
            return f"{name} failed (exit code {exc.code})"
        if isinstance(exc.code, str) and exc.code.strip():
            return exc.code
        return f"{name} failed"


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
                _console.print(f"  [yellow]•[/yellow] {escape(notice)}")
            _console.print()

    @staticmethod
    def print_unreported(exc: ReleaseError) -> None:
        """Print ``exc`` unless ``Reporter.fail`` already printed it."""
        if not isinstance(exc, ReportedReleaseError):
            _console.print(f"[red]Error:[/red] {escape(str(exc))}")

    # None: an interrupt can arrive with no error in flight to show.
    @classmethod
    def print_in_flight(cls, exc: BaseException | None) -> None:
        """Show the error an interrupt is about to replace, as its handler would."""
        if isinstance(exc, ReleaseError):
            cls.print_unreported(exc)
        elif isinstance(exc, Exception):
            cls.print_crash(exc)

    @staticmethod
    def print_crash(exc: Exception) -> None:
        """Report an unexpected exception: one line if operational, else a trace."""
        line = OperationalFailure.report(exc)
        if OperationalFailure.covers(exc):
            _console.print(f"[red]Error:[/red] {escape(line)}")

    @staticmethod
    def print_timeout(
        exc: subprocess.TimeoutExpired, current_phase_num: int, resume_phase_num: int
    ) -> None:
        """Report a command that did not return: where, and how to resume."""
        raw_cmd = cast("object", exc.cmd)
        if isinstance(raw_cmd, list | tuple):
            parts = cast("Sequence[object]", raw_cmd)
            cmd_str = " ".join(map(str, parts))
        else:
            cmd_str = str(raw_cmd)
        phase_label = PhaseOrder.name_of(current_phase_num)
        resume_label = PhaseOrder.name_of(resume_phase_num)
        if resume_label == "unknown":
            resume_hint = (
                "Investigate the command; a phase could not be identified, "
                "so pick the earliest --resume-from that covers the failure."
            )
        else:
            resume_hint = (
                f"Investigate the command, then resume with "
                f"punt release --resume-from {resume_label}."
            )
        if phase_label == "unknown":
            location = "before the first phase started"
        else:
            location = f"in phase {current_phase_num} ({phase_label})"
        _console.print(
            f"[red]Error:[/red] release aborted {location} — "
            f"`{escape(RepoSlug.redacted(cmd_str))}` did not return "
            f"within {exc.timeout}s. {resume_hint}"
        )

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
