"""The probe that imports a module from a built wheel, and the record it answers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, Self, cast

type ProbeKind = Literal["str", "absent", "type", "unlocated"]

# The probe frames its one answer as a line that starts with this marker and
# a nonce the parent picks per run, so nothing the package prints by accident
# can forge it. Code in the same process can always read the nonce; that limit
# is accepted.
_MARKER = "\x00PUNT_VERSION:"
_KINDS: frozenset[str] = frozenset({"str", "absent", "type", "unlocated"})

# Run inside the isolated interpreter: argv[1] is the module, argv[2] the
# nonce, argv[3] the wheel's distribution name, none spliced into the code.
#
# - Before the import, the probe takes its arguments, clears ``sys.argv`` past
#   the program name, and binds everything it uses afterwards (``os.write``,
#   ``os._exit``, ``os.path.realpath``, ``importlib.metadata.files``, the
#   ``sysconfig`` paths), so a package that rewrites argv or replaces those
#   while it imports cannot break or forge the record.
# - ``origin`` is where the module was loaded from (a namespace package's
#   first ``__path__`` entry). With neither, the module is ``unlocated``: it
#   was replaced in ``sys.modules``, and nothing shows it came from the wheel.
#   ``in_stdlib`` is true when the origin is not a file path (built-in,
#   frozen), or lies under this interpreter's stdlib and not its
#   site-packages: a stdlib module of the same name shadowed the wheel.
#   ``from_wheel`` is true when the origin is one of the files the wheel's
#   distribution installed, or a directory holding one. All three are worked
#   out first, and ``__version__`` is read only from a module that came from
#   the wheel, so a shadow is what gets reported.
# - ``__version__`` is always read, however the module provides it (a binding,
#   a PEP 562 ``__getattr__``, a property on a swapped module class). It is
#   absent only when the read raises an ``AttributeError`` about
#   ``__version__`` on this module, or one that names neither (a
#   ``__getattr__`` raising a bare message). Any other exception, a lazy
#   reader breaking inside included, exits non-zero.
# - A str subclass is reduced to a plain str, so it cannot choose its own repr;
#   any other type is reported by name.
# - The record goes straight to file descriptor 1, after a newline so it
#   starts its own line, and ``os._exit`` ends the process before atexit
#   handlers or buffered ``sys.stdout`` output can add to it.
PROBE_SOURCE = f"""\
import importlib, importlib.metadata, os, sys, sysconfig
name, nonce, dist = sys.argv[1], sys.argv[2], sys.argv[3]
del sys.argv[1:]
_write, _exit, _realpath, _isabs, _sep = (
    os.write, os._exit, os.path.realpath, os.path.isabs, os.sep
)
_files, _paths = importlib.metadata.files, sysconfig.get_paths()
module = importlib.import_module(name)
spec = getattr(module, '__spec__', None)
origin = getattr(spec, 'origin', None)
if not origin:
    origin = next(iter(getattr(module, '__path__', None) or []), '')
origin = str(origin)
where = _realpath(origin) if _isabs(origin) else ''
def under(root):
    return where == root or where.startswith(root + _sep)
def under_path(key):
    return under(_realpath(_paths[key]))
in_stdlib = bool(origin) and (not where or (
    (under_path('stdlib') or under_path('platstdlib'))
    and not (under_path('purelib') or under_path('platlib'))
))
installed = [_realpath(str(f.locate())) for f in (_files(dist) or [])]
from_wheel = bool(where) and any(
    path == where or path.startswith(where + _sep) for path in installed
)
kind, value = ('unlocated' if not origin else 'absent'), ''
if from_wheel:
    try:
        found = module.__version__
    except AttributeError as error:
        if getattr(error, 'name', None) not in (None, '__version__'):
            raise
        if getattr(error, 'obj', None) not in (None, module):
            raise
    else:
        if isinstance(found, str):
            kind, value = 'str', str.__str__(found)
        else:
            kind, value = 'type', type(found).__name__
fields = (kind, value, origin, in_stdlib, from_wheel)
record = {_MARKER!r} + nonce + ascii(fields)
_write(1, ('\\n' + record + '\\n').encode('ascii'))
_exit(0)
"""


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    """What the probe saw: the kind of ``__version__``, and where it imported from.

    ``value`` is the version for ``"str"``, the type name for ``"type"``, and
    empty for ``"absent"`` and ``"unlocated"``.
    """

    kind: ProbeKind
    value: str
    origin: str
    in_stdlib: bool
    from_wheel: bool

    @classmethod
    def lines(cls, stdout: str, nonce: str) -> list[str]:
        """The record payloads in ``stdout`` that carry ``nonce``."""
        head = f"{_MARKER}{nonce}"
        lines = stdout.split("\n")
        return [line.removeprefix(head) for line in lines if line.startswith(head)]

    # None: a payload the probe could not have written; the caller fails on it.
    @classmethod
    def parse(cls, payload: str) -> Self | None:
        """The record ``payload`` spells; ``None`` when it is malformed."""
        try:
            fields: object = ast.literal_eval(payload)
        except (ValueError, SyntaxError):
            return None
        match fields:
            case (
                str() as kind,
                str() as value,
                str() as origin,
                bool() as in_stdlib,
                bool() as from_wheel,
            ) if kind in _KINDS:
                return cls(
                    cast("ProbeKind", kind), value, origin, in_stdlib, from_wheel
                )
            case _:
                return None
