"""Invariants of the release package that no single behavior test would notice."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Self, final

import pytest

import punt_kit

_PACKAGE = Path(punt_kit.__file__).parent
_PLUGIN = _PACKAGE.parent.parent / "plugin"

# The one parser and the one reader of CHANGELOG.md content.
_CHANGELOG_MODULES = frozenset(
    {
        "changelog.py",
        "changelog_blocks.py",
        "changelog_parser.py",
        "changelog_sections.py",
    }
)
_READ_METHODS = frozenset({"read_text", "read_bytes", "readlines", "read", "open"})
_CHANGELOG = "CHANGELOG.md"


@final
class ChangelogReads:
    """The lines where a module reads CHANGELOG.md content itself.

    A read is a read method or ``open`` on a path that traces to
    ``"CHANGELOG.md"``: directly, through a name it was assigned to, through
    a wrapper such as ``TextFile(p)`` (and a name bound to that wrapper), or
    through an imported constant that holds the file name. ``git show
    <ref>:CHANGELOG.md`` reads it too.
    """

    __slots__ = ("_constants", "_tree")

    _tree: ast.Module
    _constants: frozenset[str]

    def __new__(cls, source: str, *, constants: frozenset[str] = frozenset()) -> Self:
        self = super().__new__(cls)
        self._tree = ast.parse(source)
        self._constants = constants
        return self

    @staticmethod
    def constants_in(source: str) -> frozenset[str]:
        """Names assigned the literal ``"CHANGELOG.md"`` at module level."""
        return frozenset(
            target.id
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign | ast.AnnAssign)
            and isinstance(node.value, ast.Constant)
            and node.value.value == _CHANGELOG
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        )

    def lines(self) -> list[int]:
        """Line numbers of reads of a path built from ``"CHANGELOG.md"``."""
        paths = self._names_bound_to_the_changelog()
        return sorted(
            node.lineno
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Call)
            and (self._reads(node, paths) or self._shows(node, paths))
        )

    def _names_bound_to_the_changelog(self) -> set[str]:
        """Source text of every name or attribute assigned a CHANGELOG.md path.

        Repeated to a fixed point so ``f = TextFile(p)`` binds ``f`` once ``p``
        is bound, whatever order the assignments appear in.
        """
        bound: set[str] = set()
        while True:
            before = len(bound)
            for node in ast.walk(self._tree):
                if isinstance(node, ast.Assign) and self._mentions(node.value, bound):
                    bound.update(ast.unparse(target) for target in node.targets)
                elif (
                    isinstance(node, ast.AnnAssign)
                    and node.value is not None
                    and self._mentions(node.value, bound)
                ):
                    bound.add(ast.unparse(node.target))
            if len(bound) == before:
                return bound

    def _mentions(self, node: ast.AST, bound: set[str]) -> bool:
        """True when ``node`` holds the file name, a constant for it, or a path."""
        for part in ast.walk(node):
            if (
                isinstance(part, ast.Constant)
                and isinstance(part.value, str)
                and _CHANGELOG in part.value
            ):
                return True
            if isinstance(part, ast.Name | ast.Attribute):
                text = ast.unparse(part)
                if text in bound or text in self._constants:
                    return True
        return False

    def _reads(self, call: ast.Call, paths: set[str]) -> bool:
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in _READ_METHODS:
            target: ast.AST = func.value
        elif isinstance(func, ast.Name) and func.id == "open" and call.args:
            target = call.args[0]
        else:
            return False
        return self._mentions(target, paths)

    def _shows(self, call: ast.Call, paths: set[str]) -> bool:
        """True for a ``["git", "show", "<ref>:CHANGELOG.md"]`` argument vector."""
        return any(
            isinstance(arg, ast.List | ast.Tuple)
            and any(
                isinstance(item, ast.Constant) and item.value == "show"
                for item in arg.elts
            )
            and self._mentions(arg, paths)
            for arg in call.args
        )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('(root / "CHANGELOG.md").read_text()', id="inline"),
        pytest.param('p = root / "CHANGELOG.md"\np.read_text("utf-8")', id="bound"),
        pytest.param('p = root / "CHANGELOG.md"\np.read_bytes()', id="bytes"),
        pytest.param('open(root / "CHANGELOG.md")', id="open"),
        pytest.param('p = base / "CHANGELOG.md"\nopen(p)', id="open-bound"),
        pytest.param(
            'self._path = root / "CHANGELOG.md"\nself._path.read_text()',
            id="attribute-target",
        ),
        pytest.param(
            'p: Path = root / "CHANGELOG.md"\np.read_text()', id="annotated-target"
        ),
        pytest.param(
            'self._p: Path = root / "CHANGELOG.md"\nopen(self._p)',
            id="annotated-attribute",
        ),
    ],
)
def test_the_scan_finds_a_module_reading_the_changelog(source: str) -> None:
    assert ChangelogReads(source).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'p = root / "CHANGELOG.md"\nTextFile(p).read()', id="wrapped-in-textfile"
        ),
        pytest.param(
            'p = root / "CHANGELOG.md"\nf = TextFile(p)\nf.read()', id="wrapper-bound"
        ),
        pytest.param(
            'f = TextFile(p)\np = root / "CHANGELOG.md"\nf.read()', id="bound-late"
        ),
        pytest.param("(root / CHANGELOG_NAME).read_text()", id="imported-constant"),
        pytest.param(
            "p = root / CHANGELOG_NAME\nTextFile(p).read()", id="constant-then-wrapper"
        ),
        pytest.param(
            'ops.run(["git", "show", f"{ref}:CHANGELOG.md"])', id="git-show-literal"
        ),
        pytest.param(
            'ops.run(["git", "show", f"{ref}:{CHANGELOG_NAME}"], cwd=d)',
            id="git-show-constant",
        ),
    ],
)
def test_the_scan_finds_the_indirect_reads_of_the_changelog(source: str) -> None:
    assert ChangelogReads(source, constants=frozenset({"CHANGELOG_NAME"})).lines()


def test_the_constants_that_hold_the_file_name_are_found_in_a_module() -> None:
    source = 'CHANGELOG_NAME = "CHANGELOG.md"\nOTHER = "README.md"\nx = 1\n'

    assert ChangelogReads.constants_in(source) == {"CHANGELOG_NAME"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('p = root / "CHANGELOG.md"\np.exists()', id="exists"),
        pytest.param('p = root / "CHANGELOG.md"\nfiles = [p]', id="staged"),
        pytest.param('(root / "README.md").read_text()', id="another-file"),
        pytest.param(
            'p = root / "CHANGELOG.md"\nq = root / "x"\nq.read_text()', id="other"
        ),
        pytest.param(
            'p = root / "CHANGELOG.md"\nf = TextFile(q)\nf.read()', id="other-wrapper"
        ),
        pytest.param('ops.run(["git", "show", "HEAD:README.md"])', id="show-another"),
        pytest.param('ops.run(["git", "log", "CHANGELOG.md"])', id="log-not-show"),
    ],
)
def test_the_scan_ignores_paths_that_are_not_read(source: str) -> None:
    assert ChangelogReads(source).lines() == []


def _changelog_constants() -> frozenset[str]:
    found: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        found.update(ChangelogReads.constants_in(path.read_text("utf-8")))
    return frozenset(found)


def test_only_the_changelog_modules_read_changelog_content() -> None:
    """One parser, every reader: nothing else opens CHANGELOG.md itself."""
    constants = _changelog_constants()
    readers = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name not in _CHANGELOG_MODULES
        if (
            lines := ChangelogReads(
                path.read_text("utf-8"), constants=constants
            ).lines()
        )
    }
    assert readers == {}


def _frontmatter(path: Path) -> str:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text("utf-8"), re.DOTALL)
    assert match is not None, f"{path} has no frontmatter"
    return match.group(1)


def test_every_skill_with_a_command_is_hidden_from_the_slash_menu() -> None:
    """A skill the command of the same name loads must not list itself twice."""
    skills = sorted((_PLUGIN / "skills").glob("*/SKILL.md"))
    twinned = [
        s for s in skills if (_PLUGIN / "commands" / f"{s.parent.name}.md").exists()
    ]
    assert twinned, "no skill has a command of the same name: the guard guards nothing"
    visible = [
        s.parent.name
        for s in twinned
        if not re.search(r"^user-invocable:\s*false\s*$", _frontmatter(s), re.MULTILINE)
    ]
    assert visible == []


_README_PIN = "punt_kit.phases.shared.readme_sha"


def _imports_the_readme_pin(source: str) -> bool:
    """True for any import form that binds the ``readme_sha`` module or its names."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative: ``from . import readme_sha``, ``from .readme_sha import X``.
                names = [alias.name for alias in node.names]
                if "readme_sha" in names or (node.module or "").endswith("readme_sha"):
                    return True
            if node.module == _README_PIN:
                return True
            if node.module == _README_PIN.rpartition(".")[0] and any(
                alias.name == "readme_sha" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import) and any(
            alias.name == _README_PIN for alias in node.names
        ):
            return True
    return False


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(f"from {_README_PIN} import ReadmeShaPin", id="from-module"),
        pytest.param(
            "from punt_kit.phases.shared import readme_sha", id="from-package"
        ),
        pytest.param(
            "from punt_kit.phases.shared import git, readme_sha as rs", id="aliased"
        ),
        pytest.param(f"import {_README_PIN}", id="plain-import"),
        pytest.param(f"import {_README_PIN} as rs", id="plain-import-as"),
        pytest.param("from . import readme_sha", id="relative-package"),
        pytest.param("from .readme_sha import ReadmeShaPin", id="relative-module"),
        pytest.param("from .shared.readme_sha import ReadmeShaPin", id="relative-deep"),
    ],
)
def test_the_readme_pin_import_guard_catches_every_form(source: str) -> None:
    assert _imports_the_readme_pin(source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from punt_kit.phases.shared import git", id="sibling"),
        pytest.param("import punt_kit.phases.shared.git", id="sibling-import"),
        pytest.param("from . import git", id="relative-sibling"),
        pytest.param("from .shared.git import GitWorkspace", id="relative-names"),
        pytest.param("from punt_kit.phases.shared.git import GitWorkspace", id="names"),
    ],
)
def test_the_readme_pin_import_guard_ignores_other_imports(source: str) -> None:
    assert not _imports_the_readme_pin(source)


