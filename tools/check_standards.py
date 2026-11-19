"""Check that policy clauses and language rules trace to each other."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^#{1,6} ")
_CLAUSE = re.compile(r"^#{2,6} ([A-Z][A-Z0-9]{1,7})-(\d+): (.+)$")
_RULE = re.compile(r"^#{2,6} ([A-Z][A-Z0-9]*-[A-Z][A-Z0-9]*-\d+[a-z]?): ")
_NEAR_CLAUSE = re.compile(r"^#{2,6} [A-Za-z][A-Za-z0-9]*-\d+\b")
_NEAR_RULE = re.compile(r"^#{2,6} [A-Za-z][A-Za-z0-9]*-[A-Za-z][A-Za-z0-9]*-\d+")
_APPLIES = re.compile(r"^\*\*Applies to:\*\* (.+)$")
_IMPLEMENTS = re.compile(r"^\*\*Implements:\*\*")
_TRACE = re.compile(r"^\*\*Implements:\*\* ([A-Z0-9, -]+?) · \*\*Gate:\*\* (\S.*)$")
_CLAUSE_ID = re.compile(r"^[A-Z][A-Z0-9]{1,7}-\d+$")


@dataclass
class _Clause:
    where: str
    retired: bool
    languages: frozenset[str] | None


@dataclass
class _Rule:
    rule_id: str
    where: str
    language: str
    cites: list[str] = field(default_factory=list[str])
    traced: bool = False


def _lines(path: Path) -> list[tuple[int, str]]:
    """Return numbered lines outside fenced code blocks."""
    kept: list[tuple[int, str]] = []
    fenced = False
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            kept.append((number, line.rstrip()))
    return kept


class _Index:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[str] = []
        self.clauses: dict[str, _Clause] = {}
        self.rules: list[_Rule] = []
        self.prefixes: dict[str, str] = {}

    def add_standard(self, path: Path) -> None:
        current: str | None = None
        doc_prefixes: set[str] = set()
        for number, line in _lines(self.root / path):
            where = f"{path}:{number}"
            if match := _CLAUSE.match(line):
                prefix, clause_id = match[1], f"{match[1]}-{match[2]}"
                doc_prefixes.add(prefix)
                if clause_id in self.clauses:
                    self.findings.append(
                        f"{where}: duplicate clause {clause_id} "
                        f"(first at {self.clauses[clause_id].where})"
                    )
                    current = None
                    continue
                retired = match[3].startswith("Retired")
                self.clauses[clause_id] = _Clause(where, retired, None)
                current = clause_id
            elif _NEAR_CLAUSE.match(line):
                self.findings.append(f"{where}: expected '### <PREFIX>-<n>: <title>'")
                current = None
            elif _HEADING.match(line):
                current = None
            elif current and (match := _APPLIES.match(line)):
                names = {name.strip() for name in match[1].split(",")}
                self.clauses[current].languages = frozenset(names - {""})
        if len(doc_prefixes) > 1:
            self.findings.append(
                f"{path}: clauses use more than one prefix: "
                + ", ".join(sorted(doc_prefixes))
            )
        for prefix in doc_prefixes:
            owner = self.prefixes.setdefault(prefix, str(path))
            if owner != str(path):
                self.findings.append(
                    f"{path}: clause prefix {prefix} is already used by {owner}"
                )

    def add_rule_file(self, path: Path, language: str) -> None:
        file_rules: list[_Rule] = []
        current: _Rule | None = None
        for number, line in _lines(self.root / path):
            where = f"{path}:{number}"
            if match := _RULE.match(line):
                current = _Rule(match[1], where, language)
                file_rules.append(current)
            elif _NEAR_RULE.match(line):
                self.findings.append(
                    f"{where}: expected '## <LANG>-<AREA>-<n>: <title>'"
                )
                current = None
            elif _HEADING.match(line):
                current = None
            elif _IMPLEMENTS.match(line):
                self._add_trace(current, line, where)
        if any(rule.traced for rule in file_rules):
            self.findings.extend(
                f"{rule.where}: rule {rule.rule_id} has no Implements line"
                for rule in file_rules
                if not rule.traced
            )
        self.rules.extend(file_rules)

    def _add_trace(self, rule: _Rule | None, line: str, where: str) -> None:
        match = _TRACE.match(line)
        if rule is None:
            self.findings.append(f"{where}: Implements line outside a rule")
        elif rule.traced:
            self.findings.append(
                f"{where}: rule {rule.rule_id} has two Implements lines"
            )
        elif match is None:
            self.findings.append(
                f"{where}: expected '**Implements:** <IDs> · **Gate:** <gate>'"
            )
        else:
            rule.traced = True
            rule.cites = [cited.strip() for cited in match[1].split(",")]
            self.findings.extend(
                f"{where}: malformed clause ID {cited!r}"
                for cited in rule.cites
                if not _CLAUSE_ID.match(cited)
            )

    def resolve(self, languages: set[str]) -> list[str]:
        """Check citations against clauses and return every finding."""
        seen: dict[str, str] = {}
        cited_by: defaultdict[str, set[str]] = defaultdict(set)
        for rule in self.rules:
            if rule.rule_id in seen:
                self.findings.append(
                    f"{rule.where}: duplicate rule {rule.rule_id} "
                    f"(first at {seen[rule.rule_id]})"
                )
            seen.setdefault(rule.rule_id, rule.where)
            for cited in rule.cites:
                self._check_citation(rule, cited)
                cited_by[cited].add(rule.language)
        for clause_id, clause in sorted(self.clauses.items()):
            if clause.retired:
                continue
            if clause.languages is None and not cited_by[clause_id]:
                self.findings.append(
                    f"{clause.where}: clause {clause_id} is cited by no rule"
                )
            required = clause.languages or frozenset[str]()
            for language in sorted(required - cited_by[clause_id]):
                gap = (
                    f"no rule in lang-rules/{language}/ cites it"
                    if language in languages
                    else f"lang-rules/{language}/ does not exist"
                )
                self.findings.append(
                    f"{clause.where}: clause {clause_id} applies to {language} "
                    f"but {gap}"
                )
        return self.findings

    def _check_citation(self, rule: _Rule, cited: str) -> None:
        clause = self.clauses.get(cited)
        if clause is None:
            if _CLAUSE_ID.match(cited):
                self.findings.append(
                    f"{rule.where}: {rule.rule_id} cites undefined clause {cited}"
                )
        elif clause.retired:
            self.findings.append(
                f"{rule.where}: {rule.rule_id} cites retired clause {cited}"
            )
        elif clause.languages is not None and rule.language not in clause.languages:
            self.findings.append(
                f"{rule.where}: {rule.rule_id} cites {cited}, which does not "
                f"apply to {rule.language}"
            )


def check(root: Path) -> list[str]:
    """Return traceability findings for the standards and rules under root."""
    index = _Index(root)
    for path in sorted((root / "standards").rglob("*.md")):
        index.add_standard(path.relative_to(root))
    rules_root = root / "lang-rules"
    languages = {entry.name for entry in rules_root.iterdir() if entry.is_dir()}
    for language in sorted(languages):
        for path in sorted((rules_root / language).rglob("*.md")):
            index.add_rule_file(path.relative_to(root), language)
    return index.resolve(languages)


def main() -> int:
    """Run the traceability check and fail on any finding."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path())
    args = parser.parse_args()
    try:
        findings = check(args.root)
    except (OSError, UnicodeDecodeError) as error:
        findings = [str(error)]
    for finding in findings:
        print(finding, file=sys.stderr)
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
