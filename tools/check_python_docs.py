"""Check Python comments, docstring arguments, and generated API coverage."""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
import zlib
from pathlib import Path

from docstring_parser import DocstringStyle, ParseError, parse

_DOC_DIAGNOSTIC = re.compile(r".+:\d+: DOC(\d{3}): (.+)")
_REQUIRED_DOC_CODES = {1, 2, 3, 102, 111, 304}
_OPTIONAL_DOC_CODES = {
    101,
    104,
    105,
    106,
    107,
    108,
    109,
    110,
    *range(201, 204),
    *range(301, 304),
    *range(305, 308),
    *range(401, 406),
    *range(501, 505),
    *range(601, 608),
}
_OMITTED_ARGS = "Arguments in the function signature but not in the docstring:"
_STALE_ARGS = "Arguments in the docstring but not in the function signature:"
_ARGS_HEADER = re.compile(r"^(?:Args|Arguments|Parameters|Params):[ \t\r\f\v]*$", re.M)
_TRACKER_REFERENCE = re.compile(
    r"(?<![\w-])(?:PL-\d+|pkit-[a-z0-9]{4,8})(?![\w-])"
    r"|\b(?:PR|issue|pull request)\s+#\d+\b"
    r"|\blinear\.app/[^/\s]+/issue/[^/\s]+"
    r"|\bgithub\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/\d+\b",
    re.IGNORECASE,
)
_API_SYMBOLS = frozenset(
    {
        "punt_kit",
        "punt_kit.audit.run_audit",
        "punt_kit.claude_md.ClaudeMdImport",
        "punt_kit.claude_md.ClaudeMdImport.__new__",
        "punt_kit.claude_md.ClaudeMdImport.append_would_be_fenced",
        "punt_kit.claude_md.ClaudeMdImport.is_registered",
        "punt_kit.claude_md.ClaudeMdImport.prune",
        "punt_kit.claude_md.ClaudeMdImport.register",
        "punt_kit.claude_md.UNCLOSED_FENCE",
        "punt_kit.claude_md.write_atomically",
        "punt_kit.claude_permissions.PUNT_RULES",
        "punt_kit.claude_permissions.PermissionChange",
        "punt_kit.claude_permissions.PermissionChange.lines",
        "punt_kit.claude_permissions.ProjectPermissions",
        "punt_kit.claude_permissions.ProjectPermissions.__new__",
        "punt_kit.claude_permissions.ProjectPermissions.grant",
        "punt_kit.claude_permissions.ProjectPermissions.revoke",
        "punt_kit.doctor.CheckResult",
        "punt_kit.doctor.CheckResult.status_suffix",
        "punt_kit.doctor.run_doctor",
        "punt_kit.enablement.EnablementReport",
        "punt_kit.enablement.PuntEnablement",
        "punt_kit.enablement.PuntEnablement.__new__",
        "punt_kit.enablement.PuntEnablement.disable",
        "punt_kit.enablement.PuntEnablement.enable",
        "punt_kit.init.run_init",
        "punt_kit.permission_rules.PermissionRule",
        "punt_kit.permission_rules.PermissionRule.content",
        "punt_kit.permission_rules.PermissionRule.is_dead",
        "punt_kit.permission_rules.PermissionRule.live_equivalent",
        "punt_kit.permission_rules.PermissionRule.tool",
        "punt_kit.permission_rules.RuleSet",
        "punt_kit.permission_rules.RuleSet.covered",
        "punt_kit.permission_rules.RuleSet.dead",
        "punt_kit.permission_rules.RuleSet.from_strings",
        "punt_kit.permission_rules.RuleSet.orphans",
        "punt_kit.permission_rules.RuleSet.pruned",
        "punt_kit.permission_rules.RuleSet.to_strings",
        "punt_kit.permission_rules.Tier",
        "punt_kit.pii.run_pii",
        "punt_kit.release.run_release",
        "punt_kit.seed.run_seed",
        "punt_kit.status.StatusInfo",
        "punt_kit.status.run_status",
    }
)


def doclint_findings(returncode: int, output: str) -> list[str]:
    """Retain violations that are incompatible with selective Google-style docs."""
    lines = [line for line in output.splitlines() if line.strip()]
    if returncode == 0 and not lines:
        return []
    if returncode != 1 or not lines:
        return [f"pydoclint failed unexpectedly (exit {returncode}): {output!r}"]

    findings: list[str] = []
    for line in lines:
        match = _DOC_DIAGNOSTIC.fullmatch(line)
        if match is None:
            findings.append(f"Unrecognized pydoclint output: {line}")
            continue
        code, message = int(match[1]), match[2]
        if code == 103:
            # A partial Args section is valid unless it names an unknown parameter.
            if _STALE_ARGS in message or _OMITTED_ARGS not in message:
                findings.append(line)
        elif code not in _OPTIONAL_DOC_CODES:
            findings.append(
                line
                if code in _REQUIRED_DOC_CODES
                else f"Unknown pydoclint code: {line}"
            )
    return findings


