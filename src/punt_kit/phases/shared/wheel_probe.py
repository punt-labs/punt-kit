"""The probe that imports a module from a built wheel, and the record it answers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, Self, cast

type ProbeKind = Literal["str", "absent", "type"]

# The probe frames its one answer as a line that starts with this marker and
# a nonce the parent picks per run, so nothing the package prints can forge it.
_MARKER = "\x00PUNT_VERSION:"
_KINDS: frozenset[str] = frozenset({"str", "absent", "type"})

# Run inside the isolated interpreter: argv[1] is the module, argv[2] the
# nonce, neither spliced into the code.
#
# - ``__version__`` is absent only when the module neither binds it nor
#   defines a PEP 562 ``__getattr__``; otherwise the attribute is read, so a
#   lazy reader that raises exits non-zero.
# - A str subclass is reduced to a plain str, so it cannot choose its own repr;
#   any other type is reported by name.
# - ``origin`` is where the module was loaded from (a namespace package's
#   first ``__path__`` entry). ``in_stdlib`` is true when that is not a file
#   path, or lies under this interpreter's stdlib and not its site-packages:
#   a stdlib module of the same name shadowed the wheel.
# - The record goes straight to file descriptor 1, after a newline so it
#   starts its own line, and ``os._exit`` ends the process before atexit
#   handlers or buffered ``sys.stdout`` output can add to it.
PROBE_SOURCE = f"""\
import importlib, os, sys, sysconfig
module = importlib.import_module(sys.argv[1])
names = vars(module)
if '__version__' not in names and '__getattr__' not in names:
    kind, value = 'absent', ''
else:
    found = module.__version__
    if isinstance(found, str):
        kind, value = 'str', str.__str__(found)
    else:
        kind, value = 'type', type(found).__name__
spec = getattr(module, '__spec__', None)
origin = getattr(spec, 'origin', None)
if not origin:
    origin = next(iter(getattr(module, '__path__', [])), '')
origin = str(origin)
where = os.path.realpath(origin) if os.path.isabs(origin) else ''
paths = sysconfig.get_paths()
def under(key):
    root = os.path.realpath(paths[key])
    return where == root or where.startswith(root + os.sep)
in_stdlib = not where or (
    (under('stdlib') or under('platstdlib'))
    and not (under('purelib') or under('platlib'))
)
record = {_MARKER!r} + sys.argv[2] + ascii((kind, value, origin, in_stdlib))
os.write(1, ('\\n' + record + '\\n').encode('ascii'))
os._exit(0)
"""


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    """What the probe saw: the kind of ``__version__``, and where it imported from.

    ``value`` is the version for ``"str"``, the type name for ``"type"``, and
    empty for ``"absent"``.
    """

    kind: ProbeKind
    value: str
    origin: str
    in_stdlib: bool

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
            case (str() as kind, str() as value, str() as origin, bool() as stdlib) if (
                kind in _KINDS
            ):
                return cls(cast("ProbeKind", kind), value, origin, stdlib)
            case _:
                return None
