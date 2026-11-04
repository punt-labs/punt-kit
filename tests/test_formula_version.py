"""FormulaVersion reads the formula's own version, never a resource's."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.formula_version import FormulaVersion

WITH_RESOURCES = """\
class Proj < Formula
  desc "demo"
  url "https://files.pythonhosted.org/packages/ab/cd/punt_proj-3.5.5.tar.gz"
  sha256 "abc"

  resource "attrs" do
    url "https://files.pythonhosted.org/packages/xx/attrs-25.1.0.tar.gz"
    version "25.1.0"
  end

  resource "zzz" do
    url "https://files.pythonhosted.org/packages/yy/zzz-9.9.9.tar.gz"
  end

  def install
    virtualenv_install_with_resources
  end
end
"""


def test_a_formulas_main_url_wins_over_resource_blocks() -> None:
    assert FormulaVersion(WITH_RESOURCES).value() == "3.5.5"


def test_a_top_level_version_wins_over_a_resources_version() -> None:
    text = WITH_RESOURCES.replace(
        '  sha256 "abc"\n', '  sha256 "abc"\n  version "4.0.0"\n', 1
    )
    assert FormulaVersion(text).value() == "4.0.0"


def test_a_top_level_version_after_the_resources_still_counts() -> None:
    text = WITH_RESOURCES.replace(
        "  def install", '  version "4.1.0"\n\n  def install', 1
    )
    assert FormulaVersion(text).value() == "4.1.0"


def test_a_version_only_inside_a_resource_is_not_the_formulas() -> None:
    text = """\
class Proj < Formula
  resource "attrs" do
    version "25.1.0"
    url "https://x/attrs-25.1.0.tar.gz"
  end
end
"""
    assert FormulaVersion(text).value() is None


@pytest.mark.parametrize(
    ("url", "version"),
    [("proj-0.2.0.tar.gz", "0.2.0"), ("v1.2.3.tar.gz", "1.2.3")],
)
def test_the_version_comes_from_the_archive_name(url: str, version: str) -> None:
    text = f'class P < Formula\n  url "https://h/{url}"\nend\n'
    assert FormulaVersion(text).value() == version
