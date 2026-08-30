# Release Engine Phase Fixes — Design

Epic: pkit-f85t (+ pkit-fwql). Fixes five bugs in `src/punt_kit/release.py` that
all fired live during prfaq's v1.8.0 release. Fix order: f85t.1 → f85t.2 →
f85t.4 → f85t.3 → fwql — each section below is self-contained but numbered in
that order.

Orthogonality: this design touches only phase bodies and one helper
(`_get_project_version`, `_wait_for_required_checks`, `_phase6_ci_wait`,
`_phase11_verify`, `_phase2_version_bump`/`_phase4_release_pr`). It does not
move phase functions into a package or change the `_phaseN_*` naming
convention — that restructuring is pkit-i6gj's separate concern.

## 1. Harness extension

### Inventory of existing helpers

| Helper | Location | Shape | Used by |
|---|---|---|---|
| `_fake_gh_run` | `tests/test_release.py:2169` | Builds a `fake_run(cmd, **kwargs) -> MagicMock` closure over a fixed PR list; branches on `cmd[:2]`/`cmd[:3]` prefixes (`git rev-parse`, `gh pr list/create/view/merge`). Returns `(fake_run, issued)` — `issued` is an append-only call log. | `_pr_merge` tests (stale/closed/matching PR resolution, 404-on-branch-delete) |
| `_run_stub` | `tests/test_release.py:4220` | Builds a `fake_run(cmd, **kwargs) -> CompletedProcess` closure over a `dict[str, CompletedProcess]` keyed by `cmd[2]` (the gh subcommand: `"list"`, `"watch"`, `"view"`). `git rev-parse` is special-cased to return the module-level `COMMIT`. | `_phase6_ci_wait` tests (run selection, watch failure/timeout) |
| `_graphql_checks_response` | `tests/test_release.py:1568` | Builds the nested GraphQL JSON shape `_wait_for_required_checks` parses. Not a `_run` stub itself — each `_wait_for_required_checks` test still writes its own inline `fake_run` around this. | `_wait_for_required_checks` tests |
| `_setup_verify_project` / `_setup_fully_passing_verify` | `tests/test_release.py:2357` / `2477` | Real git repos (via `_git`/`_make_sibling`, not mocks) for `.github` and `claude-plugins` siblings, wired through `_resolve_sibling` monkeypatch. Profile-SHA and marketplace checks are exercised against real commits, not fixtures. | `_phase11_verify` profile-SHA tests |
| `_make_release_project` | `tests/test_release.py:89` | Hybrid project: pyproject.toml **with** `[project.scripts]`, plugin.json, install.sh. `is_plugin=True`, `is_hybrid=True`, `language="python"`. | Most phase tests |
| `_make_pure_plugin_project` | `tests/test_release.py:1425` | pyproject.toml **without** `[project.scripts]` (so `cli_commands=[]`, `is_hybrid=False`), still `language="python"`. No install.sh. | wy5 preflight-script tests, pvb install-all.sh loop test |

None of the five fixes need a new mocking *style* — each extends one of the
three existing patterns (`_fake_gh_run`-style closures, `_run_stub`-style
dict dispatch, or the real-git-repo `_setup_verify_project` family). No
parallel harness is introduced.

### New fixtures and helpers

**`_make_language_none_plugin_project(tmp_path) -> Path`** (new, alongside
`_make_pure_plugin_project` at `tests/test_release.py:1425`). The existing
`_make_pure_plugin_project` still writes a `pyproject.toml` (without
`[project.scripts]`), so `info.language == "python"` and `info.pyproject is
not None` — it does not reproduce f85t.1, whose precondition is `info.pyproject
is None` (prfaq has no pyproject.toml at all). The new fixture:

- No `pyproject.toml`, no `package.json`, no `go.mod` → `detect()` leaves
  `language=None`, `pyproject=None` (`src/punt_kit/detect.py:100-133`).
- `.claude-plugin/plugin.json` with a `version` field → `is_plugin=True`.
- `scripts/release-plugin.sh` + `scripts/restore-dev-plugin.sh` (phase 1
  preflight requires these for any `is_plugin` project — see
  `test_preflight_checks_scripts_for_pure_plugin`).
- CHANGELOG.md (same shape as the other fixtures).
- No `install.sh` (matches the pure-plugin marketplace-only install path).

**`_graphql_no_required_checks_response()`** (new, next to
`_graphql_checks_response` at `tests/test_release.py:1568`) — returns the
nested shape with an empty `contexts.nodes` list, for f85t.4's "no branch
protection" tests.

