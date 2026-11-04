"""Tests for classifying a Python module's ``__version__`` from its syntax tree."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.module_version import (
    ComputedVersion,
    LiteralVersion,
    ModuleVersion,
    UnpinnableVersionError,
)


@pytest.mark.parametrize(
    "text",
    [
        "from punt_vox.paths import installed_version\n\n"
        "__version__ = installed_version()\n",
        'from importlib.metadata import version\n__version__ = version("x")\n',
        'import importlib.metadata\n__version__ = importlib.metadata.version("x")\n',
    ],
    ids=["helper-call", "metadata-call", "dotted-metadata-call"],
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
    ],
    ids=["double", "single", "annotated", "trailing-comment", "beside-import"],
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
    ],
    ids=["keeps-quote", "keeps-crlf", "non-ascii-line"],
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
    ["", "from ._v import __version__\n", "__version__: str\n", "x = 1\n"],
    ids=["empty", "imported", "annotation-only", "unrelated"],
)
def test_no_module_level_assignment_is_absent(text: str) -> None:
    assert ModuleVersion(text).resolved() is None


def test_a_docstring_decoy_is_neither_read_nor_rewritten() -> None:
    text = (
        '"""Package.\n\n__version__ = "9.9"\n"""\n\n__version__ = installed_version()\n'
    )

    assert ModuleVersion(text).resolved() == ComputedVersion(
        "__version__ = installed_version()"
    )


def test_an_assignment_inside_a_block_is_not_module_level() -> None:
    text = (
        "try:\n    from ._v import __version__\n"
        'except ImportError:\n    __version__ = "0"\n'
    )

    assert ModuleVersion(text).resolved() is None


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
    ],
    ids=["imported-name", "unbound-name", "f-string"],
)
def test_the_refusal_says_why(text: str, reason: str) -> None:
    with pytest.raises(UnpinnableVersionError, match=reason):
        ModuleVersion(text).resolved()
