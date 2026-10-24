"""The listing forms of git ``branch``, ``tag`` and ``remote``, which write no ref."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class ReadOnlyForm:
    """The options of one git verb that only list, and never write a ref.

    ``branch``, ``tag`` and ``remote`` update refs in one form and only read
    them in another. The listing form runs no hook, so it keeps the short
    budget. A word outside the listing options, or a positional that is not
    the value of one, means the form may write: over-approximating costs only
    a longer ceiling.
    """

    flags: frozenset[str]
    value_flags: frozenset[str] = frozenset()
    # A first word after which anything is read-only (``remote get-url ...``).
    subcommands: frozenset[str] = frozenset()

    def covers(self, words: Sequence[str]) -> bool:
        """True when ``words`` are listing options, their values, and nothing else."""
        if words and words[0] in self.subcommands:
            return True
        index = 0
        while index < len(words):
            step = self._step(words, index)
            if step == 0:
                return False
            index += step
        return True

    def _step(self, words: Sequence[str], index: int) -> int:
        """How many words the listing option at ``index`` takes; 0 if it is not one."""
        word = words[index]
        name = word.split("=", 1)[0]
        if name in self.value_flags:
            return 2 if self._has_value(words, index) else 1
        return 1 if name in self.flags or self._is_flag_cluster(word) else 0

    @staticmethod
    def _has_value(words: Sequence[str], index: int) -> bool:
        """True when the option at ``index`` takes the next word as its value."""
        return (
            "=" not in words[index]
            and index + 1 < len(words)
            and not words[index + 1].startswith("-")
        )

    def _is_flag_cluster(self, word: str) -> bool:
        """True for a short-option cluster such as ``-vv`` or ``-av``."""
        return (
            word.startswith("-")
            and not word.startswith("--")
            and len(word) > 2
            and all(f"-{letter}" in self.flags for letter in word[1:])
        )


_LISTING_VALUE_OPTIONS = frozenset(
    {
        "--contains",
        "--format",
        "--merged",
        "--no-contains",
        "--no-merged",
        "--points-at",
        "--sort",
    }
)
_LISTING_FLAGS = frozenset(
    {"--column", "--ignore-case", "--list", "--no-column", "-i", "-l"}
)
READ_ONLY_FORMS: dict[str, ReadOnlyForm] = {
    "branch": ReadOnlyForm(
        _LISTING_FLAGS
        | {
            "--all",
            "--color",
            "--no-color",
            "--remotes",
            "--show-current",
            "--verbose",
            "-a",
            "-r",
            "-v",
        },
        _LISTING_VALUE_OPTIONS | {"--abbrev"},
    ),
    "tag": ReadOnlyForm(_LISTING_FLAGS, _LISTING_VALUE_OPTIONS),
    "remote": ReadOnlyForm(
        frozenset({"--verbose", "-v"}), subcommands=frozenset({"get-url"})
    ),
}
