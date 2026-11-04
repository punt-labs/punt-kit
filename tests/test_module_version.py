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
        "from ._version import get_versions\n"
        "__version__ = get_versions()['version']\ndel get_versions\n",
        "from importlib.metadata import version\n"
        '__version__ = version("x").split("+")[0]\n',
        'from importlib.metadata import version\n__version__ = version("x") or "0"\n',
    ],
    ids=[
        "helper-call",
        "metadata-call",
        "dotted-metadata-call",
        "versioneer",
        "call-then-split",
        "call-or-fallback",
    ],
)
def test_a_call_is_computed(text: str) -> None:
    assert isinstance(ModuleVersion(text).resolved(), ComputedVersion)


def test_a_computed_version_names_its_source_line() -> None:
    text = "__version__ = installed_version()  # from metadata\n"

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
    text = 'VERSION = version("x")\n__version__ = VERSION\n'

    assert ModuleVersion(text).resolved() == ComputedVersion('VERSION = version("x")')


@pytest.mark.parametrize(
    "text",
    [
        "",
        "__version__: str\n",
        "x = 1\n",
        'def f():\n    __version__ = "0.1.0"\n',
        "from ._v import *\n",
    ],
    ids=["empty", "annotation-only", "unrelated", "function-local", "star-only"],
)
def test_no_binding_at_all_is_absent(text: str) -> None:
    assert ModuleVersion(text).resolved() is None


def test_a_docstring_decoy_is_neither_read_nor_rewritten() -> None:
    text = (
        '"""Package.\n\n__version__ = "9.9"\n"""\n\n__version__ = installed_version()\n'
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
        'from ._v import *\n__version__ = "0.1.0"\n',
        '__version__ = "0.1.0"\nfrom ._v import *\n',
        'VERSION = "0.1.0"\n__version__ = VERSION\nfrom ._v import *\n',
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
        "star-before",
        "star-after",
        "star-beside-name",
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
        ('from ._v import *\n__version__ = "0.1.0"\n', r"import \*` at line 1"),
        (
            'VI = (0, 1, 0)\n__version__ = ".".join(map(str, VI))\n',
            r"hardcoded version \(0, 1, 0\) \(line 1\)",
        ),
        ('__version__ = str("0.1.0")\n', "hardcoded version '0.1.0'"),
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
    ],
)
def test_the_refusal_says_why(text: str, reason: str) -> None:
    with pytest.raises(UnpinnableVersionError, match=reason):
        ModuleVersion(text).resolved()
