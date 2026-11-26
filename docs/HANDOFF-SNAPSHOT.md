# Ethos handoff snapshot

The punt-kit handoff still runs the full `make check` gate. The profile in
`.punt-labs/ethos/checks/snapshots/punt-kit.yaml` lets a compatible Ethos runner
execute it against a read-only copy of the worktree. The runtime supports Linux
x86-64 only; on other platforms run the explicit gate. Nothing runs against the
live checkout as a fallback for a deferred snapshot.

On Linux x86-64, install Git, Make, Bash, ShellCheck, gettext, Python 3,
curl, and GNU coreutils, then install the pinned runtime:

```sh
scripts/install-handoff-runtime.sh --apply
```

The installer verifies the digest before placing the archive in
`~/.punt-labs/ethos/runtimes/`. Ethos does not download it. To install the same
bytes before publication, pass a local archive path to the installer. The
download is not available until the release is published. Run the installer
without arguments to preview without writing anything.

The bundle contains uv, Python, Node with npm, and the offline dependency caches.
The profile uses private copies of those caches and a fresh venv. The design
gate creates a detached base worktree under the runner's private `TMPDIR` and
needs the runner's writable private `.git/worktrees` mount. The source tree,
Git refs, and objects remain read-only. Keep `origin/main` available locally.

## Creating a runtime release

Use Linux x86-64, uv 0.13.9 and the Node v24.22.3 distribution with npm:

```sh
mkdir -p .punt-labs/local/ethos/handoff-assets
scripts/build-handoff-runtime.sh .punt-labs/local/ethos/handoff-assets
```

The builder prints the archive path, named by its SHA-256. Tar headers and gzip
metadata are normalized; a new package-manager fetch can still change the cache
bytes. Preserve and pin the exact archive that was tested, not a rebuild.

The Handoff runtime workflow builds and smoke-tests a candidate on pull
requests. Refresh the runtime pin when `uv.lock`, the project build requirements,
or the toolchain changes. Use an artifact from a successful build on a reviewed
branch in this repository, test that exact archive with the full gate, and
update the sidecar with its SHA-256 and new release URL. After the pin reaches
`main`, dispatch the workflow with the candidate's build run ID. Publication
checks the build run and verifies the artifact against the pin on `main`.

If publication stops after creating a draft, inspect the draft and its asset
digests before publishing it manually. Do not overwrite an existing release.
