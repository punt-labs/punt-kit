"""The one definition of each SHA pin that release propagation writes and verifies."""

from __future__ import annotations

import re
from typing import Self, final

_SHA = r"[0-9a-fA-F]{7,40}"


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
        """Build a pin from regex source for the text around the SHA."""
        self = super().__new__(cls)
        self._pattern = re.compile(rf"({prefix})({_SHA})({suffix})")
        return self

    @classmethod
    def install_all_entry(cls, project_name: str) -> Self:
        """``$GH/<project>/<sha>/install.sh`` in the org's ``install-all.sh``."""
        return cls(rf"\$GH/{re.escape(project_name)}/", r"/install\.sh")

    @classmethod
    def profile(cls) -> Self:
        """``punt-labs/.github/<sha>/install-all.sh`` in the org profile README."""
        return cls(r"punt-labs/\.github/", r"/install-all\.sh")

    def repinned(self, content: str, sha: str) -> tuple[str, int]:
        """``content`` with every pin moved to ``sha``, and how many there were."""
        return self._pattern.subn(rf"\g<1>{sha}\g<3>", content)

    def all_shas(self, content: str) -> list[str]:
        """Every pinned SHA in ``content``, in order; empty is the answer for no pin."""
        return [found.group(2) for found in self._pattern.finditer(content)]
