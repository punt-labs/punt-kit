"""The files a built wheel installs, and whether they make up a given module."""

from __future__ import annotations

import re
import zipfile
from typing import TYPE_CHECKING, Literal, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# "module": the wheel ships it. "empty": a directory of it with no Python or
# extension file in it. "missing": nothing of it at all.
type Shipping = Literal["module", "empty", "missing"]

# A wheel's ``<dist>.data/purelib/`` and ``.../platlib/`` install to
# site-packages just as the wheel root does.
_INSTALLED_DATA = re.compile(r"^[^/]+\.data/(?:purelib|platlib)/")
_CODE_SUFFIXES = (".py", ".so", ".pyd")


@final
class WheelContents:
    """The paths a wheel installs into site-packages, relative to it."""

    __slots__ = ("_paths",)

    _paths: tuple[str, ...]

    def __new__(cls, names: Iterable[str]) -> Self:
        self = super().__new__(cls)
        self._paths = tuple(_INSTALLED_DATA.sub("", name, count=1) for name in names)
        return self

    @classmethod
    def of(cls, wheel: Path) -> Self:
        """The contents of ``wheel``; ``zipfile.BadZipFile`` if it is not a zip."""
        with zipfile.ZipFile(wheel) as archive:
            return cls(archive.namelist())

    def top_level(self) -> tuple[str, ...]:
        """The top-level importable names the wheel installs, sorted.

        Top-level directories count, except ``*.dist-info`` and the
        ``*.data`` schemes that do not install to site-packages; so do
        top-level ``.py``, ``.so`` and ``.pyd`` files, by module name.
        """
        names: set[str] = set()
        for path in self._paths:
            head, slash, _ = path.partition("/")
            if slash:
                if not head.endswith((".dist-info", ".data")):
                    names.add(head)
            elif head.endswith(_CODE_SUFFIXES):
                names.add(head.split(".", 1)[0])
        return tuple(sorted(names))

    def shipping(self, module: str) -> Shipping:
        """How the wheel ships the dotted ``module``.

        A module file (``.py``, or an extension such as ``.so``, ``.pyd`` or
        ``.cpython-313-x86_64-linux-gnu.so``) or a directory holding at least
        one such file counts; a directory of data alone does not.
        """
        path = module.replace(".", "/")
        extension = re.compile(rf"{re.escape(path)}(?:\.[^/.]+)?\.(?:so|pyd)")
        if any(
            name == f"{path}.py" or extension.fullmatch(name) for name in self._paths
        ):
            return "module"
        inside = [name for name in self._paths if name.startswith(f"{path}/")]
        if not inside:
            return "missing"
        return "module" if any(n.endswith(_CODE_SUFFIXES) for n in inside) else "empty"
