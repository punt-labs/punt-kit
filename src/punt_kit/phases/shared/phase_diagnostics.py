"""Record symmetric outcomes at each actual release phase boundary."""

from __future__ import annotations

import logging
from functools import wraps
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@final
class PhaseDiagnostics:
    """Bind phase outcome reporting to a fixed phase number."""

    __slots__ = ("_number",)

    _number: int

    def __new__(cls, number: int) -> Self:
        """Bind diagnostics to the release phase's stable number."""
        self = super().__new__(cls)
        self._number = number
        return self

    def __call__[**P, T](self, action: Callable[P, T]) -> Callable[P, T]:
        """Wrap the phase without changing its result or raised exception."""

        @wraps(action)
        def run(*args: P.args, **kwargs: P.kwargs) -> T:
            logger.info("Release phase started number=%d", self._number)
            try:
                result = action(*args, **kwargs)
            except BaseException:
                logger.info(
                    "Release phase finished number=%d outcome=error", self._number
                )
                raise
            logger.info("Release phase finished number=%d outcome=ok", self._number)
            return result

        return run
