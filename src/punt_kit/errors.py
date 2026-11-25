"""Expose the expected failure types used by checkout operations."""

from __future__ import annotations

from dataclasses import dataclass, field

from punt_kit.phases.shared.errors import ReleaseError as ReleaseError


@dataclass(eq=False, slots=True)
class CommandFailure(SystemExit):
    """Report details while preserving the engine's unsuccessful exit."""

    message: str
    # Different commands supply different partial result schemas.
    details: dict[str, object] = field(default_factory=dict[str, object])

    def __post_init__(self) -> None:
        """Set the exit code expected by existing engine callers."""
        SystemExit.__init__(self, 1)