**`_protection_response(protected: bool) -> MagicMock`** (new, in the
`_wait_for_required_checks` test section, `tests/test_release.py:1561`
onward) — builds the `MagicMock` for a `gh api
repos/OWNER/REPO/branches/main/protection` call: `protected=True` →
`returncode=0, stdout='{"required_status_checks": {...}}'`; `protected=False`
→ `returncode=1, stdout="", stderr='gh: Branch not protected (HTTP 404)'`.
Every f85t.4 test's inline `fake_run` gains one more branch: `if cmd[:2] ==
["gh", "api"] and cmd[2].endswith("/protection"):` dispatches to this
fixture. This follows the existing convention in this test section (each
test defines its own `fake_run` closure around `_graphql_checks_response`)
rather than retrofitting `_fake_gh_run`, whose `cmd[:3]` dispatch table is
PR-lifecycle-specific and unrelated to the GraphQL/protection calls
`_wait_for_required_checks` makes.

**`_run_stub` gains no new key set** for f85t.2 — `_phase6_ci_wait`'s new
early-return guard is pure Python (`"release.yml" not in info.workflow_files`)
and needs no subprocess mock at all. Its tests construct `info` directly
(no `_run` patch needed for the skip-path tests) and reuse the existing
`_run_stub`/`_fake_which` pair only for the still-fails-when-it-should
regression test (a non-plugin project missing release.yml).

**`_make_sibling` reuse for f85t.3** — no new sibling-builder helper. The
existing `_setup_verify_project` (`tests/test_release.py:2357`) already
builds a `claude-plugins` sibling with a `marketplace.json` entry; f85t.3's
tests add a **second** `.github/install-all.sh` shape (the marketplace-loop
line, `curl -fsSL "$GH/claude-plugins/<sha>/install.sh"`) via the same
`_make_sibling` call, and pin the profile README to a commit of `.github`
whose `install-all.sh` carries that line. This is data setup, not a new
helper — see §2.5 for the exact fixture shape.

## 2. Fixes

### 2.1 — f85t.1: `_get_project_version` has no plugin-only branch

**Function**: `_get_project_version(info: ProjectInfo) -> str`
(`src/punt_kit/release.py:239`).

**ProjectInfo fields branched on**: `info.language` (existing), `info.pyproject`
(existing), `info.is_plugin` (new branch), `info.plugin_manifest` (existing
property, raises if `plugin_manifests` is empty — safe here because it's
guarded by `info.is_plugin`).

**Before**:

```python
def _get_project_version(info: ProjectInfo) -> str:
    if info.language == "go":
        return _get_latest_tag_version(info.root)
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    ...
```

**After** — insert the plugin branch between the Go check and the
pyproject-required failure, so a plugin-only project (pyproject absent) is
resolved before falling into `_fail`:

```python
def _get_project_version(info: ProjectInfo) -> str:
    if info.language == "go":
        return _get_latest_tag_version(info.root)
    if info.pyproject is None:
        if info.is_plugin:
            data = json.loads(info.plugin_manifest.read_text(encoding="utf-8"))
            version = data.get("version")
            if not isinstance(version, str):
                _fail(f"No version in {info.plugin_manifest}")
            return version
        _fail("No pyproject.toml found")
    ...
```

This is the same read `_phase2_version_bump` already does on the write side
(`json.loads(plugin_json.read_text(...))`, `src/punt_kit/release.py:1119`) and
the same read `_phase11_verify` does to check plugin.json's version
(`src/punt_kit/release.py:2688`) — no new parsing convention.

**Adjacent fix, same root cause, same function's precondition guard**: the
`run_release` resume-path caller at `src/punt_kit/release.py:3092-3095`
still hard-fails *before* calling `_get_project_version` for a **fresh**
plugin-only release:

```python
if info.pyproject is None and info.language != "go":
    _fail("Version required for plugin-only projects (no pyproject.toml)")
