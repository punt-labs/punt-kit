"""The numbered release phases and the names ``--resume-from`` accepts for them."""

from __future__ import annotations

from typing import ClassVar, final


@final
class PhaseOrder:
    """The canonical phase order: the one source of the number-to-name mapping.

    Index + 1 is the phase number; the name at that index is the string the
    operator passes to ``--resume-from``. Every lookup derives from ``ORDER``
    so the names, the numbers and the "not confirmed landed" list cannot drift
    apart.
    """

    __slots__ = ()

    ORDER: ClassVar[tuple[str, ...]] = (
        "preflight",
        "bump",
        "build",
        "release-pr",
        "tag",
        "ci",
        "github-release",
        "pypi",
        "post-release",
        "propagate",
        "verify",
    )

    # Name -> number, plus the ``release`` alias for muscle memory.
    NUMBERS: ClassVar[dict[str, int]] = {
        **{name: i + 1 for i, name in enumerate(ORDER)},
        "release": ORDER.index("release-pr") + 1,
    }

    @classmethod
    def name_of(cls, number: int) -> str:
        """The ``--resume-from`` name for a phase number, or ``"unknown"``.

        Only in-range numbers map to a name; 0 (nothing running yet) and
        anything outside 1..len(ORDER) fall through to ``"unknown"`` so the
        diagnosis path never fabricates a phase that would not round-trip
        through ``--resume-from``.
        """
        if 1 <= number <= len(cls.ORDER):
            return cls.ORDER[number - 1]
        return "unknown"

    @classmethod
    def unlanded_from(cls, number: int) -> tuple[str, ...]:
        """Phase names from ``number`` through the end.

        The portion of the pipeline not confirmed to land when a release stops
        early: the phase that was running, plus everything after it.
        """
        if not 1 <= number <= len(cls.ORDER):
            return cls.ORDER
        return cls.ORDER[number - 1 :]
