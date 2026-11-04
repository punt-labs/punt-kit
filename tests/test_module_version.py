"""Tests for classifying a Python module's ``__version__`` from its syntax tree."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.module_version import (
    ComputedVersion,
    LiteralVersion,
    ModuleVersion,
    UnpinnableVersionError,
)

_TYPE_CHECKING_ELSE = (
    "from typing import TYPE_CHECKING\n"
    "if TYPE_CHECKING:\n    __version__: str\n"
    'else:\n    __version__ = "0.1.0"\n'
)
_LUX_FALLBACK = (
    "from importlib.metadata import PackageNotFoundError, version\n\n"
    'try:\n    __version__ = version("punt-lux")\n'
    'except PackageNotFoundError:\n    __version__ = "0.0.0"\n'
)
_PARSE = "from ._util import parse\n"
_TRY_EXCEPT = (
    "try:\n    from ._v import __version__\n"
    'except ImportError:\n    __version__ = "0.1.0"\n'
)


@pytest.mark.parametrize(
    "text",
    [
        "from punt_vox.paths import installed_version\n\n"
        "__version__ = installed_version()\n",
        'from importlib.metadata import version\n__version__ = version("x")\n',
        'import importlib.metadata\n__version__ = importlib.metadata.version("x")\n',
        'from importlib import metadata\n__version__ = metadata.version("x")\n',
        'import importlib_metadata\n__version__ = importlib_metadata.version("x")\n',
        'import importlib.metadata as md\n__version__ = md.version("x")\n',
        "from importlib.metadata import version\nfrom ._dist import DIST\n"
        "__version__ = version(DIST)\n",
        "from importlib.metadata import version\nfrom ._dist import DIST\n"
        "__version__ = version(name=DIST)\n",
        "try:\n    from importlib.metadata import version\n"
        "except ImportError:\n    from importlib_metadata import version\n"
        '__version__ = version("x")\n',
        "from .paths import installed_version as iv\n__version__ = iv()\n",
        "from .paths import installed_version\n"
        "VERSION = installed_version()\n__version__ = VERSION\n",
        'from importlib.metadata import version\n__version__ = version("punt-x")\n',
        'from importlib.metadata import version\nNAME = "punt-x"\n'
        "__version__ = version(NAME)\n",
        "import pkg._version as _version\n__version__ = _version.get_versions()\n",
        'from importlib import metadata as md\n__version__ = md.version("x")\n',
        "import importlib\nimport importlib.metadata\n"
        '__version__ = importlib.metadata.version("x")\n',
        "import importlib\nfrom importlib.metadata import version\n"
        '__version__ = version("punt-biff")\n',
        "from importlib.metadata import version\n__version__ = version(__name__)\n",
        "import importlib.metadata\n"
        "__version__ = importlib.metadata.version(__package__)\n",
        'import os\n__version__ = os.getenv("PKG_VERSION", "x")\n',
        'import os.path\n__version__ = os.getenv("V", "x")\n',
        "import importlib_metadata.foo\nfrom ._dist import DIST\n"
        "__version__ = importlib_metadata.version(DIST)\n",
        "try:\n    from importlib import metadata\n"
        "except ImportError:\n    import importlib_metadata as metadata\n"
        '__version__ = metadata.version("x")\n',
    ],
    ids=[
        "helper-call",
        "metadata-call",
        "dotted-metadata-call",
        "imported-submodule-call",
        "backport-call",
        "aliased-module-call",
        "imported-dist-name",
        "imported-dist-keyword",
        "try-either-reader",
        "aliased-helper-call",
        "through-a-name",
        "plain-dist-string",
        "dist-name-bound-to-a-string",
        "module-alias-function",
        "metadata-alias-function",
        "package-and-submodule-imports",
        "biff-and-quarry-shape",
        "dist-from-module-name",
        "dist-from-package-name",
        "digit-free-default",
        "dotted-import-binds-its-top-module",
        "dotted-backport-import",
        "try-either-metadata-module",
    ],
)
def test_a_call_is_computed(text: str) -> None:
    assert isinstance(ModuleVersion(text).resolved(), ComputedVersion)


def test_a_computed_version_names_its_source_line() -> None:
    text = (
        "from .paths import installed_version\n"
        "__version__ = installed_version()  # from metadata\n"
    )

    assert ModuleVersion(text).resolved() == ComputedVersion(
        "__version__ = installed_version()  # from metadata"
    )


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('__version__ = "0.1.0"\n', "0.1.0"),
        ("__version__ = '0.1.0'\n", "0.1.0"),
        ('__version__: str = "0.1.0"\n', "0.1.0"),
        ('__version__ = "0.1.0"  # pinned\n', "0.1.0"),
        ('import importlib.metadata\n\n__version__ = "0.1.0"\n', "0.1.0"),
        ('__version__: str\n__version__ = "0.1.0"\n', "0.1.0"),
        ('def f():\n    __version__ = "9.9"\n__version__ = "0.1.0"\n', "0.1.0"),
        ('class C:\n    __version__ = "9.9"\n__version__ = "0.1.0"\n', "0.1.0"),
        ('from .core import *\n__version__ = "1.0"\n', "1.0"),
    ],
    ids=[
        "double",
        "single",
        "annotated",
        "trailing-comment",
        "beside-import",
        "after-bare-annotation",
        "beside-a-function-local",
        "beside-a-class-attribute",
        "after-a-star-import",
    ],
)
def test_a_plain_quoted_string_is_a_literal(text: str, value: str) -> None:
    found = ModuleVersion(text).resolved()

    assert isinstance(found, LiteralVersion)
    assert found.value == value


@pytest.mark.parametrize(
    ("text", "bumped"),
    [
        ("__version__ = '0.1.0'\n", "__version__ = '0.2.0'\n"),
        ('__version__: str = "0.1.0"\r\n', '__version__: str = "0.2.0"\r\n'),
        ('x = "é"; y = 1\n__version__ = "0.1.0"  # é\n', None),
        ('x="é"; __version__ = "0.1.0"\n', 'x="é"; __version__ = "0.2.0"\n'),
        ('__version__: "é" = "0.1.0"\n', '__version__: "é" = "0.2.0"\n'),
    ],
    ids=[
        "keeps-quote",
        "keeps-crlf",
        "non-ascii-line",
        "non-ascii-before-statement",
        "non-ascii-annotation",
    ],
)
def test_a_literal_is_rewritten_in_place(text: str, bumped: str | None) -> None:
    found = ModuleVersion(text).resolved()
    assert isinstance(found, LiteralVersion)
    expected = bumped or text.replace('"0.1.0"', '"0.2.0"')

    assert found.rewritten(text, "0.2.0") == expected


def test_a_name_bound_to_a_literal_resolves_to_that_literal() -> None:
    text = 'VERSION = "0.1.0"\n__version__ = VERSION\n'
    found = ModuleVersion(text).resolved()

    assert isinstance(found, LiteralVersion)
    assert found.rewritten(text, "0.2.0") == text.replace("0.1.0", "0.2.0")


def test_a_name_bound_to_a_call_is_computed() -> None:
    text = (
        "from importlib.metadata import version\n"
        'VERSION = version("x")\n__version__ = VERSION\n'
    )

    assert ModuleVersion(text).resolved() == ComputedVersion('VERSION = version("x")')


@pytest.mark.parametrize(
    "text",
    [
        "",
        "__version__: str\n",
        "x = 1\n",
        'def f():\n    __version__ = "0.1.0"\n',
    ],
    ids=["empty", "annotation-only", "unrelated", "function-local"],
)
def test_no_binding_at_all_is_absent(text: str) -> None:
    assert ModuleVersion(text).resolved() is None


def test_a_docstring_decoy_is_neither_read_nor_rewritten() -> None:
    text = (
        '"""Package.\n\n__version__ = "9.9"\n"""\n\n'
        "from .paths import installed_version\n__version__ = installed_version()\n"
    )

    assert ModuleVersion(text).resolved() == ComputedVersion(
        "__version__ = installed_version()"
    )


def test_an_assignment_inside_a_block_cannot_be_pinned() -> None:
    text = (
        "try:\n    from ._v import __version__\n"
        'except ImportError:\n    __version__ = "0"\n'
    )

    with pytest.raises(UnpinnableVersionError, match="assigned 2 times"):
        ModuleVersion(text).resolved()


@pytest.mark.parametrize(
    "text",
    [
        '__version__ = f"0.1.{N}"\n',
        '__version__ = r"0.1.0"\n',
        '__version__ = u"0.1.0"\n',
        '__version__ = b"0.1.0"\n',
        '__version__ = ("0.1.0")\n',
        '__version__ = (\n    "0.1.0"\n)\n',
        '__version__ = "0.1" ".0"\n',
        '__version__ = "0.1.0" + "-dev"\n',
        '__version__ = "0.1.0" if DEV else "0.2.0"\n',
        '__version__ = """0.1.0"""\n',
        "__version__ = 1\n",
        "__version__ = 1.0\n",
        "__version__ = (1, 0)\n",
        "__version__ = _version.VERSION\n",
        "from ._about import VERSION\n__version__ = VERSION\n",
        "__version__ = VERSION\n",
        "__version__ = __version__\n",
        '__version__ = "0.1.0"; x = 1\n',
        'x = __version__ = "0.1.0"\n',
        '__version__, x = "0.1.0", 1\n',
        '__version__ = str("0.1.0")\n',
        '__version__ = "0.1.0".strip()\n',
        'import os\n__version__ = os.environ.get("V", "0.1.0")\n',
        'VI = (0, 1, 0)\n__version__ = ".".join(map(str, VI))\n',
        'VI = (0, 1)\nV = VI\n__version__ = ".".join(map(str, V))\n',
        "from ._v import __version__\n",
        "from ._v import VERSION as __version__\n",
        "import _v as __version__\n",
        _TYPE_CHECKING_ELSE,
        _TRY_EXCEPT,
        'if DEV:\n    __version__ = "0.1.0"\n',
        'def _set():\n    global __version__\n    __version__ = "0.1.0"\n',
        '__version__ = "0.1.0"\ndef _dev():\n    global __version__\n'
        '    __version__ = "0.1.0-dev"\n',
        '__version__ = "0.1.0"\nif DEV:\n    __version__ += "-dev"\n',
        'VERSION = "0.1.0"\nif DEV:\n    VERSION = "0.2.0"\n__version__ = VERSION\n',
        'if (__version__ := "0.1.0"):\n    pass\n',
        '__version__ = "0.1.0"\nprint(__version__ := "0.2.0")\n',
        'for __version__ in ["0.1.0"]:\n    pass\n',
        'with open("V") as __version__:\n    pass\n',
        'match "0.1.0":\n    case __version__:\n        pass\n',
        '__version__ = "0.1.0"\nfrom ._v import *\n',
        'VERSION = "0.1.0"\n__version__ = VERSION\nfrom ._v import *\n',
        f"{_PARSE}from ._about import VERSION\n__version__ = parse(VERSION)\n",
        f"{_PARSE}from ._about import VERSION\n__version__ = parse(x=VERSION)\n",
        f"{_PARSE}from ._about import VERSION\nV = VERSION\n__version__ = parse(V)\n",
        f"{_PARSE}from ._about import VERSION\nV = parse(VERSION)\n__version__ = V\n",
        f"{_PARSE}from . import _about\n__version__ = parse(_about.VERSION)\n",
        "from . import _about\n__version__ = str(_about.VERSION)\n",
        # The callee must be imported: a same-module def, class or lambda can
        # return a stale literal.
        'def _v():\n    return "0.1.0"\n__version__ = _v()\n',
        "def _v():\n    return MAJOR\nMAJOR = 0\n__version__ = _v()\n",
        'def _v(x="0.1.0"):\n    return x\n__version__ = _v()\n',
        'class _V(str):\n    pass\n__version__ = _V("0.1.0")\n',
        'class _V:\n    def __str__(self):\n        return "0.1.0"\n'
        "__version__ = str(_V())\n",
        '_v = lambda: "0.1.0"\n__version__ = _v()\n',
        'class _Meta:\n    VERSION = "0.1.0"\n__version__ = _Meta.VERSION\n',
        # Built on a call, or on literals the allow-list does not read.
        'MAJOR = 0\nMINOR = 1\n__version__ = "{}.{}".format(MAJOR, MINOR)\n',
        '__version__ = "%d.%d" % (0, 1)\n',
        '__version__ = ".".join(["0", "1", "0"])\n',
        '__version__ = b"0.1.0".decode()\n',
        "__version__ = str(0.1)\n",
        'PARTS = [0, 1, 0]\n__version__ = ".".join(map(str, PARTS))\n',
        '__version__ = ".".join(str(n) for n in [1, 2, 3])\n',
        '__version__ = ".".join(map(str, (1,) + (2,)))\n',
        "__version__ = str(1.2)\n",
        "from importlib.metadata import version\n"
        '__version__ = version("x").split("+")[0]\n',
        'from importlib.metadata import version\n__version__ = version("x") or "0"\n',
        "from ._version import get_versions\n"
        "__version__ = get_versions()['version']\ndel get_versions\n",
        'from . import _version\n__version__ = _version.get_versions()["version"]\n',
        # An imported reader fed a hardcoded version or part of one.
        f"{_PARSE}__version__ = parse(1)\n",
        f"{_PARSE}__version__ = parse(0.1)\n",
        f'{_PARSE}__version__ = parse(b"x")\n',
        f'{_PARSE}__version__ = parse(("0", "1"))\n',
        f"{_PARSE}__version__ = parse({{0, 1}})\n",
        f'{_PARSE}V = "0.1.0"\n__version__ = parse(V)\n',
        'from importlib.metadata import version\n__version__ = version("0.1.0")\n',
        # A module loaded at run time is not a reader.
        "import importlib\n"
        '__version__ = importlib.import_module("._about", __name__).VERSION\n',
        '__version__ = __import__("x").VERSION\n',
        # A walrus in a lambda default binds at module scope.
        '__version__ = "0.1.0"\nf = lambda x=(__version__ := "0.0.9"): x\n',
        '__version__ = "0.1.0"\nf = lambda *, x=(__version__ := "0.0.9"): x\n',
        # Every walrus that runs at module scope binds there.
        '__version__ = "0.1.0"\nmatch x:\n    case _ if (__version__ := "0.0.9"):\n'
        "        pass\n",
        '__version__ = "0.1.0"\n@d((__version__ := "0.0.9"))\ndef f():\n    pass\n',
        '__version__ = "0.1.0"\ndef f(x=(__version__ := "0.0.9")):\n    pass\n',
        '__version__ = "0.1.0"\ndef f(*, x=(__version__ := "0.0.9")):\n    pass\n',
        '__version__ = "0.1.0"\ndef f(x: (__version__ := "0.0.9")):\n    pass\n',
        '__version__ = "0.1.0"\n@d((__version__ := "0.0.9"))\nclass C:\n    pass\n',
        '__version__ = "0.1.0"\ntype __version__ = str\n',
        # A method call on a from-imported name reads a value, not a module.
        "from ._about import VERSION\n__version__ = VERSION.strip()\n",
        'from .paths import helpers\n__version__ = helpers.installed_version("x")\n',
        # The callee is an imported module's path plus exactly one attribute.
        "import pkg._version as _v\n__version__ = _v.VERSION.strip()\n",
        'import pkg._version as _v\n__version__ = _v.TAG.removeprefix("v")\n',
        "import pkg._version as _v\n__version__ = _v.VERSION.__str__()\n",
        "import pkg._version\n__version__ = pkg._version.__version__.strip()\n",
        "import mypkg\n__version__ = mypkg.VERSION.lower()\n",
        'import importlib\n__version__ = importlib.metadata.version("x")\n',
        # Every argument is a plain string, a name bound once to one, or an
        # imported name passed to a metadata reader.
        'import os\n__version__ = os.getenv("V", "1" + ".0")\n',
        'import os\n__version__ = os.getenv("V", "1-0".replace("-", "."))\n',
        'from textwrap import dedent\n__version__ = dedent("1" + ".0")\n',
        'import os\ndef _default():\n    return "0.1.0"\n'
        '__version__ = os.getenv("PKG_VERSION", _default())\n',
        'import os\nclass _C:\n    DEFAULT = "0.1.0"\n'
        '__version__ = os.getenv("PKG_VERSION", _C.DEFAULT)\n',
        "from importlib.metadata import version\ndef f():\n    return 'x'\n"
        "__version__ = version(f())\n",
        'from importlib.metadata import version\n__version__ = version(f"{X}")\n',
        "from importlib.metadata import version\ndef f():\n    pass\n"
        "__version__ = version(f)\n",
        "from importlib.metadata import version\n__version__ = version(*NAMES)\n",
        "from importlib.metadata import version\n__version__ = version(**KW)\n",
        'from importlib.metadata import version\nNAME = "x"\nNAME = "y"\n'
        "__version__ = version(NAME)\n",
        'from importlib.metadata import version\nif A:\n    NAME = "x"\n'
        "__version__ = version(NAME)\n",
        "from importlib.metadata import version\n__version__ = version(NAME)\n",
        f'{_PARSE}__version__ = parse("x", ("y", "z"))\n',
        _LUX_FALLBACK + '__version__ = "0.1.0"\n',
        "from ._v import *\n",
        'import os\n__version__ = os.environ.get("X", "2")\n',
        'import os\n__version__ = os.getenv("X", "10")\n',
        'import os\n__version__ = os.getenv("X", "2rc1")\n',
        'import os\nDEFAULT = "2"\n__version__ = os.getenv("X", DEFAULT)\n',
        # Every binding of the callee's root must be a module that reaches it.
        "import importlib.metadata as md\nfrom ._compat import md\n"
        '__version__ = md.version("pkg")\n',
        "from importlib import metadata\nfrom mypkg import metadata\n"
        '__version__ = metadata.version("x")\n',
        "try:\n    import importlib.metadata as md\n"
        "except ImportError:\n    from ._compat import md\n"
        '__version__ = md.version("pkg")\n',
        # Only a metadata reader may take the module's own name.
        "import os\n__version__ = os.getenv(__name__)\n",
        "import os\n__version__ = os.getenv(__package__)\n",
        # Any digit is version text to a non-metadata reader.
        'import os\n__version__ = os.getenv("V", "v2")\n',
        'import os\n__version__ = os.getenv("V", " 2")\n',
        'import os\n__version__ = os.getenv("V", "\uff12")\n',
        # Unpacking does not bind a plain string.
        'import os\n_, D = "x2"\n__version__ = os.getenv("V", D)\n',
        'import os\n*_, D = "release-2"\n__version__ = os.getenv("V", D)\n',
        'import os\n_, D = "xy"\n__version__ = os.getenv("V", D)\n',
    ],
    ids=[
        "f-string",
        "raw",
        "unicode-prefix",
        "bytes",
        "parenthesised",
        "parenthesised-multiline",
        "implicit-concatenation",
        "plus-concatenation",
        "conditional",
        "triple-quoted",
        "int",
        "float",
        "tuple",
        "attribute",
        "imported-name",
        "unbound-name",
        "self-reference",
        "semicolon-trailer",
        "chained",
        "destructured",
        "literal-in-call",
        "method-on-literal",
        "environ-default",
        "tuple-joined",
        "tuple-joined-through-two-names",
        "imported",
        "imported-alias",
        "imported-module-alias",
        "type-checking-else",
        "try-except",
        "only-in-if",
        "only-under-global",
        "rebound-under-global",
        "augmented-in-block",
        "name-rebound-in-block",
        "walrus-in-if",
        "walrus-rebinds",
        "for-target",
        "with-target",
        "match-capture",
        "star-after",
        "star-beside-name",
        "imported-argument",
        "imported-keyword-argument",
        "imported-through-a-name",
        "imported-on-the-chain",
        "imported-attribute-argument",
        "builtin-on-imported-attribute",
        "def-helper",
        "def-helper-separate-int",
        "def-helper-default",
        "class-constructor",
        "class-dunder-str",
        "lambda-helper",
        "class-attribute",
        "format-separate-ints",
        "percent-format",
        "join-list",
        "bytes-decode",
        "str-of-float",
        "join-list-of-ints",
        "join-generator-over-list",
        "join-tuple-sum",
        "str-of-float-1-2",
        "call-then-split",
        "call-or-fallback",
        "versioneer",
        "versioneer-module",
        "reader-of-int",
        "reader-of-float",
        "reader-of-bytes",
        "reader-of-digit-tuple",
        "reader-of-int-set",
        "reader-of-literal-name",
        "metadata-reader-of-version",
        "import-module-attribute",
        "dunder-import-attribute",
        "walrus-in-lambda-default",
        "walrus-in-lambda-kw-default",
        "walrus-in-match-guard",
        "walrus-in-def-decorator",
        "walrus-in-def-default",
        "walrus-in-def-kw-default",
        "walrus-in-def-annotation",
        "walrus-in-class-decorator",
        "type-alias",
        "method-on-from-imported-value",
        "attribute-on-from-imported-name",
        "method-on-module-alias-attribute",
        "removeprefix-on-module-alias-attribute",
        "dunder-str-on-module-alias-attribute",
        "method-on-dotted-module-attribute",
        "method-on-package-attribute",
        "submodule-not-imported",
        "binop-default",
        "method-call-default",
        "binop-argument",
        "def-default",
        "class-attribute-default",
        "call-argument",
        "f-string-argument",
        "def-bound-argument",
        "starred-argument",
        "double-starred-argument",
        "name-bound-twice",
        "name-bound-in-block",
        "unbound-name-argument",
        "tuple-argument",
        "fallback-then-literal",
        "star-only",
        "digit-only-default",
        "two-digit-default",
        "digit-led-default",
        "digit-only-name-default",
        "alias-shadowed-by-from-import",
        "metadata-shadowed-by-from-import",
        "alias-shadowed-in-try",
        "module-name-to-non-metadata",
        "package-name-to-non-metadata",
        "v-digit-default",
        "space-digit-default",
        "full-width-digit-default",
        "tuple-unpacked-name",
        "starred-unpacked-name",
        "tuple-unpacked-digit-free-name",
    ],
)
def test_anything_else_cannot_be_pinned(text: str) -> None:
    with pytest.raises(UnpinnableVersionError):
        ModuleVersion(text).resolved()


@pytest.mark.parametrize(
    "text",
    [
        '__version__ = "0.1.0"\n__version__ = "0.2.0"\n',
        '__version__ = "0.1.0"\n__version__ += "-dev"\n',
        'VERSION = "0.1.0"\nVERSION = "0.2.0"\n__version__ = VERSION\n',
    ],
    ids=["reassigned", "augmented", "name-reassigned"],
)
def test_more_than_one_module_level_assignment_cannot_be_pinned(text: str) -> None:
    with pytest.raises(UnpinnableVersionError, match="assigned 2 times"):
        ModuleVersion(text).resolved()


@pytest.mark.parametrize(
    "text",
    ['__version__ = "0.1.0\n', "__version__ = \"0.1.0'\n"],
    ids=["unterminated", "mismatched-quotes"],
)
def test_an_unparseable_module_names_the_syntax_error(text: str) -> None:
    with pytest.raises(UnpinnableVersionError, match=r"does not parse \(.*line 1\)"):
        ModuleVersion(text)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("from ._about import VERSION\n__version__ = VERSION\n", "imported"),
        ("__version__ = VERSION\n", "not assigned at module level"),
        ('__version__ = f"0.1.{N}"\n', "not a plain quoted string"),
        ("from ._v import __version__\n", "imported from another module"),
        (_TYPE_CHECKING_ELSE, "assigned inside a block at line 5"),
        (_TRY_EXCEPT, r"assigned 2 times \(lines 2, 4\)"),
        ('__version__ = "0.1.0"\nfrom ._v import *\n', r"import \*` at line 2"),
        (
            'VI = (0, 1, 0)\n__version__ = ".".join(map(str, VI))\n',
            r"\(line 2\) calls `'\.'\.join`, which is not a function imported",
        ),
        (
            '__version__ = str("0.1.0")\n',
            r"calls `str`, .*a call to an imported reader such as "
            r"importlib\.metadata\.version\(\)",
        ),
        (
            f"{_PARSE}from ._about import VERSION\n__version__ = parse(VERSION)\n",
            "passes VERSION, which is imported from another module; pin the version",
        ),
        (
            f'{_PARSE}V = "0.1.0"\n__version__ = parse(V)\n',
            r"\(line 3\) passes V, bound to the hardcoded version '0\.1\.0' \(line 2\)",
        ),
        (
            'from importlib.metadata import version\n__version__ = version("x")[0]\n',
            r"\(line 2\) is not a plain quoted string .* or a call to an "
            r"imported reader",
        ),
        (
            "from ._about import VERSION\n__version__ = VERSION.strip()\n",
            "calls `VERSION.strip`, which is not a function of a module this file "
            "imports",
        ),
        (
            _LUX_FALLBACK,
            r"assigned 2 times \(lines 4, 6\); a fallback version is not allowed "
            r'\(python\.md Version Reporting: no "0\.0\.0" fallback\); remove the '
            "except branch",
        ),
        (
            _LUX_FALLBACK + '__version__ = "0.1.0"\n',
            r"assigned 3 times \(lines 4, 6, 7\); Python keeps the last",
        ),
        (
            'import os\n__version__ = os.getenv("V", "1" + ".0")\n',
            r"\(line 2\) passes `'1' \+ '\.0'`, which is not a plain string or a "
            "name bound to one",
        ),
        (
            "import mypkg\n__version__ = mypkg.VERSION.lower()\n",
            "calls `mypkg.VERSION.lower`, which is not a function of a module this "
            "file imports",
        ),
        (
            "from ._v import *\n",
            r"`from \._v import \*` at line 1 could supply __version__; bind it "
            "explicitly",
        ),
        (
            'import os\n__version__ = os.getenv("X", "2")\n',
            "passes the hardcoded version '2', which could be stale",
        ),
        (
            "import importlib.metadata as md\nfrom ._compat import md\n"
            '__version__ = md.version("pkg")\n',
            "calls `md.version`, which is not a function of a module this file imports",
        ),
        (
            "import os\n__version__ = os.getenv(__name__)\n",
            "passes __name__, which only a metadata reader may take",
        ),
        (
            'import os\n__version__ = os.getenv("V", "\uff12")\n',
            "passes the hardcoded version '\uff12'",
        ),
        (
            'import os\n_, D = "x2"\n__version__ = os.getenv("V", D)\n',
            "passes D, which is neither imported nor bound once, at module level, "
            "to a plain string",
        ),
    ],
    ids=[
        "imported-name",
        "unbound-name",
        "f-string",
        "imported",
        "type-checking-else",
        "try-except",
        "star-import",
        "tuple-joined",
        "literal-in-call",
        "imported-argument",
        "hardcoded-argument",
        "subscripted-call",
        "method-on-from-imported-value",
        "metadata-fallback",
        "fallback-then-literal",
        "binop-argument",
        "callee-too-deep",
        "star-only",
        "digit-only-default",
        "shadowed-alias",
        "module-name-to-non-metadata",
        "full-width-digit",
        "unpacked-name",
    ],
)
def test_the_refusal_says_why(text: str, reason: str) -> None:
    with pytest.raises(UnpinnableVersionError, match=reason):
        ModuleVersion(text).resolved()
