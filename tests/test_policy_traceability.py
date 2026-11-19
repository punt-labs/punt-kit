"""Exercise policy definition and citation coverage with isolated corpora."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from tools.check_policy_traceability import main, traceability_findings

if TYPE_CHECKING:
    from pathlib import Path


def _run(args: list[str]) -> int:
    with patch.object(sys, "argv", ["check_policy_traceability.py", *args]):
        return main()


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    standards = tmp_path / "standards"
    standards.mkdir()
    (standards / "logging.md").write_text("## LOG-1: Diagnostics\n")
    (standards / "telemetry.md").write_text("## TEL-1: Usage\n")
    rules = tmp_path / "lang-rules/python"
    rules.mkdir(parents=True)
    (rules / "python-logging.md").write_text(
        "## PY-LOG-1: Observation\n**Implements**: LOG-1, TEL-1.\n"
    )
    return tmp_path


def test_pass(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert traceability_findings(corpus) == []
    assert _run(["--root", str(corpus)]) == 0
    assert "Policy traceability: all definitions cited" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        ("standards/logging.md", "## LOG-2: Sink\n", "LOG-2: no Python rule citation"),
        (
            "lang-rules/python/other.md",
            "## PY-LOG-9: Broken\nTEL-99\n",
            "undefined policy citation: TEL-99",
        ),
        (
            "standards/logging.md",
            "## LOG-1: First\n## LOG-1: Second\n",
            "LOG-1: duplicate policy definition (2 definitions)",
        ),
        ("standards/logging.md", "", "standards/logging.md: no policy definitions"),
    ],
)
def test_violations(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
    path: str,
    source: str,
    expected: str,
) -> None:
    (corpus / path).write_text(source)
    assert any(expected in finding for finding in traceability_findings(corpus))
    assert _run(["--root", str(corpus)]) == 1
    assert expected in capsys.readouterr().err


def test_explicit_gap_is_a_citation(corpus: Path) -> None:
    (corpus / "lang-rules/python/python-logging.md").write_text(
        "## PY-LOG-1: Diagnostics\nLOG-1\n"
        "| Policy ID | Python rule(s) | Gate |\n| TEL-1 | gap | gap |\n"
    )
    assert traceability_findings(corpus) == []


def test_fenced_examples_and_rule_ids_are_not_citations(corpus: Path) -> None:
    (corpus / "lang-rules/python/python-logging.md").write_text(
        "## PY-LOG-1: Not a policy citation\nTEL-1\n"
        "```text\nLOG-1 TEL-99\n```\n~~~md\nLOG-1\n~~~\n"
    )
    assert traceability_findings(corpus) == ["LOG-1: no Python rule citation"]


def test_fenced_definitions_are_not_policies(corpus: Path) -> None:
    (corpus / "standards/logging.md").write_text(
        "## LOG-1: Diagnostics\n```md\n## LOG-2: Example\n```\n"
    )
    assert traceability_findings(corpus) == []


def test_duplicate_across_files(corpus: Path) -> None:
    (corpus / "standards/telemetry.md").write_text(
        "## TEL-1: Usage\n## LOG-1: Duplicate\n"
    )
    findings = traceability_findings(corpus)
    assert "LOG-1: duplicate policy definition (2 definitions)" in findings
    assert "standards/telemetry.md: unexpected policy prefix: LOG-1" in findings


def test_missing_inputs_fail_closed(corpus: Path) -> None:
    (corpus / "lang-rules/python/python-logging.md").unlink()
    assert "lang-rules/python: no rule files" in traceability_findings(corpus)
    (corpus / "standards/logging.md").unlink()
    assert _run(["--root", str(corpus)]) == 1