```

Once `_get_project_version` can resolve a plugin-only version, this guard is
stricter than necessary and creates a fresh-vs-resume asymmetry for the same
project shape (resume auto-detects, fresh does not). Recommend narrowing it
to `if info.pyproject is None and info.language != "go" and not
info.is_plugin:`. This is in the same function, three lines from the bug's
own fresh-release call site, and is optional relative to the bead's
acceptance criteria (which scopes to `--resume-from`) — flagged for the
leader to confirm in scope or defer.

**New/modified tests** (`tests/test_release.py`, new section after the
`_get_latest_tag_version` tests or near `_make_pure_plugin_project`):

- `test_get_project_version_plugin_only_reads_plugin_json` — uses
  `_make_language_none_plugin_project`; asserts `_get_project_version(info)
  == "0.1.0"`.
- `test_get_project_version_plugin_only_missing_version_fails` — plugin.json
  with no `version` key; asserts `ReleaseError` via `_fail`.
- `test_get_project_version_python_unaffected` — existing
  `_make_release_project`; asserts unchanged behavior (guards against a
  regression where the new branch shadows the pyproject path).
- `test_get_project_version_go_unaffected` — existing Go fixture (see
  `_get_latest_tag_version` tests); asserts unchanged behavior.
- `test_run_release_resume_plugin_only_no_version_flag` (integration,
  exercises `run_release`'s resume path at `:3107`, not just the helper) —
  `--resume-from` a phase after 1, no `--version`, plugin-only project;
  asserts no `ReleaseError` at version-resolution time (the failure this bead
  reports verbatim: "Error: No pyproject.toml found").
- If the adjacent fix (line 3092) is in scope:
  `test_run_release_fresh_plugin_only_no_version_flag` — same fixture, no
  `--resume-from`, no `--version`; asserts version auto-detects from
  plugin.json instead of failing.

**Harness used**: none of these need subprocess mocking — `_get_project_version`
and the resume-path check are pure filesystem reads. `_run_release` tests
patch `_run`/`shutil.which` only far enough to isolate the version-resolution
step (pattern: stop `run_release` after phase 1/version-detection by making
phase 2 raise, matching the existing "verify a specific early failure" style
used elsewhere in this file, e.g. `test_phase11_verify_fails_when_install_all_missing`).

### 2.2 — f85t.2: `_phase6_ci_wait` waits on a release.yml that doesn't exist

**Function**: `_phase6_ci_wait(info: ProjectInfo, version: str, *, dry_run: bool) -> None`
(`src/punt_kit/release.py:1629`).

**ProjectInfo fields branched on**: `info.workflow_files` (existing field,
populated at `src/punt_kit/detect.py:160-163` from `.github/workflows/*.yml`
and `*.yaml` filenames), `info.is_plugin`, `info.is_hybrid` (both existing).

**Before**: the function proceeds unconditionally from
`console.print("\n[bold]Phase 6: Wait for CI[/bold]")` straight into the
`gh run list --workflow release.yml` poll (`_TagRunSelector.list_command`,
`src/punt_kit/release.py:1487-1499`).

**After** — insert a guard immediately after the header print, before the
`dry_run` branch (so `--dry-run` also reports the skip instead of printing a
command that will never run):

```python
def _phase6_ci_wait(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    console.print("\n[bold]Phase 6: Wait for CI[/bold]")

    if "release.yml" not in info.workflow_files:
        if info.is_plugin and not info.is_hybrid:
            _ok("No release.yml workflow — pure plugin, nothing to wait for")
            return
        _fail(
            "Expected .github/workflows/release.yml for this project but none "
            "was found — this is a misconfiguration, not a plugin-only skip "
            f"(workflows present: {info.workflow_files or 'none'})"
        )

    tag = f"v{version}"
    ...
```

This mirrors phase 8's existing pattern (`if info.language != "python":
return`, `src/punt_kit/release.py:1800-1801`) for the auto-skip branch, and
adds the bead's alternative (b) — an actionable failure — for every project
shape that is *not* a pure plugin, so a Python/Go/hybrid project silently
missing its release workflow still fails loudly instead of skipping.

**New/modified tests** (`tests/test_release.py`, new section near the
existing `_phase6_ci_wait` tests, after line ~4390):

- `test_phase6_skips_for_pure_plugin_without_release_yml` — `info` built
  directly from `ProjectInfo(..., is_plugin=True, workflow_files=["docs.yml",
  "biff-notify.yml"])` or via `_make_pure_plugin_project` with its
  `.github/workflows/` populated accordingly; asserts no `ReleaseError`, no
  `_run` call issued (patch `_run` to raise `AssertionError` if invoked, to
  prove the skip short-circuits before any subprocess call).
- `test_phase6_fails_actionably_when_python_project_missing_release_yml` —
  `_make_release_project` fixture with its `.github/workflows/release.yml`
  never created (i.e. `info.workflow_files` doesn't include it); asserts
  `ReleaseError` with a message containing `"release.yml"` and
  `"misconfiguration"`.
- `test_phase6_hybrid_missing_release_yml_still_fails` — `is_plugin=True,
  is_hybrid=True`, no `release.yml` in `workflow_files`; asserts the failure
  path, not the skip path (hybrid projects are expected to publish to PyPI
  and must have the workflow).
- `test_phase6_proceeds_normally_when_release_yml_present` — regression
  guard: existing `_make_release_project` (which the fixture must be updated
  to include a `.github/workflows/release.yml` file — see note below) with
  the current `_run_stub`-based mocks; asserts the existing pass-through
  behavior (this exercises the untouched code path after the new guard).

**Fixture note**: `_make_release_project` (`tests/test_release.py:89`) does
not currently create any `.github/workflows/` directory, so
`info.workflow_files == []` for every existing test that uses it — **every
existing `_phase6_ci_wait` test would hit the new `_fail` branch** unless the
fixture is updated. `_make_release_project` must gain a
`.github/workflows/release.yml` empty placeholder file (mirroring how it
already fabricates `scripts/release-plugin.sh` as a placeholder) as part of
this fix, in the same commit as the guard. This is the one fixture change
that is not additive — flagged so the implementer doesn't discover it via 20
failing tests.

**Harness used**: none for the skip/fail paths (pure Python branch on
`info.workflow_files`, no `_run` call reached). The regression test for the
present-and-passing path reuses the existing `_run_stub` dict-dispatch
pattern already used for `_phase6_ci_wait` (`tests/test_release.py:4220`)
unchanged.

### 2.3 — f85t.4: `_wait_for_required_checks` has no branch-protection fallback

**Function**: `_wait_for_required_checks(gh: str, cwd: str, pr_number: int) -> None`
(`src/punt_kit/release.py:583`).

**ProjectInfo fields branched on**: none — this function takes `gh`/`cwd`/
`pr_number`, not a `ProjectInfo`. The branch-protection state comes from a
new `gh api` call, not project detection.

**Before**: `required = [c for c in checks if c.get("isRequired")]`
(`:758`); if empty for more than 24 polls (2 minutes), `_fail("No required
checks found on PR #{pr_number} after 2 minutes -- check branch protection
configuration")` (`:762-766`). No branch-protection check is ever made — the
message names the likely cause but the code never confirms it.

**After** — resolve branch-protection presence once, before the polling
loop starts (a single extra `gh api` call per `_wait_for_required_checks`
invocation, not per poll), and use it to pick which check list matters:

```python
def _wait_for_required_checks(gh: str, cwd: str, pr_number: int) -> None:
    repo_slug = _get_github_repo(Path(cwd))
    if not repo_slug or "/" not in repo_slug:
        _fail(f"Cannot determine GitHub owner/repo from git remote in {cwd}")
    owner, repo_name = repo_slug.split("/", 1)

    branch_protected = _branch_protection_exists(gh, cwd, owner, repo_name)
    if not branch_protected:
        _warn(
            f"No branch protection configured on {owner}/{repo_name}'s main "
            "branch — waiting for ALL checks to pass instead of only required "
            "ones"
        )

    _info(f"Waiting for {'required' if branch_protected else 'all'} CI checks "
          f"on PR #{pr_number}...")
    ...
    while time.time() < deadline:
        ...
        relevant = (
            [c for c in checks if c.get("isRequired")]
            if branch_protected
            else checks
        )
        if not relevant:
            no_checks_attempts += 1
            ...
        ...
```

New helper, placed immediately above `_wait_for_required_checks`:

```python
def _branch_protection_exists(gh: str, cwd: str, owner: str, repo_name: str) -> bool:
    """True if ``main`` has a branch protection rule; False on a confirmed 404.

    ``gh api .../branches/main/protection`` 404s with "Branch not protected"
    when none is configured. Any other failure (network, auth, rate limit) is
    NOT treated as "unprotected" — it falls through as True so the existing
    isRequired-only wait behavior is unchanged for errors unrelated to branch
    protection, and a transient API hiccup here cannot silently widen the
    check set for a repo that genuinely has protection.
    """
    result = _run(
        [gh, "api", f"repos/{owner}/{repo_name}/branches/main/protection"],
        cwd=cwd,
        check=False,
    )
    if result.returncode == 0:
        return True
    combined = (result.stderr + result.stdout).lower()
    return "404" not in combined and "branch not protected" not in combined
```

`_run` here uses the module default timeout (`_DEFAULT_RUN_TIMEOUT`, a
metadata call) — no new timeout budget needed.

**Behavioral note (accepted, not a defect)**: falling back to "ALL checks"
includes informational-only checks such as "Claude Code Review" that the
`isRequired`-filtered path deliberately ignores (see the function's own
docstring, `:589`). This is what the bead's acceptance criterion (a)
explicitly asks for ("falls back to waiting for ALL checks to pass") for a
repo that has made a deliberate choice not to configure branch protection —
documented here so review doesn't flag it as an oversight.

**New/modified tests** (`tests/test_release.py`, new section after the
existing `_wait_for_required_checks` tests, i.e. after line ~1780-ish where
that block ends):

- `test_branch_protection_exists_true_on_200` — `_branch_protection_exists`
  direct unit test; `fake_run` returns `returncode=0`; asserts `True`.
- `test_branch_protection_exists_false_on_404` — `fake_run` returns
  `returncode=1, stderr="gh: Branch not protected (HTTP 404)"`; asserts
  `False`.
- `test_branch_protection_exists_true_on_unrelated_error` — `fake_run`
  returns `returncode=1, stderr="gh: API rate limit exceeded"`; asserts
  `True` (fail-safe: does not widen the check set on an unrelated error).
- `test_wait_for_required_checks_falls_back_to_all_checks_when_unprotected` —
  `fake_run` dispatches the protection call to a 404 `MagicMock`
  (`_protection_response(protected=False)`) and the GraphQL call to
  `_graphql_checks_response` with checks that have `isRequired=False` (or
  missing) but `conclusion=SUCCESS`/`status=COMPLETED`; asserts the function
  returns without raising, proving the non-required checks were waited on
  and treated as the pass condition.
- `test_wait_for_required_checks_still_requires_only_required_when_protected` —
  regression guard: protection call returns 200; same non-required-only
  check set as above; asserts the existing `_fail("No required checks
  found...")` behavior is unchanged when protection genuinely exists.
- `test_wait_for_required_checks_warns_once_on_fallback` (optional,
  `capsys`) — asserts the `_warn` fallback message is printed exactly once,
  not once per poll (since branch-protection is resolved once, before the
  loop, this is really a proof of function structure, not a separate
  behavior).

**Harness used**: the ad hoc `fake_run` style already used throughout this
test section (`tests/test_release.py:1596` onward), extended with one more
`cmd` prefix branch for `["gh", "api", ...protection]`. `_protection_response`
(§1) centralizes the two-shape response so five new tests don't hand-roll the
same `MagicMock` construction five times.

### 2.4 — f85t.3: Phase 11 profile-SHA check false-positives for marketplace-only plugins

**Function**: `_phase11_verify(info: ProjectInfo, version: str, *, dry_run: bool) -> None`
(`src/punt_kit/release.py:2646`), specifically the "6. Profile SHA" block
(`:2806-2875`).

**ProjectInfo fields branched on**: `info.is_plugin`, `info.is_hybrid`
(both existing) — used to decide whether the direct-URL pattern is even
expected to exist, mirroring check "4. install-all.sh entry" immediately
above it (`:2713-2760`), which already branches the same way between
`curl_match` (direct SHA URL) and the `for plugin in` loop pattern.

**Before**: the check searches `show_result.stdout` (the pinned commit's
`install-all.sh` content) for `\$GH/{project_name}/{install_sha}[0-9a-fA-F]*
/install\.sh` only. For a marketplace-only plugin, this pattern can never
exist — `install-all.sh` only ever grows a `for plugin in ...` loop entry
for such projects (confirmed at `.github/install-all.sh:74`, "Step 3: Pure
plugins"), never a per-project curl line.

**The marketplace-pin chain** (confirmed against the live `.github`
repo, `.github/install-all.sh:45`): `install-all.sh` pins the
`claude-plugins` installer itself by SHA: `curl -fsSL
"$GH/claude-plugins/aa5a34d/install.sh" | sh`. So for a marketplace-only
plugin, the chain to verify is: profile SHA → (this design's existing code
already resolves) → `install-all.sh` content at that SHA → extract the
`claude-plugins` pin SHA from *that* content → in the `claude-plugins`
sibling, at that pinned SHA, read `.claude-plugin/marketplace.json` → confirm
this project's entry has `version == version` and `source.ref == f"v{version}"`
(same fields check "5. Marketplace" already validates against the sibling's
current working tree, `:2777-2804`, but against a **historical, pinned**
commit here instead of the working tree).

**After** — inside the existing `else:` branch of check 6
(`src/punt_kit/release.py:2836` onward), after computing `show_result`
(the pinned `.github` commit's `install-all.sh` content) and before the
existing `current_entry` regex:

```python
else:
    project_name = repo.split("/")[-1]
    direct_pattern = (
        rf"\$GH/{re.escape(project_name)}/"
        rf"{re.escape(_get_install_sh_sha(info.root))}[0-9a-fA-F]*/install\.sh"
    )
    current_entry = re.search(direct_pattern, show_result.stdout)
    if current_entry is not None or not (info.is_plugin and not install_sh.exists()):
        # unchanged: direct-URL path (CLI/hybrid projects, or a plugin that
        # happens to also have install.sh)
        checks.append(("profile SHA", current_entry is not None, ...))
    else:
        # marketplace-pin chain for a marketplace-only plugin
        mp_pin = re.search(
            r"\$GH/claude-plugins/([0-9a-fA-F]{7,40})/install\.sh",
            show_result.stdout,
        )
        if mp_pin is None:
            checks.append(
                ("profile SHA", False,
                 f"SHA={profile_sha} (no claude-plugins pin in install-all.sh)")
            )
        else:
            cp_sibling = _resolve_sibling(info.root, "claude-plugins")
            ok, detail = _verify_marketplace_pin_chain(
                cp_sibling, mp_pin.group(1), project_name, version, tag
            )
            checks.append(("profile SHA", ok, f"SHA={profile_sha} ({detail})"))
