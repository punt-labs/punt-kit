"""Release-specific interpretation of a detected project: version, package
name, install-sh SHA, and template-pin rewriting.

Composes ``punt_kit.detect.ProjectInfo`` rather than subclassing or editing
it — ``detect.py`` is generic project detection, owned separately; this
module adds release-specific behavior (template-pin rewriting, install-sh
SHA) on top.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Self, cast, final

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

# Bundled template files (CI workflow YAMLs deployed by a project's own
# `enable`/`init` commands) sometimes hardcode a pinned `uvx --from` invocation
# of the project's own CLI for supply-chain reasons — running unpinned/latest
# in a customer's CI is rejected. That pin lives outside pyproject.toml and
# plugin.json, so without this scan a fix landing in a template after a
# version already tagged stays stale in every future deployment of that
# template until the NEXT release re-pins it.
_TEMPLATE_PIN_GLOBS: tuple[str, ...] = (
    "src/**/data/*.yml",
    "src/**/data/*.yaml",
    "plugin/**/*.yml",
    "plugin/**/*.yaml",
)


def normalize_package_name(name: str) -> str:
    """PEP 503 normalization key: case- and separator-insensitive.

    PyPI treats ``-``, ``_``, and ``.`` as equivalent separators and names as
    case-insensitive, so ``punt_biff`` and ``Punt-Biff`` both name the same
    package as ``punt-biff``. Comparing raw strings would leave a pin stale
    whenever a template spells the name with a different separator or case
    than ``pyproject.toml``.

    Pure string transform — legitimate PY-OO-7 exception: useful independent
    of any project, shares no vocabulary with ``ReleaseProject``'s fields.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


