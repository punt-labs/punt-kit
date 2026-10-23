"""Invariants of the release package that no single behavior test would notice."""

from __future__ import annotations

import ast
import io
import re
import tokenize
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
class FileAccess:
    """The lines where a module reads or writes named files itself.

    A tripwire for the plausible forms, not a proof. By default the file is
    CHANGELOG.md and the access is a read. An access is a method in
    ``methods`` or ``open`` on a path that traces to one of ``names``:
    directly, through a name it was assigned to (module-wide, by name, not per
    function), through a wrapper such as ``TextFile(p)`` (and a name bound to
    that wrapper), through an imported constant that holds the file name, or
    through an attribute in ``attributes`` (``info.plugin_manifest``). A
    ``shutil`` call in ``shutil_calls`` with such a path argument is an
    access, and so is a ``git`` argv in ``git_verbs`` (``show``,
    ``cat-file``) naming the file, written inline or held in a variable
    assigned a list or tuple.

    Out of scope, and not caught: a path that reaches the call through tuple
    unpacking, a loop variable, a walrus, a helper's argument, an alias such as
    ``m = os``, a path assembled from pieces, or ``Path(...)`` built without
    the literal name.
    """

    __slots__ = (
        "_argvs",
        "_attributes",
        "_constants",
        "_git_verbs",
        "_methods",
        "_names",
        "_shutil_calls",
        "_tree",
    )

    _tree: ast.Module
    _constants: frozenset[str]
    _names: frozenset[str]
    _methods: frozenset[str]
    _git_verbs: frozenset[str]
    _attributes: frozenset[str]
    _shutil_calls: frozenset[str]
    _argvs: dict[str, ast.List | ast.Tuple]

    def __new__(
        cls,
        source: str,
        *,
        constants: frozenset[str] = frozenset(),
        names: frozenset[str] = frozenset({_CHANGELOG}),
        methods: frozenset[str] = _READ_METHODS,
        git_verbs: frozenset[str] = frozenset({"show", "cat-file"}),
        attributes: frozenset[str] = frozenset(),
        shutil_calls: frozenset[str] = frozenset(),
    ) -> Self:
        self = super().__new__(cls)
        self._tree = ast.parse(source)
        self._constants = constants
        self._names = names
        self._methods = methods
        self._git_verbs = git_verbs
        self._attributes = attributes
        self._shutil_calls = shutil_calls
        self._argvs = {
            ast.unparse(target): node.value
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Assign | ast.AnnAssign)
            and isinstance(node.value, ast.List | ast.Tuple)
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        }
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
        """Line numbers of every access to a watched file, sorted.

        An access is a call to one of ``methods`` (``read_text``) or to
        ``open`` on the file's path, a ``shutil`` call in ``shutil_calls``
        with it as an argument, or a ``git`` argv with a verb in
        ``git_verbs`` (``show``, ``cat-file``) that names the file.
        """
        paths = self._names_bound_to_a_file()
        return sorted(
            node.lineno
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Call)
            and (
                self._reads(node, paths)
                or self._shows(node, paths)
                or self._copies(node, paths)
            )
        )

    def _names_bound_to_a_file(self) -> set[str]:
        """Source text of every name or attribute assigned a watched file's path.

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
                and any(name in part.value for name in self._names)
            ):
                return True
            if isinstance(part, ast.Attribute) and part.attr in self._attributes:
                return True
            if isinstance(part, ast.Name | ast.Attribute):
                text = ast.unparse(part)
                if text in bound or text in self._constants:
                    return True
        return False

    def _reads(self, call: ast.Call, paths: set[str]) -> bool:
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in self._methods:
            target: ast.AST = func.value
        elif isinstance(func, ast.Name) and func.id == "open" and call.args:
            target = call.args[0]
        else:
            return False
        return self._mentions(target, paths)

    def _shows(self, call: ast.Call, paths: set[str]) -> bool:
        """True for a ``git`` argv with a verb in ``git_verbs`` that names the file."""
        for arg in call.args:
            argv = (
                self._argvs.get(ast.unparse(arg)) if isinstance(arg, ast.Name) else arg
            )
            if (
                isinstance(argv, ast.List | ast.Tuple)
                and any(
                    isinstance(item, ast.Constant) and item.value in self._git_verbs
                    for item in argv.elts
                )
                and self._mentions(argv, paths)
            ):
                return True
        return False

    def _copies(self, call: ast.Call, paths: set[str]) -> bool:
        """True for a ``shutil`` copy or move with a managed path argument."""
        func = call.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr in self._shutil_calls
            and isinstance(func.value, ast.Name)
            and func.value.id == "shutil"
            and any(self._mentions(arg, paths) for arg in call.args)
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
    assert FileAccess(source).lines()


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
    assert FileAccess(source, constants=frozenset({"CHANGELOG_NAME"})).lines()


def test_the_constants_that_hold_the_file_name_are_found_in_a_module() -> None:
    source = 'CHANGELOG_NAME = "CHANGELOG.md"\nOTHER = "README.md"\nx = 1\n'

    assert FileAccess.constants_in(source) == {"CHANGELOG_NAME"}


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
    assert FileAccess(source).lines() == []


def _changelog_constants() -> frozenset[str]:
    found: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        found.update(FileAccess.constants_in(path.read_text("utf-8")))
    return frozenset(found)


def test_only_the_changelog_modules_read_changelog_content() -> None:
    """One parser, every reader: nothing else opens CHANGELOG.md itself."""
    constants = _changelog_constants()
    readers = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name not in _CHANGELOG_MODULES
        if (lines := FileAccess(path.read_text("utf-8"), constants=constants).lines())
    }
    assert readers == {}


def _frontmatter(path: Path) -> str:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text("utf-8"), re.DOTALL)
    assert match is not None, f"{path} has no frontmatter"
    return match.group(1)


def _skill_names(skill: Path) -> set[str]:
    """The names a skill answers to: its directory and its frontmatter ``name:``."""
    names = {skill.parent.name}
    named = re.search(r"^name:\s*(\S+)\s*$", _frontmatter(skill), re.MULTILINE)
    if named:
        names.add(named.group(1).strip("\"'"))
    return names


def _twinned_skills(plugin: Path) -> list[Path]:
    """Skills a command of the same name loads, by directory name or ``name:``."""
    return [
        skill
        for skill in sorted((plugin / "skills").glob("*/SKILL.md"))
        if any((plugin / "commands" / f"{n}.md").exists() for n in _skill_names(skill))
    ]


def _listed_twice(plugin: Path) -> list[str]:
    """Twinned skills that would also list themselves in the slash menu."""
    return [
        skill.parent.name
        for skill in _twinned_skills(plugin)
        if not re.search(
            r"^user-invocable:\s*false\s*$", _frontmatter(skill), re.MULTILINE
        )
    ]


def _write_skill(plugin: Path, directory: str, frontmatter: str) -> None:
    skill = plugin / "skills" / directory / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f"---\n{frontmatter}\n---\n\nBody\n")


def test_a_skill_pairs_with_a_command_through_its_frontmatter_name(
    tmp_path: Path,
) -> None:
    """The skill lives in ``tool/`` but is named ``run``: ``run.md`` is its twin."""
    _write_skill(tmp_path, "tool", "name: run\ndescription: x")
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "run.md").write_text("---\n---\n")

    assert _listed_twice(tmp_path) == ["tool"]


def test_a_skill_pairs_with_a_command_through_its_directory_name(
    tmp_path: Path,
) -> None:
    _write_skill(tmp_path, "run", "name: other\ndescription: x")
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "run.md").write_text("---\n---\n")

    assert _listed_twice(tmp_path) == ["run"]


def test_a_hidden_twin_is_not_listed_twice(tmp_path: Path) -> None:
    _write_skill(tmp_path, "run", "name: run\nuser-invocable: false")
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "run.md").write_text("---\n---\n")

    assert _listed_twice(tmp_path) == []


def test_every_skill_with_a_command_is_hidden_from_the_slash_menu() -> None:
    """A skill the command of the same name loads must not list itself twice."""
    assert _twinned_skills(_PLUGIN), (
        "no skill has a command of the same name: the guard guards nothing"
    )
    assert _listed_twice(_PLUGIN) == []


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
    """The lines where a module builds a regex for an install-URL or install-all pin.

    A tripwire, not a proof: it sees a ``re.<fn>(...)`` call whose first
    argument holds a pin marker, directly or through a name assigned such a
    string. Out of scope: a pattern assembled from pieces, one passed through a
    helper's argument, or one compiled by a module imported under another name
    than ``re``.
    """

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
_SLUG_SEPARATORS = frozenset({"/", ":"})
_REMOTE_WORDS = ("remote", "origin", "slug", "url")
_GITHUB_PREFIXES = (
    "https://github.com",
    "http://github.com",
    "ssh://git@github.com",
    "git@github.com:",
)


@final
class SlugParsing:
    """The lines where a module reads an owner/repo out of a remote URL itself.

    A tripwire, not a proof. It flags ``split``, ``rsplit``, ``partition`` and
    ``rpartition`` on ``/`` or ``:`` (positional or ``sep=``), and
    ``removesuffix(".git")``, when the receiver's name says remote, origin,
    slug or url; and a string literal that is a github.com host, scheme prefix
    or ``github.com/`` / ``github.com:`` path. Docstrings are skipped. Out of
    scope: a receiver with a neutral name (``path``, ``text``), a separator held
    in a variable, a regex without a host, tuple-unpacking or loop variables.
    """

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
        if not isinstance(node.func, ast.Attribute):
            return False
        receiver = ast.unparse(node.func.value).lower()
        if not any(word in receiver for word in _REMOTE_WORDS):
            return False
        if node.func.attr == "removesuffix":
            return bool(node.args) and ast.unparse(node.args[0]) in {"'.git'", '".git"'}
        if node.func.attr not in _SPLITTERS:
            return False
        separators = [
            *node.args[:1],
            *(k.value for k in node.keywords if k.arg == "sep"),
        ]
        return any(
            isinstance(sep, ast.Constant) and sep.value in _SLUG_SEPARATORS
            for sep in separators
        )

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
    """Lines that call ``EntryMatcher(...)`` directly.

    A tripwire: the bare name, a name it was imported as (``from x import
    EntryMatcher as EM``), and ``<module>.EntryMatcher(...)``. Out of scope: an
    alias made by assignment, ``type(m)(...)``, or a class built by a factory
    other than ``for_marketplace`` / ``for_website``.
    """
    tree = ast.parse(source)
    names = {"EntryMatcher"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "EntryMatcher" and alias.asname
    }
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "EntryMatcher"
            )
        )
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


# --- no suppressions ---

# A tripwire for the suppression comments a toolchain here reads: ruff/flake8
# (noqa), mypy and pyright (type/pyright ignore, a `pyright: basic` or
# `reportX=false` file override, `mypy: ignore-errors`), pylint, bandit, coverage,
# ruff-format (`fmt: off|skip`) and shellcheck. Out of scope: a suppression in
# pyproject.toml or a config file, and a tool this repo does not run.
_SUPPRESSION = re.compile(
    r"noqa|type:\s*ignore|pyright:\s*(?:ignore|basic|standard|report)"
    r"|mypy:\s*ignore-errors|pylint:\s*(?:disable|skip-file)|nosec"
    r"|pragma:\s*no\s*cover|fmt:\s*(?:off|skip)|shellcheck\s+disable",
    re.IGNORECASE,
)
_SUPPRESSION_ROOTS = (_PACKAGE, _PLUGIN)
_COMMENT_FILES = frozenset({".py", ".sh", ".yaml", ".yml"})


def _suppression_lines(source: str, *, python: bool) -> list[int]:
    """Lines whose comment suppresses a check; a string that says so does not."""
    if python:
        comments = [
            (token.start[0], token.string)
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        ]
    else:
        comments = [
            (number, line.partition("#")[2])
            for number, line in enumerate(source.splitlines(), 1)
            if "#" in line
        ]
    return [number for number, text in comments if _SUPPRESSION.search(text)]


@pytest.mark.parametrize(
    "comment",
    [
        "x = 1  # noqa: E501",
        "x = 1  # NOQA",
        "x = 1  # type: ignore[attr-defined]",
        "x = 1  # pyright: ignore[reportPrivateUsage]",
        "x = 1  # pylint: disable=too-many-arguments",
        "x = 1  # nosec B101",
        "if x:  # pragma: no cover",
    ],
)
def test_the_suppression_scan_finds_every_suppression(comment: str) -> None:
    assert _suppression_lines(comment, python=True) == [1]
    assert _suppression_lines(comment, python=False) == [1]


def test_the_suppression_scan_ignores_a_string_that_names_one() -> None:
    assert _suppression_lines('msg = "add # noqa to silence it"', python=True) == []


def test_no_source_or_plugin_file_suppresses_a_check() -> None:
    """A suppression hides the finding a gate exists to surface."""
    found = {
        str(path): lines
        for root in _SUPPRESSION_ROOTS
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in _COMMENT_FILES
        if (
            lines := _suppression_lines(
                path.read_text("utf-8"), python=path.suffix == ".py"
            )
        )
    }
    assert found == {}


# --- tests reach release.py through its public names ---

_TESTS = Path(__file__).parent


@final
class ReleaseReachIns:
    """The lines that fetch a private ``release`` name by string.

    ``vars(release)["_run"]``, ``vars(release).get("_run")`` and
    ``getattr(release, "_run")`` read the same private name a
    ``release._run`` would, but no type checker flags them. Scope: the
    ``release`` module, bound by ``from punt_kit import release`` or
    ``import punt_kit.release as ...``; other modules are out of scope.
    """

    __slots__ = ("_aliases", "_tree")

    _tree: ast.Module
    _aliases: frozenset[str]

    def __new__(cls, source: str) -> Self:
        self = super().__new__(cls)
        self._tree = ast.parse(source)
        self._aliases = frozenset(cls._bound_names(self._tree))
        return self

    def lines(self) -> list[int]:
        """Line numbers of every reach-in, in source order."""
        return sorted(
            node.lineno
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Subscript | ast.Call) and self._reaches(node)
        )

    @staticmethod
    def _bound_names(tree: ast.Module) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "punt_kit":
                names |= {a.asname or a.name for a in node.names if a.name == "release"}
            elif isinstance(node, ast.Import):
                names |= {
                    a.asname
                    for a in node.names
                    if a.name == "punt_kit.release" and a.asname
                }
        return names

    def _reaches(self, node: ast.Subscript | ast.Call) -> bool:
        if isinstance(node, ast.Subscript):
            return self._vars_of_release(node.value) and self._private(node.slice)
        return self._vars_get(node) or self._getattr(node)

    def _vars_of_release(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "vars"
            and len(node.args) == 1
            and self._is_release(node.args[0])
        )

    def _vars_get(self, call: ast.Call) -> bool:
        func = call.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and self._vars_of_release(func.value)
            and bool(call.args)
            and self._private(call.args[0])
        )

    def _getattr(self, call: ast.Call) -> bool:
        return (
            isinstance(call.func, ast.Name)
            and call.func.id == "getattr"
            and len(call.args) >= 2
            and self._is_release(call.args[0])
            and self._private(call.args[1])
        )

    def _is_release(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id in self._aliases

    @staticmethod
    def _private(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("_")
        )


@pytest.mark.parametrize(
    "source",
    [
        'from punt_kit import release\nx = vars(release)["_run"]\n',
        'from punt_kit import release as r\nx = vars(r)["_run"]\n',
        "import punt_kit.release as r\nx = vars(r).get('_interrupted')\n",
        'from punt_kit import release\nx = getattr(release, "_skips")\n',
    ],
    ids=["vars-subscript", "aliased", "vars-get", "getattr"],
)
def test_the_reach_in_scan_finds_a_private_release_name_fetched_by_string(
    source: str,
) -> None:
    assert ReleaseReachIns(source).lines() == [2]


@pytest.mark.parametrize(
    "source",
    [
        'from punt_kit import release\nx = vars(release)["run_release"]\n',
        'from punt_kit import audit\nx = vars(audit)["_check"]\n',
        "from punt_kit import release\nx = vars(release)[name]\n",
        "from punt_kit import release\nx = release.run_release\n",
        'x = vars(release)["_run"]\n',
    ],
    ids=["public-name", "other-module", "computed-key", "attribute", "unbound-name"],
)
def test_the_reach_in_scan_ignores_everything_else(source: str) -> None:
    assert ReleaseReachIns(source).lines() == []


def test_no_test_reaches_a_private_release_name_by_string() -> None:
    """``vars(release)["_x"]`` hides from pyright what a suppression would show."""
    found = {
        str(path.relative_to(_TESTS)): lines
        for path in sorted(_TESTS.rglob("*.py"))
        if (lines := ReleaseReachIns(path.read_text("utf-8")).lines())
    }
    assert found == {}


# --- release-managed files are read and written through TextFile / JsonFile ---

_MANAGED_FILES = frozenset(
    {
        "CHANGELOG.md",
        "pyproject.toml",
        "__init__.py",
        "install.sh",
        "install-all.sh",
        "plugin.json",
        "README.md",
        "marketplace.json",
        "projects.json",
        "settings.json",
    }
)
# ProjectInfo attributes that are paths of a managed file.
_MANAGED_ATTRIBUTES = frozenset({"plugin_manifest", "plugin_manifests"})
_SHUTIL_CALLS = frozenset({"copy", "copy2", "copyfile", "move", "copytree"})
_IO_METHODS = frozenset(
    {"read_text", "write_text", "read_bytes", "write_bytes", "open", "readlines"}
)
# The two wrappers: they are where a managed file's bytes are actually touched.
_FILE_WRAPPERS = frozenset({"text_file.py", "json_file.py"})


def _managed_io_lines(source: str) -> list[int]:
    # `git show` of a managed file stays legal: Phase 11 reads a file as of a
    # commit that way. `git cat-file` is the raw-bytes read and is flagged.
    return FileAccess(
        source,
        names=_MANAGED_FILES,
        methods=_IO_METHODS,
        git_verbs=frozenset({"cat-file"}),
        attributes=_MANAGED_ATTRIBUTES,
        shutil_calls=_SHUTIL_CALLS,
    ).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('(root / "pyproject.toml").read_text()', id="read-text"),
        pytest.param('(root / "README.md").write_text(x)', id="write-text"),
        pytest.param('p = root / "install.sh"\np.read_bytes()', id="bound-read"),
        pytest.param('p = pkg / "__init__.py"\np.write_bytes(b)', id="bound-write"),
        pytest.param('open(root / ".claude" / "settings.json")', id="open"),
        pytest.param(
            'init_py = pkg / "__init__.py"\ninit_py.write_text(t, encoding="utf-8")',
            id="write-with-encoding",
        ),
        pytest.param('(d / "install-all.sh").read_text()', id="install-all"),
        pytest.param('(d / "src" / "data" / "projects.json").open()', id="projects"),
    ],
)
def test_the_file_io_scan_finds_a_managed_file_touched_directly(source: str) -> None:
    assert _managed_io_lines(source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('TextFile(root / "pyproject.toml").read()', id="text-file"),
        pytest.param('JsonFile(root / "plugin.json").load()', id="json-file"),
        pytest.param('(root / ".markdownlint.jsonc").write_text(x)', id="unmanaged"),
        pytest.param('(root / "Makefile").read_text()', id="makefile"),
        pytest.param('(root / "README.md").exists()', id="exists"),
    ],
)
def test_the_file_io_scan_ignores_the_wrappers_and_unmanaged_files(
    source: str,
) -> None:
    assert _managed_io_lines(source) == []


def test_release_managed_files_are_touched_only_through_the_wrappers() -> None:
    """A direct read or write drops the BOM, the line endings, or the final newline."""
    direct = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name not in _FILE_WRAPPERS
        if (lines := _managed_io_lines(path.read_text("utf-8")))
    }
    assert direct == {}


# --- further forms each tripwire catches ---


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'cmd = ["git", "show", f"{ref}:CHANGELOG.md"]\nops.run(cmd)',
            id="show-argv-variable",
        ),
        pytest.param(
            'cmd = ("git", "cat-file", "-p", "HEAD:CHANGELOG.md")\nops.run(cmd)',
            id="cat-file-tuple-variable",
        ),
        pytest.param(
            'ops.run(["git", "cat-file", "-p", "HEAD:CHANGELOG.md"])', id="cat-file"
        ),
        pytest.param(
            'cmd: list[str] = ["git", "show", "HEAD:CHANGELOG.md"]\nops.run(cmd)',
            id="annotated-argv-variable",
        ),
    ],
)
def test_the_changelog_scan_follows_a_git_argv_held_in_a_variable(source: str) -> None:
    assert FileAccess(source).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('cmd = ["git", "log", "CHANGELOG.md"]\nops.run(cmd)', id="log"),
        pytest.param('cmd = ["git", "show", "HEAD:x"]\nops.run(cmd)', id="other-file"),
    ],
)
def test_the_changelog_scan_ignores_an_argv_that_does_not_read_it(source: str) -> None:
    assert FileAccess(source).lines() == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("info.plugin_manifest.write_text(x)", id="attribute-write"),
        pytest.param("self._info.plugin_manifest.read_text()", id="attribute-read"),
        pytest.param("info.plugin_manifest.open()", id="attribute-open"),
        pytest.param('shutil.copy(src, root / "README.md")', id="shutil-copy"),
        pytest.param('shutil.move(root / "install.sh", dst)', id="shutil-move"),
        pytest.param("shutil.copyfile(info.plugin_manifest, dst)", id="shutil-attr"),
        pytest.param(
            'ops.run(["git", "cat-file", "-p", "HEAD:install.sh"])', id="cat-file"
        ),
        pytest.param(
            'cmd = ["git", "cat-file", "blob", "HEAD:README.md"]\nops.run(cmd)',
            id="cat-file-variable",
        ),
    ],
)
def test_the_managed_file_scan_finds_the_attribute_shutil_and_cat_file_forms(
    source: str,
) -> None:
    assert _managed_io_lines(source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('ops.run(["git", "show", "HEAD:install.sh"])', id="show-is-legal"),
        pytest.param("JsonFile(info.plugin_manifest).load()", id="wrapper"),
        pytest.param("info.plugin_manifest.relative_to(root)", id="not-io"),
        pytest.param('shutil.copy(src, root / "notes.txt")', id="unmanaged-copy"),
    ],
)
def test_the_managed_file_scan_leaves_the_legal_forms_alone(source: str) -> None:
    assert _managed_io_lines(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('name = remote.removesuffix(".git")', id="removesuffix"),
        pytest.param('remote.rsplit(":", 1)[-1]', id="rsplit-colon"),
        pytest.param('origin.split(sep="/")', id="split-keyword"),
        pytest.param('remote_url.partition(":")', id="partition-colon"),
        pytest.param("slug_text.rpartition('/')", id="rpartition"),
    ],
)
def test_the_slug_scan_finds_the_colon_keyword_and_suffix_forms(source: str) -> None:
    assert SlugParsing(source).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('name = filename.removesuffix(".py")', id="other-suffix"),
        pytest.param('line.rsplit(":", 1)', id="neutral-receiver"),
        pytest.param('text.split(sep="/")', id="neutral-keyword"),
    ],
)
def test_the_slug_scan_ignores_neutral_receivers(source: str) -> None:
    assert SlugParsing(source).lines() == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from x import EntryMatcher as EM\nm = EM(a, b, c)", id="import-alias"
        ),
        pytest.param("m = entry_matcher.EntryMatcher(a, b, c)", id="module-attribute"),
        pytest.param(
            "import x.entry_matcher as em\nm = em.EntryMatcher(a, b, c)",
            id="module-alias",
        ),
    ],
)
def test_the_entry_matcher_scan_finds_an_aliased_construction(source: str) -> None:
    assert _constructs_entry_matcher(source)


@pytest.mark.parametrize(
    "comment",
    [
        "# shellcheck disable=SC2086",
        "# mypy: ignore-errors",
        "# pyright: basic",
        "# pyright: reportUnknownMemberType=false",
        "# fmt: off",
        "# fmt: skip",
        "# pylint: skip-file",
    ],
)
def test_the_suppression_scan_finds_the_file_level_forms(comment: str) -> None:
    assert _suppression_lines(f"{comment}\nx = 1\n", python=True) == [1]
    assert _suppression_lines(f"{comment}\nx = 1\n", python=False) == [1]