```

New helper (co-located with `_resolve_sibling`/`_validate_sibling`,
`src/punt_kit/release.py:2020` area):

```python
def _verify_marketplace_pin_chain(
    cp_sibling: Path | None,
    claude_plugins_sha: str,
    project_name: str,
    version: str,
    tag: str,
) -> tuple[bool, str]:
    """Check a pinned claude-plugins commit's marketplace.json for this project.

    Returns ``(passed, detail)``. Used only for marketplace-only plugins,
    where the profile-SHA check has no direct install URL to verify against
    (see f85t.3) — the pin chain (profile -> install-all.sh's claude-plugins
    SHA -> that commit's marketplace.json) is the equivalent invariant.
    """
    if cp_sibling is None:
        return False, "claude-plugins sibling not found"
    show = _run(
        ["git", "show", f"{claude_plugins_sha}:.claude-plugin/marketplace.json"],
        cwd=str(cp_sibling),
        check=False,
    )
    if show.returncode != 0:
        return False, f"claude-plugins@{claude_plugins_sha} does not resolve"
    data = cast("dict[str, object]", json.loads(show.stdout))
    plugins = cast("list[dict[str, object]]", data.get("plugins", []))
    for p in plugins:
        src = cast("dict[str, str]", p.get("source", {}))
        if str(src.get("repo", "")).endswith("/" + project_name):
            ok = str(p.get("version", "")) == version and str(src.get("ref", "")) == tag
            return ok, f"claude-plugins@{claude_plugins_sha} version={p.get('version')}, ref={src.get('ref')}"
    return False, f"claude-plugins@{claude_plugins_sha} has no entry for {project_name}"