@final
class ReleaseProject:
    """Release-relevant facts about a detected project."""

    __slots__ = ("_info", "_ops")

    _info: ProjectInfo
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        return self

    def version(self) -> str:
        """Extract current version from pyproject.toml, plugin.json, or git tag."""
        info = self._info
        if info.language == "go":
            return self.latest_tag_version()
        if info.pyproject is None:
            if info.is_plugin:
                data = json.loads(info.plugin_manifest.read_text(encoding="utf-8"))
                version = data.get("version")
                if not isinstance(version, str):
                    self._ops.fail(f"No version in {info.plugin_manifest}")
                return version
            self._ops.fail("No pyproject.toml found")
        project = info.pyproject.get("project")
        if not isinstance(project, dict):
            self._ops.fail("No [project] section in pyproject.toml")
        version = cast("dict[str, object]", project).get("version")
        if not isinstance(version, str):
            self._ops.fail("No version in pyproject.toml [project]")
        return version

    def latest_tag_version(self) -> str:
        """Get the latest semantic version from git tags.

        Public rather than private: ``version()`` calls it for Go projects,
        and ``punt_kit.release._get_latest_tag_version`` (kept for public API
        preservation and tested directly against a bare ``root``) calls it
        too.
        """
        result = self._ops.run(
            ["git", "tag", "--list", "v*", "--sort=-v:refname"],
            cwd=str(self._info.root),
        )
        tags = result.stdout.strip().splitlines()
        if not tags:
            return "0.0.0"
        return tags[0].removeprefix("v")

    def package_name(self) -> str:
        """Extract package name from pyproject.toml."""
        info = self._info
        if info.pyproject is None:
            self._ops.fail("No pyproject.toml found")
        project = info.pyproject.get("project")
        if not isinstance(project, dict):
            self._ops.fail("No [project] section in pyproject.toml")
        name = cast("dict[str, object]", project).get("name")
        if not isinstance(name, str):
            self._ops.fail("No name in pyproject.toml [project]")
        return name

    def marketplace_name(self) -> str | None:
        """Return the plugin's marketplace-visible name for lookup.

        Marketplace entries in ``claude-plugins/.claude-plugin/marketplace.json``
        use the plugin's short name (``punt``, ``vox``, ``lux``), not the PyPI
        distribution name (``punt-kit``). The name lives in the project's own
        plugin.json; because phase 2 runs before the phase 4 plugin swap that
        strips the ``-dev`` suffix, the on-disk manifest reads ``punt-dev`` /
        ``vox-dev`` etc., and the ``-dev`` must be dropped before comparison.
        ``None`` for non-plugin projects — they have no marketplace entry to
        match against.
        """
        info = self._info
        if not info.is_plugin:
            return None
        data = json.loads(info.plugin_manifest.read_text(encoding="utf-8"))
        name = data.get("name")
        if not isinstance(name, str):
            return None
        return name.removesuffix("-dev")

    def self_package_name(self) -> str | None:
        """Return the project's own PyPI package name for self-referential pins.

        Prefers ``pyproject.toml [project] name``. Falls back to the ``name``
        field in the plugin manifest for plugin-only projects that have no
        ``pyproject.toml`` at all — stripped of a trailing ``-dev``, since
        phase 2 runs before the phase 4 plugin swap and the manifest on disk
        still names the dev shell (e.g. ``punt-dev``), not the production
        package a bundled template pins against. ``None`` for non-Python,
        non-plugin projects (e.g. Go CLIs) — there is no self-referential
        package name to match template pins against, and that absence is
        expected, not an error.
        """
        info = self._info
        if info.pyproject is not None:
            return self.package_name()
        if info.is_plugin:
            data = json.loads(info.plugin_manifest.read_text(encoding="utf-8"))
            name = data.get("name")
            if isinstance(name, str):
                return name.removesuffix("-dev")
        return None

    def package_dir(self) -> Path | None:
        """Find the Python package directory (src layout)."""
        src_dir = self._info.root / "src"
        if not src_dir.is_dir():
            return None
        for child in sorted(src_dir.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                return child
        return None

    def install_sh_sha(self) -> str:
        """Get the short SHA of the commit that last modified install.sh.

        This is the correct SHA for install URL pinning. Using the tag SHA
        is wrong for hybrid projects because the tag sits on the
        "prepare plugin for release" commit, which comes *after* the
        version-bump commit that actually changes install.sh.
        """
        result = self._ops.run(
            ["git", "log", "-1", "--format=%h", "--", "install.sh"],
            cwd=str(self._info.root),
        )
        sha = result.stdout.strip()
        if not sha:
            self._ops.fail("No commit found that touches install.sh")
        return sha

    def rewrite_template_pins(self, version: str, *, dry_run: bool) -> list[Path]:
        """Rewrite self-referential ``uvx --from <own-pkg>==X.Y.Z`` template pins.

        Scans ``_TEMPLATE_PIN_GLOBS`` under the project root. Only pins
        matching the project's own package name are rewritten — pins for
        other ``punt-*`` packages are a deliberate supply-chain guarantee,
        not a stylistic preference, and are left untouched.
        """
        info = self._info
        own_pkg = self.self_package_name()
        if own_pkg is None:
            return []
        own_key = normalize_package_name(own_pkg)
        pin_re = re.compile(
            r"uvx --from (?P<pkg>[Pp]unt[-_.][A-Za-z0-9._-]+)"
            r"==(?P<ver>[0-9]+\.[0-9]+\.[0-9]+)"
        )

        def _replace(match: re.Match[str]) -> str:
            if normalize_package_name(match.group("pkg")) != own_key:
                return match.group(0)
            return f"uvx --from {own_pkg}=={version}"

        changed: list[Path] = []
        seen: set[Path] = set()
        for pattern in _TEMPLATE_PIN_GLOBS:
            for path in sorted(info.root.glob(pattern)):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                content = path.read_text(encoding="utf-8")
                new_content = pin_re.sub(_replace, content)
                if new_content == content:
                    continue
                rel = path.relative_to(info.root)
                if dry_run:
                    self._ops.dry(f"{rel}: uvx --from {own_pkg}=={version}")
                else:
                    path.write_text(new_content, encoding="utf-8")
                    self._ops.ok(f"{rel}: uvx --from {own_pkg}=={version}")
                changed.append(path)
        return changed