def test_phase_9_does_not_import_the_readme_pin() -> None:
    """Phase 4 owns the README pin; Phase 9 is the dev restore only."""
    source = (_PACKAGE / "phases" / "phase09_post_release.py").read_text("utf-8")
    assert not _imports_the_readme_pin(source)


# --- one definition of a pin ---

_PIN_RULE_MODULES = frozenset({"install_urls.py", "pin_rules.py"})
_PIN_MARKERS = (
    "raw.githubusercontent",
    "raw\\.githubusercontent",
    "install.sh",
    "install\\.sh",
    "install-all",
)
_RE_FUNCTIONS = frozenset(
    {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn"}
)


@final
class PinRegexes:
    """The lines where a module builds a regex for an install-URL or install-all pin."""

    __slots__ = ("_tree",)

    _tree: ast.Module

    def __new__(cls, source: str) -> Self:
        self = super().__new__(cls)
        self._tree = ast.parse(source)
        return self

    def lines(self) -> list[int]:
        """Line numbers of ``re.<fn>(...)`` calls whose pattern names a pin."""
        marked = self._names_bound_to_pin_text()
        return sorted(
            node.lineno
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Call)
            and self._is_re_call(node)
            and node.args
            and self._names_a_pin(node.args[0], marked)
        )

    def _names_bound_to_pin_text(self) -> set[str]:
        bound: set[str] = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign) and self._has_marker(node.value):
                bound.update(ast.unparse(target) for target in node.targets)
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and self._has_marker(node.value)
            ):
                bound.add(ast.unparse(node.target))
        return bound

    @staticmethod
    def _is_re_call(call: ast.Call) -> bool:
        func = call.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr in _RE_FUNCTIONS
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
        )

    @staticmethod
    def _has_marker(node: ast.AST) -> bool:
        return any(
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and any(marker in part.value for marker in _PIN_MARKERS)
            for part in ast.walk(node)
        )

    def _names_a_pin(self, pattern: ast.AST, marked: set[str]) -> bool:
        return self._has_marker(pattern) or ast.unparse(pattern) in marked


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'import re\nre.compile(r"raw\\.githubusercontent\\.com/o/([^/]+)/")',
            id="raw-url",
        ),
        pytest.param('import re\nre.search(r"/install\\.sh", text)', id="install-sh"),
        pytest.param(
            'import re\nre.compile(rf"\\$GH/{name}/([0-9a-f]+)/install\\.sh")',
            id="fstring",
        ),
        pytest.param('import re\nre.findall("install-all", text)', id="install-all"),
        pytest.param(
            'import re\n_P = r"raw.githubusercontent.com/x"\nre.compile(_P)',
            id="through-a-name",
        ),
        pytest.param(
            'import re\nclass C:\n    _P = re.compile("install.sh")', id="class-body"
        ),
    ],
)
def test_the_pin_regex_scan_finds_a_regex_for_a_pin(source: str) -> None:
    assert PinRegexes(source).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('import re\nre.compile(r"^version\\s*=")', id="other-regex"),
        pytest.param('x = "raw.githubusercontent.com"', id="plain-string"),
        pytest.param('import re\nre.search(r"VERSION=", text)', id="version-pin"),
        pytest.param('p.install("install.sh")', id="not-re"),
    ],
)
def test_the_pin_regex_scan_ignores_everything_else(source: str) -> None:
    assert PinRegexes(source).lines() == []