```

**New/modified tests** (`tests/test_release.py`, new section after
`test_phase11_verify_fails_when_install_all_missing`, ~`:2636` onward):

- `test_phase11_verify_profile_sha_marketplace_chain_passes` — extend
  `_setup_verify_project` (or add a sibling variant
  `_setup_verify_project_marketplace_only`) so `.github`'s
  `install-all.sh` has **no** direct `$GH/proj/<sha>/install.sh` line, only
  a `for plugin in ... proj ...` loop entry (matching check 4's existing
  `test_verify_finds_pure_plugin_in_install_all` fixture shape,
  `tests/test_release.py:1512`) plus a `$GH/claude-plugins/<sha>/install.sh`
  pin line; the `claude-plugins` sibling's marketplace.json at that pinned
  commit has a matching `version`/`ref` entry; the profile README pins the
  `.github` commit whose `install-all.sh` carries that content. Asserts no
  raise.
- `test_phase11_verify_profile_sha_marketplace_chain_stale_version` — same
  shape but the pinned `claude-plugins` commit's `marketplace.json` entry has
  an older `version`; asserts `ReleaseError`.
- `test_phase11_verify_profile_sha_marketplace_chain_no_claude_plugins_pin` —
  `.github`'s `install-all.sh` has neither a direct URL nor a
  `claude-plugins` pin line; asserts `ReleaseError` with "no claude-plugins
  pin" in the detail.
- `test_phase11_verify_profile_sha_marketplace_chain_missing_sibling` —
  `claude-plugins` sibling absent (`_resolve_sibling` returns `None`);
  asserts `ReleaseError` (this is a real defect, not a tolerated
  `_GITHUB_ABSENT_SKIP` case — the sibling being absent for a marketplace-only
  plugin means the chain genuinely cannot be verified, unlike the `.github`-absent
  case which is a tolerated meta-repo shape).
- `test_phase11_verify_profile_sha_direct_url_path_unaffected` — regression
  guard: existing `_setup_verify_project`/`_setup_fully_passing_verify`
  (hybrid/CLI project with a direct install URL) still passes through the
  unchanged branch, proving `is_plugin and not install_sh.exists()` is the
  correct discriminator and doesn't accidentally divert CLI/hybrid projects
  into the new chain.

**Harness used**: the real-git-repo `_setup_verify_project` family (§1) —
no `MagicMock`/`_run` patching, since this check's correctness depends on
actual commit history and `git show` resolution, exactly like the existing
profile-SHA tests it sits beside.

### 2.5 — fwql: README install-SHA guard fails at tag time (phase-ordering circularity)

**Function named in the mission contract**: `_phase2_version_bump`
(`src/punt_kit/release.py:1045`). **Helper**: `_bump_readme_install_sha`
(`src/punt_kit/release.py:1392`).

**Root cause, precisely**: `_bump_readme_install_sha` calls
`_get_install_sh_sha`, which runs `git log -1 --format=%h -- install.sh`
(`:229-232`) — i.e. "the SHA of whichever commit last touched install.sh, as
of the current checkout." Today this only runs in `_phase9_post_release`
(`:1982`), **after** phase 4's squash-merge and phase 5's tag. At the moment
the tag is created (phase 5), README.md still carries the *previous*
release's SHA pin, while `install.sh` on the just-merged main already has
the new `VERSION=`. `scripts/check-readme-install-sha.sh`
(confirmed at `quarry/scripts/check-readme-install-sha.sh:90`, same script
this org uses across repos) diffs `git show <readme_pin>:install.sh` against
the **working-tree** `install.sh` byte-for-byte — that diff is real and the
guard's failure is correct given the state it observes; the state itself is
wrong for the ~1-3 minutes between tag and phase 9's fix.

**Why this cannot be fixed by literally editing inside
`_phase2_version_bump`, as named in the mission contract.** The mission's
success criterion 6 says pin the README "AFTER writing the new VERSION" —
i.e. call `_bump_readme_install_sha` at the tail of `_phase2_version_bump`,
before the branch is pushed. At that point in the release, `install.sh`'s new
content is either (a) uncommitted (so `_get_install_sh_sha` still returns the
*previous* commit — wrong SHA, same bug in a new place), or (b) committed as
part of step 2d (`:1161-1195`) and then read back — which works, but that
commit still lives on the **release branch**, not `main`. Phase 4 merges that
branch with `gh pr merge --squash --delete-branch`
(`src/punt_kit/release.py:995-996`). Squash-merge creates one *new* commit on
`main`; the release branch's own commits become unreachable from any ref the
moment the branch is deleted. A subsequent CI checkout of the tag
(`fetch-depth: 0`, which fetches full history for existing refs, not
arbitrary dangling objects) will not contain that orphaned commit. The
guard's own precondition check —
`git rev-parse --verify --quiet "${readme_sha}^{commit}"`
(`quarry/scripts/check-readme-install-sha.sh:77`) — would then fail with "SHA
not present in local git object DB," which is fwql's failure mode with a
different symptom, not a fix. **This is a substantive design issue for the
leader to rule on before implementation** (per this repo's org CLAUDE.md
requirement to escalate design-time issues rather than let implementation
discover them).

**Recommended fix (Option B — preferred): pin after the squash-merge lands,
not before it.**

`_phase4_release_pr` (`src/punt_kit/release.py:1291`) already calls
`_pr_merge`, which itself checks out `main`, pulls, and returns
`git rev-parse --short HEAD` (`:1041`/`:924`/`:980`) — i.e. the squashed
commit SHA, which is now `main`'s own permanent history (not an orphaned
branch commit). Capture that return value and pin the README immediately
after, in the same phase:

```python
def _phase4_release_pr(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    ...
    merge_sha = _pr_merge(cwd=root, branch=branch, title=f"chore: release v{version}", dry_run=dry_run)
    if not dry_run:
        _land_readme_sha_pin(info, version, dry_run=dry_run)
    return merge_sha
```

New helper `_land_readme_sha_pin(info, version, *, dry_run) -> None`
(co-located near `_bump_readme_install_sha`, `:1392`), extracted from the
existing inline logic in `_phase9_post_release`
(`src/punt_kit/release.py:1980-1990`: call `_bump_readme_install_sha`, check
`git status --porcelain -- README.md`, stage+commit if dirty) but pushed via
a **second** small PR/branch cycle (`release-readme-pin/v{version}`, reusing
`_pr_merge` exactly as phase 9 already does for `post-release/v{version}`) —
this repo's org convention forbids direct pushes to `main` even for
single-file automated changes (org CLAUDE.md: "no direct pushes to main,
even for docs"; phase 9's own README-bump already goes through a PR for this
reason, `:2006-2011`). `_phase9_post_release` then **drops** its
README-SHA-bump block entirely (it becomes a no-op landing on an
already-correct README) and its docstring changes from "Dev plugin restore
and README SHA bump via PR" to "Dev plugin restore via PR."

This adds one more PR/CI cycle between phase 4 and phase 5 per release. It
is the same cost `_phase9_post_release` already pays today for the identical
operation — it moves an existing cost earlier, it does not add a new kind of
cost.

**Option A (as literally named in the mission contract) — rejected**: call
`_bump_readme_install_sha` inside `_phase2_version_bump` after the git commit
at step 2d. Rejected per the reachability argument above: the pinned SHA can
become an orphaned, potentially-unfetchable object once phase 4 squash-merges
and deletes the branch. This failure mode is intermittent (it depends on
whether GitHub has already pruned the dangling object and whether the CI
runner's fetch happens to include it), which makes it strictly worse than
today's deterministic false-positive — a flaky guard is harder to diagnose
than an always-failing one.

**Bead's own rejected options (carried forward, unchanged)**:

- **Option 2 — pin to a stable ref/tag instead of a SHA.** Rejected: loses
  byte-equality, which is the property `check-readme-install-sha.sh`
  exists to guarantee (see that script's own header comment, lines 4-13).
- **Option 3 — make the guard non-fatal.** Rejected: weakens a working
  invariant to paper over a phase-ordering bug; the guard has correctly
  caught a real staleness class before (see the script's header, "that is
  exactly how a stale 6f90f11 SHA shipped once, unnoticed").

**New/modified tests** (`tests/test_release.py`):

- `test_phase4_release_pr_pins_readme_after_merge` — `_pr_merge` mocked via
  `_fake_gh_run` (§1, already returns a merge SHA path); asserts
  `_land_readme_sha_pin`/`_bump_readme_install_sha` is invoked with the
  post-merge `info.root` state (README.md content changes to reference the
  new `install.sh` SHA) and that a **second** `gh pr create`/`gh pr merge`
  pair is issued (distinct branch name `release-readme-pin/v{version}`) —
  extend `_fake_gh_run`'s `issued` call log assertions.
- `test_land_readme_sha_pin_noop_when_readme_already_current` — README
  already pins the correct SHA (resume case); asserts no PR is created
  (mirrors the existing `_phase9_post_release` "no post-release changes
  needed" resume path, `:1992-2004`).
- `test_phase9_post_release_no_longer_bumps_readme` — regression guard:
  `_phase9_post_release` run against a project whose README is *already*
  current (as phase 4 now guarantees); asserts the dev-restore-only path
  runs and no README-specific commit is made.
- `test_readme_sha_pin_survives_tag` (integration-shaped) — build a real git
  repo (reuse `_git`/`_make_release_project` helpers, not mocks, since this
  is exactly the byte-equality property under test): run the phase-4 pin
  logic against a real commit, then assert `git show <pinned-sha>:install.sh`
  is byte-identical to the working tree's `install.sh` **and** that the
  pinned SHA is reachable from `main` (`git merge-base --is-ancestor
  <pinned-sha> main` exits 0) — this is the direct regression test for the
  bug (byte-equality alone doesn't catch the reachability defect Option A
  has; this test is written to fail against Option A and pass against
  Option B).

**Harness used**: `_fake_gh_run` (§1) extended with a second branch/PR-number
pair in its dispatch table (it currently assumes one PR per test — needs a
`branch -> pr_number` mapping instead of a single implicit PR). The
reachability regression test uses real git repos exclusively (no mocks
possible — reachability is a property of the actual object graph).

## 3. Ordering constraints

1. **Harness fixtures first** (§1): `_make_language_none_plugin_project`,
   `_protection_response`, `.github/workflows/release.yml` addition to
   `_make_release_project`, and `_fake_gh_run`'s multi-PR dispatch table all
   need to land before the fixes that depend on them, or every fix's tests
   are written against a moving fixture.
2. **f85t.1 → f85t.2 → f85t.4 → f85t.3 → fwql**, per the mission contract's
   ordering. f85t.1 and f85t.2 are independent of each other and could be
   reordered without cost; f85t.4 is independent of both. f85t.3 depends on
   nothing else in this set functionally, but its tests reuse the
   `_setup_verify_project` fixture family, which is easiest to extend once
   (not twice) — doing it after f85t.1/2/4 avoids fixture churn mid-epic.
3. **fwql must be last** because it is the only fix that changes a *call
   site* shared with another phase (moves logic out of
   `_phase9_post_release` into `_phase4_release_pr`) rather than adding an
   isolated guard inside one phase. Landing it last means its tests are
   written against an otherwise-stable `_phase9_post_release` and
   `_phase4_release_pr`, so a test failure unambiguously means the fwql
   change broke something, not an interaction with one of the other four
   fixes.
4. **fwql's Option A vs Option B decision blocks its own implementation
   dispatch.** Per this repo's CLAUDE.md ("Between design and implementation,
   the leader MUST review the design for substantive issues... and escalate
   ... BEFORE dispatching the implementation mission"), this is exactly such
   an issue: the mission contract names `_phase2_version_bump` explicitly,
   and this design recommends `_phase4_release_pr` instead, with a concrete
   correctness argument (git object reachability after `--squash
   --delete-branch`). Implementation of fwql should not be dispatched until
   the leader/operator picks Option A or Option B.

## 4. Test count delta

| Fix | New tests |
|---|---|
| f85t.1 | 5 |
| f85t.2 | 4 (+ 1 fixture change touching all existing `_phase6_ci_wait` tests, not counted as new) |
| f85t.4 | 6 |
| f85t.3 | 5 |
| fwql | 4 |
| **Total** | **24** (± 3 depending on whether the f85t.1 fresh-release addendum and the f85t.4 optional warn-once test are included) |

## 5. Leader verification (2026-08-30, pre-dispatch)

Manual verification against live artifacts before A2 dispatch, so the implementation mission does not discover the design's assumptions are wrong.

**§2.4 marketplace-pin chain — verified.** `/home/jfreeman/Coding/punt-labs/.github/install-all.sh:45` contains `curl -fsSL "$GH/claude-plugins/aa5a34d/install.sh" | sh` — the claude-plugins pin the design's `_verify_marketplace_pin_chain` helper reads. `git show aa5a34d:.claude-plugin/marketplace.json` in `/home/jfreeman/Coding/punt-labs/claude-plugins` resolves cleanly and returns JSON with `plugins[*].version` and `plugins[*].source.ref` fields — exactly the shape the helper parses. The proposed regex (`r"\$GH/claude-plugins/([0-9a-fA-F]{7,40})/install\.sh"`) matches the actual line.

**§2.5 fwql reachability argument — verified.** `src/punt_kit/release.py:995-996` calls `gh pr merge --squash --delete-branch` in phase 4. Squash-merge creates one commit on `main`; the release branch's commits become unreachable from any ref once the branch is deleted. Option A's proposed pin site (`_phase2_version_bump`) writes on the release branch that phase 4 deletes. Option B's proposed pin site (`_phase4_release_pr` after `_pr_merge`) writes against the squashed SHA on main. Design's reachability analysis holds.

**§2.2 workflow_files field — verified.** `src/punt_kit/detect.py:160-163` populates `info.workflow_files` from `.github/workflows/*.yml` and `*.yaml` filenames. The guard `"release.yml" not in info.workflow_files` is the correct discriminator.

**Not verified (operator ruling pending)**: fwql Option A vs B recommendation, f85t.1 fresh-path scope, ~2-3 min critical-path cost of Option B. These are policy decisions, not correctness questions.
