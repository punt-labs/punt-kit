# Release Requirements

End state requirements for a Punt Labs project release. Every release
must satisfy all applicable requirements before it is considered complete.

## Originating Repo

These artifacts are modified in the project being released.

### Version Bump

| File | Field | Example |
|------|-------|---------|
| `pyproject.toml` | `version` | `"0.7.1"` |
| `src/<pkg>/__init__.py` | `__version__` | `"0.7.1"` |
| `.claude-plugin/plugin.json` | `version` | `"0.7.1"` (hybrid/plugin only) |
| `install.sh` | `VERSION` | `VERSION="0.7.1"` |

All four locations must agree on the same version string.

### Changelog

`CHANGELOG.md` `[Unreleased]` section is stamped to `[X.Y.Z] - YYYY-MM-DD`.
A new empty `[Unreleased]` heading is inserted above it.

### README

SHA-pinned `install.sh` URLs in `README.md` are updated to point to the
tagged commit (e.g. `raw.githubusercontent.com/.../abc1234/install.sh`).

### Git

- Release commit on `main` contains all version bumps and changelog stamp.
- Tag `vX.Y.Z` points to the release commit (or the plugin-swap commit for
  hybrid projects).
- Tag and `main` are pushed to `origin`.
- For hybrid projects: dev plugin state is restored and pushed after tagging.

### GitHub Release

A GitHub Release is created for tag `vX.Y.Z` with release notes extracted
from the changelog.

### PyPI

- The CI release workflow (triggered by the tag push) publishes the package.
- The released version is installable: `uv tool install <package>==X.Y.Z`.
- The local editable install is restored after verification.

## Cross-Repo Propagation

These artifacts are modified in sibling repos. All changes are committed
and pushed to `main` in their respective repos.

### install-all.sh (punt-kit)

`install-all.sh` curl line for the released project is updated to the new
install.sh SHA:

```
curl -fsSL "$GH/<project>/<new-sha>/install.sh" | sh
```

Applies to: all projects with an `install.sh`.

### Marketplace (claude-plugins)

`.claude-plugin/marketplace.json` entry for the released project is updated:

- `version` set to the release version
- `source.ref` set to the release tag (`vX.Y.Z`)

Applies to: hybrid and plugin projects.

### Org Profile (.github)

`.github/profile/README.md` install-all.sh curl URL is updated to the
current punt-kit `main` SHA (after install-all.sh changes have landed).

Applies to: punt-kit releases only (the profile URL points to punt-kit's
install-all.sh).

### Website (public-website)

`src/data/projects.json` entry for the released project is updated:

- `version` set to the release version
- `installCommand` SHA updated if install.sh changed

Applies to: all projects with a website entry.

## Applicability Matrix

| Requirement | CLI-only | Hybrid | Plugin-only |
|-------------|----------|--------|-------------|
| pyproject.toml version | Yes | Yes | No |
| \_\_init\_\_.py version | Yes | Yes | No |
| plugin.json version | No | Yes | Yes |
| install.sh VERSION | Yes | Yes | No |
| CHANGELOG stamp | Yes | Yes | Yes |
| README SHA update | Yes | Yes | No |
| Git tag + push | Yes | Yes | Yes |
| GitHub Release | Yes | Yes | Yes |
| PyPI publish + verify | Yes | Yes | No |
| install-all.sh SHA | Yes | Yes | No |
| Marketplace update | No | Yes | Yes |
| Org profile SHA | punt-kit only | punt-kit only | No |
| Website version | Yes | Yes | Yes |