def test_only_the_pin_rule_modules_build_a_pin_regex() -> None:
    """One definition of "a pin": nothing else invents its own pattern for one."""
    builders = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name not in _PIN_RULE_MODULES
        if (lines := PinRegexes(path.read_text("utf-8")).lines())
    }
    assert builders == {}


# --- one way to name a repository, one way to match its entries ---

_SLUG_MODULES = frozenset({"repo_slug.py"})
_SPLITTERS = frozenset({"split", "rsplit", "partition", "rpartition"})
_REMOTE_WORDS = ("remote", "origin", "slug", "url")
_GITHUB_PREFIXES = (
    "https://github.com",
    "http://github.com",
    "ssh://git@github.com",
    "git@github.com:",
)


@final
class SlugParsing:
    """The lines where a module reads an owner/repo out of a remote URL itself."""

    __slots__ = ("_tree",)

    _tree: ast.Module

    def __new__(cls, source: str) -> Self:
        self = super().__new__(cls)
        self._tree = ast.parse(source)
        return self

    def lines(self) -> list[int]:
        """Line numbers of a ``/`` split of a remote, or a github.com literal.

        Docstrings describe a URL without parsing one, so they are skipped.
        """
        docs = self._docstrings()
        return sorted(
            {
                node.lineno
                for node in ast.walk(self._tree)
                if (isinstance(node, ast.Call) and self._splits_a_remote(node))
                or (
                    isinstance(node, ast.Constant)
                    and id(node) not in docs
                    and self._names_github_host(node)
                )
            }
        )

    def _docstrings(self) -> set[int]:
        """``id()`` of every docstring constant in the module."""
        docs: set[int] = set()
        for node in ast.walk(self._tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(
                    first.value, ast.Constant
                ):
                    docs.add(id(first.value))
        return docs

    @staticmethod
    def _splits_a_remote(node: ast.Call) -> bool:
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _SPLITTERS
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "/"
        ):
            return False
        receiver = ast.unparse(node.func.value).lower()
        return any(word in receiver for word in _REMOTE_WORDS)

    @staticmethod
    def _names_github_host(node: ast.Constant) -> bool:
        if not isinstance(node.value, str):
            return False
        text = node.value.replace("\\", "")  # a regex source escapes the dot
        return (
            text == "github.com"
            or text.startswith(_GITHUB_PREFIXES)
            or "github.com:" in text
            or "github.com/" in text
        )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('remote_url.split("/")', id="split-remote"),
        pytest.param('origin.rstrip("/").rsplit("/", 1)', id="rsplit-origin"),
        pytest.param('slug_text.partition("/")', id="partition-slug"),
        pytest.param('url.removesuffix(".git").split("/")[-2:]', id="split-url"),
        pytest.param('host == "github.com"', id="host-literal"),
        pytest.param('url.startswith("https://github.com/")', id="https-prefix"),
        pytest.param('x = "git@github.com:o/r"', id="scp-literal"),
        pytest.param('re.match(r"github\\.com/(.+)/(.+)", url)', id="slash-literal"),
    ],
)
def test_the_slug_scan_finds_a_module_parsing_a_remote(source: str) -> None:
    assert SlugParsing(source).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('stripped.split("/")', id="a-pattern"),
        pytest.param('print("no github.com origin remote")', id="a-message"),
        pytest.param('"noreply@github.com"', id="an-address"),
        pytest.param('path.split(":")', id="another-separator"),
        pytest.param('def f():\n    """See https://github.com/o/r."""', id="docstring"),
    ],
)
def test_the_slug_scan_ignores_everything_else(source: str) -> None:
    assert SlugParsing(source).lines() == []


def test_only_repo_slug_reads_an_owner_and_repo_out_of_a_remote() -> None:
    parsers = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name not in _SLUG_MODULES
        if (lines := SlugParsing(path.read_text("utf-8")).lines())
    }
    assert parsers == {}


def _constructs_entry_matcher(source: str) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EntryMatcher"
    )


def test_the_entry_matcher_scan_finds_a_direct_construction() -> None:
    assert _constructs_entry_matcher('m = EntryMatcher(o, r, frozenset({"x"}))')
    assert not _constructs_entry_matcher("m = EntryMatcher.for_website(slug)")


def test_only_the_entry_matcher_module_constructs_one() -> None:
    """Phases 10 and 11 must match entries by the same names: one factory each."""
    builders = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name != "entry_matcher.py"
        if (lines := _constructs_entry_matcher(path.read_text("utf-8")))
    }
    assert builders == {}
