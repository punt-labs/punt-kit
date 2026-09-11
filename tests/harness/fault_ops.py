"""A scriptable ``ReleaseOps`` double for release-engine failure-path tests.

Wraps a real ``_run`` (so real git calls still hit a real git binary — see
``docs/design-release-failure-harness.md`` §1b) plus a routing table of
``FaultRule``\\ s that say "the Nth command matching this argv prefix returns
this scripted response / raises this exception, then let the rest through."

``gh`` is deny-by-default: an unmatched, non-``git`` command that isn't on the
``passthrough`` allowlist is a hard ``AssertionError``, not a silent fall
through to the network — a test that forgot a later phase also calls ``gh``
must not have that call quietly reach production GitHub (§2a).
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict, cast, final

from punt_kit.phases.shared.reporter import reporter
from punt_kit.phases.shared.timeouts import DEFAULT_RUN

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Final, NoReturn, Self

# tests/harness/fault_ops.py -> tests/ -> tests/fixtures/gh — Wave 1's
# recorded-fixture library (§2b). Wave 0 depends only on this loader
# mechanism, not on that library existing yet; its own unit test points
# ``from_fixture`` at a fixture file it creates inline instead.
_DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "gh"


class RunFn(Protocol):
    """The call shape every real ``ReleaseOps.run`` implementation shares.

    Matched structurally so ``FaultInjectingOps`` can wrap a bare function
    (``release_mod._run``) directly, with no adapter class in between.
    """

    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...


class _FixtureEnvelope(TypedDict):
    """The subset of a recorded ``gh`` fixture envelope (§2b) that a scripted
    response needs — ``cmd`` and ``_meta`` are recording-time metadata, not
    part of what a ``FaultRule`` hands back to the release engine.
    """

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class CompletedProcessSpec:
    """The scripted shape of a subprocess result, before ``argv`` is known.

    Reusable across every match of a ``responses`` sequence — ``args`` is
    filled in at match time from the call that actually triggered it, not
    baked into the spec itself.
    """

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    def to_completed_process(
        self, cmd: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        """Render this spec against the argv that matched it."""
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def _matches_argv_prefix(cmd: Sequence[str], prefix: Sequence[str]) -> bool:
    """True if ``cmd`` starts with ``prefix``, comparing element 0 by basename.

    Production ``gh``/``git`` call sites resolve the binary via
    ``shutil.which(...)``, so ``cmd[0]`` is an absolute path like
    ``/usr/bin/gh`` at runtime — never the bare string a test naturally
    writes into ``FaultRule.match`` or ``FaultInjectingOps``'s
    ``passthrough``. Every other element compares literally; this is the
    only normalization the router applies.
    """
    if not prefix or not cmd or len(cmd) < len(prefix):
        return False
    if Path(cmd[0]).name != prefix[0]:
        return False
    return list(cmd[1 : len(prefix)]) == list(prefix[1:])


@final
class _Unset:
    """Sentinel distinguishing "caller passed nothing" from any real value,
    including ``None`` — ``times=None`` is itself meaningful ("every
    remaining match"), so a bare ``None`` default cannot also mean "derive
    the budget from ``responses``."
    """

    __slots__ = ()


_UNSET: Final = _Unset()


@dataclass(slots=True)
class FaultRule:
    """One scripted response for commands matching an argv prefix.

    Exactly one of ``response``, ``responses``, or ``raises`` must be given
    — a rule that matches but doesn't know what to do is a test bug, not a
    valid configuration.
    """

    match: Sequence[str]
    skip: int = 0
    times: InitVar[int | None | _Unset] = _UNSET
    response: CompletedProcessSpec | None = None
    responses: Sequence[CompletedProcessSpec] | None = None
    raises: type[BaseException] | BaseException | None = None
    _times: int | None = field(init=False, repr=False)
    _resolved_responses: tuple[CompletedProcessSpec, ...] = field(
        init=False, repr=False
    )
    _seen: int = field(default=0, init=False, repr=False)
    _consumed: int = field(default=0, init=False, repr=False)
    _interrupt_event: threading.Event | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self, times: int | None | _Unset) -> None:
        if not self.match:
            raise ValueError("match must be a non-empty argv prefix")
        if not self.match[0]:
            raise ValueError("match[0] must be a non-empty executable name")
        if self.skip < 0:
            raise ValueError(f"skip must be >= 0, got {self.skip}")
        if self.responses is not None and len(self.responses) == 0:
            raise ValueError("responses must be non-empty when given")
        outcomes = sum(
            x is not None for x in (self.response, self.responses, self.raises)
        )
        if outcomes != 1:
            raise ValueError(
                "FaultRule needs exactly one of response, responses, or raises "
                f"— got {outcomes}"
            )
        if isinstance(times, _Unset):
            # Unset derives to "one response per element of `responses`" (so
            # the two-element OPEN->MERGED example consumes exactly two
            # matches without a separate `times=2`), or `1` for the single
            # response/raises case — see FaultRule's own docstring above.
            self._times = len(self.responses) if self.responses is not None else 1
        else:
            if times is not None and times < 1:
                raise ValueError(f"times must be >= 1 or None, got {times}")
            self._times = times
        self._resolved_responses = (
            tuple(self.responses)
            if self.responses is not None
            else (self.response,)
            if self.response is not None
            else ()
        )

    def matches_argv(self, cmd: Sequence[str]) -> bool:
        """Pure argv-prefix check — mutates no state."""
        return _matches_argv_prefix(cmd, self.match)

    def interrupt_after(self, event: threading.Event) -> None:
        """Arm this rule: flip ``event`` the instant a match of this rule
        completes.

        Anchored to a rule match rather than a raw call count — each phase
        issues a variable number of calls depending on preflight/retry
        state, and Phase 9/10 run concurrently, so no global call number
        reliably means "this rule just matched" (§2c).
        """
        self._interrupt_event = event

    def try_consume(
        self, cmd: Sequence[str]
    ) -> subprocess.CompletedProcess[str] | None:
        """Attempt to consume one call against this rule.

        Returns ``None`` when this rule does not currently claim ``cmd`` —
        argv mismatch, still inside its ``skip`` window, or already
        exhausted — so the caller falls through to the next rule, or to
        real/passthrough dispatch. Raises the scripted exception, if any,
        instead of returning. Must be called with the router's lock held:
        it mutates the shared ``skip``/``times`` counters.
        """
        if not self.matches_argv(cmd):
            return None
        if self._seen < self.skip:
            self._seen += 1
            return None
        if self._times is not None and self._consumed >= self._times:
            return None
        self._consumed += 1
        if self.raises is not None:
            # A raising match never "returns" — §2c fires the interrupt as a
            # side effect of the matched call *returning*, so an anchored
            # rule that raises must not signal completion at all.
            raise self.raises
        spec = self._resolved_responses[
            (self._consumed - 1) % len(self._resolved_responses)
        ]
        result = spec.to_completed_process(cmd)
        if self._interrupt_event is not None:
            self._interrupt_event.set()
        return result

    @classmethod
    def from_fixture(
        cls, name: str, *, fixtures_dir: Path = _DEFAULT_FIXTURES_DIR
    ) -> CompletedProcessSpec:
        """Load a recorded ``gh`` fixture envelope (§2b) as a scripted
        response — assign the result to ``response=`` instead of writing an
        inline dict literal.

        ``fixtures_dir`` defaults to the recorded-fixture library's home;
        overridable so a test can point at a fixture file it creates itself.
        """
        raw: object = json.loads((fixtures_dir / name).read_text())
        # Wire boundary — json.loads yields `object` until narrowed to the
        # envelope shape a recorded fixture always carries (PY-TS-14).
        envelope = cast("_FixtureEnvelope", raw)
        return CompletedProcessSpec(
            returncode=envelope["returncode"],
            stdout=envelope["stdout"],
            stderr=envelope["stderr"],
        )


@final
class FaultInjectingOps:
    """A ``ReleaseOps`` that delegates to a real ``_run``, except for
    scripted faults.

    Unmatched ``git`` commands still delegate to the real ``_run`` (git
    plumbing is cheap ground truth — §1b). An unmatched non-``git`` command
    not covered by ``passthrough`` is a hard ``AssertionError``: ``gh`` is
    the one command class that reaches the live network and a real GitHub
    org, so a forgotten rule must not let a later call reach production
    unnoticed (§2a's deny-by-default posture).
    """

    __slots__ = ("_real_run", "_rules", "_passthrough", "_lock")

    _real_run: RunFn
    _rules: list[FaultRule]
    _passthrough: list[list[str]]
    _lock: threading.Lock

    def __new__(
        cls,
        *,
        real_run: RunFn,
        rules: Sequence[FaultRule],
        passthrough: Sequence[Sequence[str]] = (),
    ) -> Self:
        self = super().__new__(cls)
        self._real_run = real_run
        self._rules = list(rules)
        self._passthrough = [list(prefix) for prefix in passthrough]
        for prefix in self._passthrough:
            # Same class of bug as an empty FaultRule.match (§2a): a
            # dead-on-arrival prefix that can never admit anything would
            # silently make a test's "this call is allowed through" claim
            # false, surfacing only as an unrelated deny-by-default failure.
            if not prefix:
                raise ValueError("passthrough prefix must be non-empty")
            if not prefix[0]:
                raise ValueError(
                    "passthrough prefix[0] must be a non-empty executable name"
                )
        self._lock = threading.Lock()
        return self

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if not cmd:
            raise ValueError("cmd must be a non-empty argv list")
        with self._lock:
            for rule in self._rules:
                result = rule.try_consume(cmd)
                if result is not None:
                    return result
        if Path(cmd[0]).name == "git" or self._passthrough_match(cmd):
            return self._real_run(
                cmd, cwd=cwd, timeout=timeout, check=check, capture=capture
            )
        raise AssertionError(
            f"unmatched network command in a fault-injection test: {cmd!r} — "
            "add a FaultRule or an explicit passthrough prefix"
        )

    def _passthrough_match(self, cmd: Sequence[str]) -> bool:
        # A passthrough entry is an argv prefix with FaultRule.match's own
        # semantics (basename for cmd[0], exact for the rest) — never a bare
        # binary name, so sanctioning one invocation shape can't sanction
        # every other invocation of the same binary.
        return any(_matches_argv_prefix(cmd, prefix) for prefix in self._passthrough)

    def ok(self, msg: str) -> None:
        reporter.ok(msg)

    def info(self, msg: str) -> None:
        reporter.info(msg)

    def dry(self, msg: str) -> None:
        reporter.dry(msg)

    def warn(self, msg: str) -> None:
        reporter.warn(msg)

    def fail(self, msg: str) -> NoReturn:
        reporter.fail(msg)
