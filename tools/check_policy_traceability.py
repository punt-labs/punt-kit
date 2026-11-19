"""Check policy definitions against Python language-rule citations."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

_POLICIES = {
    "standards/logging.md": "LOG",
    "standards/telemetry.md": "TEL",
}


def _prose(source: str) -> str:
    fence = ""
    lines: list[str] = []
    for line in source.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
        elif not fence:
            lines.append(line)
    return "\n".join(lines)


def traceability_findings(root: Path) -> list[str]:
    """Find uncited policies, dangling citations and duplicate definitions.

    Definitions are ID-prefixed Markdown headings in the configured policy
    files. Citations are bare IDs in Python-rule prose, including explicit gap
    rows; Python rule IDs and fenced examples are not policy citations.
    Missing inputs and policy files without definitions fail closed.
    """
    prefixes = "|".join(re.escape(prefix) for prefix in _POLICIES.values())
    identifier = rf"(?:{prefixes})-\d+"
    definition = re.compile(rf"^#{{2,6}}\s+({identifier}):", re.M)
    citation = re.compile(rf"(?<![\w-])({identifier})(?![\w-])")
    definitions: Counter[str] = Counter()
    findings: list[str] = []
    for filename, prefix in _POLICIES.items():
        defined_ids: list[str] = definition.findall(
            _prose((root / filename).read_text())
        )
        if not defined_ids:
            findings.append(f"{filename}: no policy definitions")
        for policy_id in defined_ids:
            if not policy_id.startswith(f"{prefix}-"):
                findings.append(f"{filename}: unexpected policy prefix: {policy_id}")
        definitions.update(defined_ids)
    rules = sorted((root / "lang-rules/python").glob("*.md"))
    if not rules:
        findings.append("lang-rules/python: no rule files")
    cited: set[str] = set()
    for path in rules:
        rule_ids: set[str] = set(citation.findall(_prose(path.read_text())))
        cited.update(rule_ids)
        findings.extend(
            f"{path.relative_to(root)}: undefined policy citation: {policy_id}"
            for policy_id in sorted(rule_ids - definitions.keys())
        )
    findings.extend(
        f"{policy_id}: duplicate policy definition ({count} definitions)"
        for policy_id, count in sorted(definitions.items())
        if count > 1
    )
    findings.extend(
        f"{policy_id}: no Python rule citation"
        for policy_id in sorted(definitions.keys() - cited)
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the traceability gate and fail on violations or unreadable inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    try:
        findings = traceability_findings(args.root)
    except (OSError, UnicodeError) as error:
        findings = [str(error)]
    for finding in findings:
        print(finding, file=sys.stderr)
    if not findings:
        print(
            "Policy traceability: all definitions cited; no dangling or duplicate IDs"
        )
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
