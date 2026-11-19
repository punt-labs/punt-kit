"""Exercise the clause-to-rule traceability check."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_standards import check

_ROOT = Path(__file__).resolve().parents[1]

_STANDARD = """\
# Logging

### LOG-1: Every log file has one writer

**Applies to:** python, go

Text.

### LOG-2: Never log content

Text.
"""

_PYTHON_RULES = """\
# Python logging

## PY-LOG-1: Use the shared package

**Implements:** LOG-1, LOG-2 · **Gate:** `make lint`
"""

_GO_RULES = """\
# Go logging

## GO-LOG-1: Use one writer

**Implements:** LOG-1 · **Gate:** `review` (evaluator)
"""


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _base() -> dict[str, str]:
    return {
        "standards/logging.md": _STANDARD,
        "lang-rules/python/logging.md": _PYTHON_RULES,
        "lang-rules/go/logging.md": _GO_RULES,
    }


def test_repository_standards_trace() -> None:
    assert check(_ROOT) == []


def test_complete_tree_passes(tmp_path: Path) -> None:
    assert check(_tree(tmp_path, _base())) == []


def test_documents_without_ids_are_not_checked(tmp_path: Path) -> None:
    files = {
        "standards/legacy.md": "# Legacy\n\n## 1. Rule\n",
        "lang-rules/c/c.md": "# C\n\n## C-MEM-1: Free what you allocate\n",
    }
    assert check(_tree(tmp_path, files)) == []


def test_fenced_examples_are_ignored(tmp_path: Path) -> None:
    files = _base()
    files["standards/logging.md"] += "\n```markdown\n### LOG-9: Example\n```\n"
    assert check(_tree(tmp_path, files)) == []


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        (
            "standards/other.md",
            "# Other\n\n### LOG-2: Again\n",
            "duplicate clause LOG-2",
        ),
        (
            "standards/mixed.md",
            "# Mixed\n\n### AA-1: One\n\n### BB-1: Two\n",
            "more than one prefix",
        ),
        (
            "standards/shared.md",
            "# Shared\n\n### LOG-3: Same prefix\n",
            "prefix LOG is already used",
        ),
        (
            "lang-rules/python/extra.md",
            "## PY-LOG-1: Again\n\n**Implements:** LOG-2 · **Gate:** review\n",
            "duplicate rule PY-LOG-1",
        ),
        (
            "lang-rules/python/extra.md",
            "## PY-LOG-2: Ghost\n\n**Implements:** LOG-7 · **Gate:** review\n",
            "cites undefined clause LOG-7",
        ),
        (
            "lang-rules/python/extra.md",
            "## PY-LOG-2: No gate\n\n**Implements:** LOG-2\n",
            "expected '**Implements:** <IDs> · **Gate:** <gate>'",
        ),
        (
            "lang-rules/python/extra.md",
            "## PY-LOG-2: A\n\n**Implements:** LOG-2 · **Gate:** review\n\n"
            "## PY-LOG-3: B\n\nUntraced.\n",
            "rule PY-LOG-3 has no Implements line",
        ),
        (
            "lang-rules/pharo/logging.md",
            "## PH-LOG-1: One writer\n\n**Implements:** LOG-1 · **Gate:** review\n",
            "cites LOG-1, which does not apply to pharo",
        ),
        (
            "standards/new.md",
            "# New\n\n### NEW-1: Uncited\n",
            "clause NEW-1 is cited by no rule",
        ),
        (
            "standards/new.md",
            "# New\n\n### NEW-1: Pharo only\n\n**Applies to:** pharo\n",
            "lang-rules/pharo/ does not exist",
        ),
    ],
)
def test_broken_links_fail(tmp_path: Path, name: str, text: str, expected: str) -> None:
    files = _base()
    files[name] = text
    findings = check(_tree(tmp_path, files))
    assert any(expected in finding for finding in findings), findings


def test_missing_language_rule_fails(tmp_path: Path) -> None:
    files = _base()
    files["lang-rules/go/logging.md"] = "# Go logging\n"
    findings = check(_tree(tmp_path, files))
    assert findings == [
        "standards/logging.md:3: clause LOG-1 applies to go "
        "but no rule in lang-rules/go/ cites it"
    ]


def test_retired_clause_is_exempt_and_uncitable(tmp_path: Path) -> None:
    files = _base()
    files["standards/logging.md"] += "\n### LOG-3: Retired, replaced by LOG-2\n"
    assert check(_tree(tmp_path, files)) == []
    files["lang-rules/go/logging.md"] = _GO_RULES.replace("LOG-1 ·", "LOG-1, LOG-3 ·")
    findings = check(_tree(tmp_path, files))
    assert any("cites retired clause LOG-3" in finding for finding in findings)
