"""The probe that imports a module from a built wheel, and the record it answers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, Self, cast

type ProbeKind = Literal[
    "str", "absent", "type", "raised", "unlocated", "overwritten", "malformed"
]

# The probe frames its one answer as a line that starts with this marker and
# a nonce the parent picks per run, so nothing the package prints by accident
# can forge it. Code in the same process can always read the nonce; that limit
# is accepted.
_MARKER = "\x00PUNT_VERSION:"
_KINDS: frozenset[str] = frozenset(
    {"str", "absent", "type", "raised", "unlocated", "overwritten", "malformed"}
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
#   distribution installed, or a directory holding one.
# - Every file the distribution's RECORD lists under the module's own path
#   (its package directory, or its single file) is checked. Where RECORD
#   lists a path twice, the hashed entry wins. A code file (``.py``, ``.so``,
#   ``.pyd``) with no hash is ``malformed``; a hashed file whose bytes on
#   disk no longer match was ``overwritten`` by another distribution
#   installing the same path. Either names the file.
# - All of that comes first, and ``__version__`` is read only from an intact
#   module that came from the wheel, so a shadow is what gets reported.
# - ``__version__`` is ``absent`` only when the module binds neither it nor
#   ``__getattr__`` and is a plain ``ModuleType``, not a subclass: then
#   nothing can compute it. ``hasattr`` is never used. In every other case
#   the attribute is read directly; any exception is reported as ``raised``
#   (its type and message) and the probe exits non-zero.
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
_hash, _b64, _open, _ModuleType, _type, _str, _vars = (
    hashlib.new, base64.urlsafe_b64encode, open, types.ModuleType, type, str, vars
)
def located(path):
    return _realpath(_dirname(path)) + _sep + _basename(path)
def answer(kind, value, code=0):
    fields = (kind, value, origin, in_stdlib, from_wheel)
    record = {_MARKER!r} + nonce + ascii(fields)
    _write(1, ('\\n' + record + '\\n').encode('ascii'))
    _exit(code)
origin, in_stdlib, from_wheel = '', False, False
module = importlib.import_module(name)
spec = getattr(module, '__spec__', None)
origin = getattr(spec, 'origin', None)
if not origin:
    origin = next(iter(getattr(module, '__path__', None) or []), '')
origin = _str(origin)
if not origin:
    answer('unlocated', '')
where = located(origin) if _isabs(origin) else ''
def under(path, root):
    return path == root or path.startswith(root + _sep)
def under_path(key):
    return under(where, _realpath(_paths[key]))
in_stdlib = not where or (
    (under_path('stdlib') or under_path('platstdlib'))
    and not (under_path('purelib') or under_path('platlib'))
)
recorded = {{}}
for entry in _files(dist) or []:
    path = located(_str(entry.locate()))
    if path not in recorded or recorded[path].hash is None:
        recorded[path] = entry
from_wheel = bool(where) and any(under(path, where) for path in recorded)
if in_stdlib or not from_wheel:
    answer('absent', '')
own = _dirname(where) if _basename(where).startswith('__init__.') else where
for path, entry in sorted(recorded.items()):
    if not under(path, own):
        continue
    if entry.hash is None:
        if path.endswith(('.py', '.so', '.pyd')):
            answer('malformed', path)
        continue
    digest = _hash(entry.hash.mode)
    with _open(path, 'rb') as handle:
        digest.update(handle.read())
    if _b64(digest.digest()).rstrip(b'=').decode() != entry.hash.value:
        answer('overwritten', path)
names = _vars(module)
if (
    '__version__' not in names
    and '__getattr__' not in names
    and _type(module) is _ModuleType
):
    answer('absent', '')
try:
    found = module.__version__
except BaseException as error:
    try:
        message = _str(error)
    except BaseException:
        message = '<unprintable>'
    answer('raised', _type(error).__name__ + ': ' + message, 1)
if isinstance(found, _str):
    answer('str', _str.__str__(found))
answer('type', _type(found).__name__)
"""


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    """What the probe saw: the kind of ``__version__``, and where it imported from.

    ``value`` is the version for ``"str"``, the type name for ``"type"``,
    ``"<ExcType>: <message>"`` for ``"raised"``, the offending file for
    ``"overwritten"`` and ``"malformed"``, and empty otherwise.
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