def tracker_references(source: str, filename: str) -> list[str]:
    """Find tracker references in Python comments and actual docstrings."""
    prose = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(ast.parse(source, filename=filename)):
        if (
            isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and (docstring := ast.get_docstring(node, clean=False)) is not None
        ):
            prose.append((node.body[0].lineno, docstring))

    return [
        f"{filename}:{line}: remove tracker reference {match[0]!r} from code prose"
        for line, content in sorted(prose)
        for match in _TRACKER_REFERENCE.finditer(content)
    ]


def missing_api_symbols(inventory: bytes) -> frozenset[str]:
    """Check that the generated Sphinx inventory contains the expected Python API."""
    header, _, _, compression, body = inventory.split(b"\n", 4)
    if header != b"# Sphinx inventory version 2" or b"zlib" not in compression:
        raise ValueError("Expected a version 2 Sphinx inventory")
    published: set[str] = set()
    for line in zlib.decompress(body).decode().splitlines():
        name, role, _, _, _ = line.split(maxsplit=4)
        if role.startswith("py:"):
            published.add(name)
    return _API_SYMBOLS - published


def _raise_walk_error(error: OSError) -> None:
    raise error


def _python_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix in {".py", ".pyi"}:
        return [root]
    if not root.is_dir():
        raise ValueError(f"Not a Python source path: {root}")
    return sorted(
        directory / name
        for directory, _, names in root.walk(on_error=_raise_walk_error)
        for name in names
        if Path(name).suffix in {".py", ".pyi"}
    )


def _argument_doc_findings(path: Path) -> list[str]:
    with tokenize.open(path) as source:
        tree = ast.parse(source.read(), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not (docstring := ast.get_docstring(node)):
            continue
        if len(_ARGS_HEADER.findall(docstring)) > 1:
            findings.append(f"{path}:{node.lineno}: repeated Args section")
            continue
        try:
            params = parse(docstring, style=DocstringStyle.GOOGLE).params
        except ParseError:
            # pydoclint reports malformed sections separately.
            continue
        if isinstance(node, ast.ClassDef) and params:
            methods = {
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            }
            if "__new__" in methods and "__init__" not in methods:
                findings.append(
                    f"{path}:{node.lineno}: document constructor arguments on __new__"
                )
        seen: set[str] = set()
        for param in params:
            name = param.arg_name.lstrip("*")
            if name in seen:
                findings.append(f"{path}:{node.lineno}: repeated Args entry {name!r}")
            seen.add(name)
    return findings


def _check_docstrings(source: Path) -> list[str]:
    files = _python_files(source)
    if not files:
        return [f"No Python source files found: {source}"]
    result = subprocess.run(
        [
            "pydoclint",
            "--config",
            "pyproject.toml",
            "--quiet",
            "--exclude",
            "",
            "--show-filenames-in-every-violation-message",
            "true",
            *[str(path.resolve()) for path in files],
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    findings = doclint_findings(result.returncode, result.stdout)
    if not findings:
        for path in files:
            findings.extend(_argument_doc_findings(path))
    return findings


def _check_comments(roots: list[Path]) -> list[str]:
    files = {path for root in roots for path in _python_files(root)}
    findings: list[str] = []
    for path in sorted(files):
        with tokenize.open(path) as source:
            findings.extend(tracker_references(source.read(), str(path)))
    return findings


def main() -> int:
    """Run a documentation gate and fail on violations or tool errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="gate", required=True)
    commands.add_parser("docstrings").add_argument("source", type=Path)
    commands.add_parser("comments").add_argument("roots", nargs="+", type=Path)
    commands.add_parser("api").add_argument("inventory", type=Path)
    args = parser.parse_args()
    try:
        if args.gate == "docstrings":
            findings = _check_docstrings(args.source)
        elif args.gate == "comments":
            findings = _check_comments(args.roots)
        else:
            missing = missing_api_symbols(args.inventory.read_bytes())
            findings = [
                f"Missing generated API entry: {name}" for name in sorted(missing)
            ]
    except (OSError, SyntaxError, ValueError, tokenize.TokenError, zlib.error) as error:
        findings = [str(error)]
    for finding in findings:
        print(finding.replace("\r", r"\r").replace("\n", r"\n"), file=sys.stderr)
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
