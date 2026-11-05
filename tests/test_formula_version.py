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
    assert FormulaVersion(WITH_RESOURCES).stated() == ("3.5.5",)


def test_a_top_level_version_wins_over_a_resources_version() -> None:
    text = WITH_RESOURCES.replace(
        '  sha256 "abc"\n', '  sha256 "abc"\n  version "4.0.0"\n', 1
    )
    assert FormulaVersion(text).stated() == ("4.0.0", "3.5.5")


def test_a_top_level_version_after_the_resources_still_counts() -> None:
    text = WITH_RESOURCES.replace(
        "  def install", '  version "4.1.0"\n\n  def install', 1
    )
    assert FormulaVersion(text).stated() == ("4.1.0", "3.5.5")


def test_a_version_only_inside_a_resource_is_not_the_formulas() -> None:
    text = """\
class Proj < Formula
  resource "attrs" do
    version "25.1.0"
    url "https://x/attrs-25.1.0.tar.gz"
  end
end
"""
    assert FormulaVersion(text).stated() == ()


@pytest.mark.parametrize(
    ("url", "version"),
    [
        ("proj-0.2.0.tar.gz", "0.2.0"),
        ("v1.2.3.tar.gz", "1.2.3"),
        ("proj-1.2.3rc1.tar.gz", "1.2.3rc1"),
        ("proj-1.2.3.post1.tar.gz", "1.2.3.post1"),
        ("proj-1.2.3a1.tar.gz", "1.2.3a1"),
        ("proj-1.2.3b2.tar.gz", "1.2.3b2"),
        ("proj-1.2.3.dev1.tar.gz", "1.2.3.dev1"),
        ("proj-1.2.3rc1.post2.dev3.tar.gz", "1.2.3rc1.post2.dev3"),
    ],
)
def test_the_version_comes_from_the_archive_name(url: str, version: str) -> None:
    text = f'class P < Formula\n  url "https://h/{url}"\nend\n'
    assert FormulaVersion(text).stated() == (version,)


def test_a_bumped_version_over_a_stale_archive_is_not_the_release() -> None:
    text = (
        "class P < Formula\n"
        '  url "https://h/proj-0.1.0.tar.gz"\n'
        '  version "0.2.0"\n'
        "end\n"
    )
    assert not FormulaVersion(text).is_release("0.2.0")


def test_a_formula_whose_version_and_archive_agree_is_the_release() -> None:
    text = (
        "class P < Formula\n"
        '  url "https://h/proj-0.2.0.tar.gz"\n'
        '  version "0.2.0"\n'
        "end\n"
    )
    assert FormulaVersion(text).is_release("0.2.0")


def test_a_formula_stating_no_version_is_not_the_release() -> None:
    assert not FormulaVersion("class P < Formula\nend\n").is_release("0.2.0")
