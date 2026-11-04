"""The probe that imports a module from a built wheel, and the record it answers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, Self, cast

type ProbeKind = Literal["str", "absent", "type", "unlocated", "overwritten"]

# The probe frames its one answer as a line that starts with this marker and
# a nonce the parent picks per run, so nothing the package prints by accident
# can forge it. Code in the same process can always read the nonce; that limit
# is accepted.
_MARKER = "\x00PUNT_VERSION:"
_KINDS: frozenset[str] = frozenset(
    {"str", "absent", "type", "unlocated", "overwritten"}
)

# Run inside the isolated interpreter: argv[1] is the module, argv[2] the
# nonce, argv[3] the wheel's distribution name, none spliced into the code.
#
# - Before the import, the probe takes its arguments, clears ``sys.argv`` past
#   the program name, and binds everything it uses afterwards (``os.write``,
#   ``os._exit``, the path functions, ``importlib.metadata.files``, the
#   ``sysconfig`` paths, ``hashlib``, ``base64``, ``open``), so a package that
#   rewrites argv or replaces those while it imports cannot break or forge
#   the record. ``sys.orig_argv`` still holds the nonce: in-process code can
#   read it, which is within the accepted limit above.
# - Paths are compared with only their directory resolved, on both sides, so
#   a site-packages whose files are symlinks into uv's cache
#   (``UV_LINK_MODE=symlink``) still matches the distribution's file list.
# - ``origin`` is where the module was loaded from (a namespace package's
#   first ``__path__`` entry). With neither, the module is ``unlocated``: it
#   was replaced in ``sys.modules``, and nothing shows it came from the wheel.
#   ``in_stdlib`` is true when the origin is not a file path (built-in,
#   frozen), or lies under this interpreter's stdlib and not its
#   site-packages: a stdlib module of the same name shadowed the wheel.
#   ``from_wheel`` is true when the origin is one of the files the wheel's
#   distribution installed, or a directory holding one. When the origin is
#   such a file and its RECORD entry has a hash, the file on disk must still
#   match it; one that does not was ``overwritten`` by another distribution
#   installing the same path. A file with no RECORD hash is taken on its path.
#   All of this is worked out first, and ``__version__`` is read only from an
#   intact module that came from the wheel, so a shadow is what gets reported.
# - ``__version__`` is always read, however the module provides it (a binding,
#   a PEP 562 ``__getattr__``, a property on a swapped module class). It is
#   absent only when the read raises an ``AttributeError`` whose name and
#   object, taken as a pair, are ``__version__`` and this very module, or are
#   both unset (a ``__getattr__`` raising a bare message); and no class in the
#   module's MRO but ``ModuleType`` and ``object`` declares ``__version__``;
#   and, when the module defines ``__getattr__``, the error was raised in that
#   function's own frame. Any other exception exits non-zero: a lazy reader
#   breaking inside, including one that asks some other object (even
#   ``None``) for ``__version__``, a helper it calls, or a property.
# - A str subclass is reduced to a plain str, so it cannot choose its own repr;
#   any other type is reported by name.
# - The record goes straight to file descriptor 1, after a newline so it
#   starts its own line, and ``os._exit`` ends the process before atexit
#   handlers or buffered ``sys.stdout`` output can add to it.
PROBE_SOURCE = f"""\
import base64, hashlib, importlib, importlib.metadata, os, sys, sysconfig, types
name, nonce, dist = sys.argv[1], sys.argv[2], sys.argv[3]
del sys.argv[1:]
_write, _exit, _realpath, _isabs, _dirname, _basename, _sep = (
    os.write, os._exit, os.path.realpath, os.path.isabs,
    os.path.dirname, os.path.basename, os.sep,
)
_files, _paths = importlib.metadata.files, sysconfig.get_paths()
_hash, _b64, _open, _ModuleType = (
    hashlib.new, base64.urlsafe_b64encode, open, types.ModuleType
)
def located(path):
    return _realpath(_dirname(path)) + _sep + _basename(path)
module = importlib.import_module(name)
spec = getattr(module, '__spec__', None)
origin = getattr(spec, 'origin', None)
if not origin:
    origin = next(iter(getattr(module, '__path__', None) or []), '')
origin = str(origin)
where = located(origin) if _isabs(origin) else ''
def under(root):
    return where == root or where.startswith(root + _sep)
def under_path(key):
    return under(_realpath(_paths[key]))
in_stdlib = bool(origin) and (not where or (
    (under_path('stdlib') or under_path('platstdlib'))
    and not (under_path('purelib') or under_path('platlib'))
))
installed = [(located(str(f.locate())), f) for f in (_files(dist) or [])]
from_wheel = bool(where) and any(
    path == where or path.startswith(where + _sep) for path, _ in installed
)
own = next((f for path, f in installed if path == where), None)
intact = True
if from_wheel and own is not None and own.hash is not None:
    digest = _hash(own.hash.mode)
    with _open(where, 'rb') as handle:
        digest.update(handle.read())
    intact = _b64(digest.digest()).rstrip(b'=').decode() == own.hash.value
kind, value = ('unlocated' if not origin else 'absent'), ''
if from_wheel and not intact:
    kind = 'overwritten'
elif from_wheel:
    try:
        found = module.__version__
    except AttributeError as error:
        n, o = getattr(error, 'name', None), getattr(error, 'obj', None)
        pair = (n == '__version__' and o is module) or (n is None and o is None)
        declared = any(
            '__version__' in vars(klass)
            for klass in type(module).__mro__
            if klass is not _ModuleType and klass is not object
        )
        getter = vars(module).get('__getattr__')
        frame = error.__traceback__
        while frame is not None and frame.tb_next is not None:
            frame = frame.tb_next
        raised_by_getter = getter is None or (
            frame is not None
            and frame.tb_frame.f_code is getattr(getter, '__code__', None)
        )
        if not (pair and not declared and raised_by_getter):
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
