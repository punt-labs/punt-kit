"""The one definition of each SHA pin that release propagation writes and verifies."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

_SHA = r"[0-9a-fA-F]{7,40}"

# What may follow a complete filename: not another word character, and not a
# dot or dash that continues it (``install.sh.bak``, ``install-all.sh-old``).
# Punctuation that merely ends a sentence (``install.sh.``) still closes it.
# One rule for every recognizer of an install file, here and in install_urls.
FILENAME_END = r"(?!\w|[.-]\w)"


@final
class ShaPin:
    """A commit SHA embedded between a fixed prefix and suffix in some text.

    The propagators rewrite the pin and Phase 11 reads it back, and both build
    the pin through the same classmethod (``install_all_entry`` or
    ``profile``), so what one writes the other recognizes by construction.
    """

    __slots__ = ("_pattern",)

    _pattern: re.Pattern[str]

    def __new__(cls, prefix: str, suffix: str) -> Self:
        """Build a pin from regex source for the text around the SHA.

        ``suffix`` ends in a filename, so the match must end the filename too.
        """
        self = super().__new__(cls)
        self._pattern = re.compile(rf"({prefix})({_SHA})({suffix}){FILENAME_END}")
        return self

    @classmethod
    def install_all_entry(cls, project_name: str) -> Self:
        """``$GH/<project>/<sha>/install.sh`` in the org's ``install-all.sh``."""
        return cls(rf"\$GH/{re.escape(project_name)}/", r"/install\.sh")

    @classmethod
    def profile(cls) -> Self:
        """``punt-labs/.github/<sha>/install-all.sh`` in the org profile README."""
        return cls(r"punt-labs/\.github/", r"/install-all\.sh")

    def repinned(
        self, content: str, sha: str, *, is_current: Callable[[str], bool]
    ) -> tuple[str, int]:
        """``content`` with each stale pin moved to ``sha``, and the pin count.

        A pin for which ``is_current`` is true is left exactly as written
        (still counted), so a full-length pin of the right commit is not
        rewritten to the short form. The caller supplies
        ``PinCurrency.is_current``: the one test of currency.
        """

        def move(found: re.Match[str]) -> str:
            if is_current(found.group(2)):
                return found.group(0)
            return f"{found.group(1)}{sha}{found.group(3)}"

        return self._pattern.subn(move, content)

    def all_shas(self, content: str) -> list[str]:
        """Every pinned SHA in ``content``, in order; empty is the answer for no pin."""
        return [found.group(2) for found in self._pattern.finditer(content)]
