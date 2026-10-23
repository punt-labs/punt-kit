"""Phase 10d: propagate the release version and install pin to the public website."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.entry_matcher import EntryMatcher
from punt_kit.phases.shared.install_urls import InstallUrlRecognizer
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.pin_currency import PinCurrency
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.project_remote import ProjectRemote
from punt_kit.phases.shared.siblings import SiblingRepo

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder


@final
class WebsitePropagator:
    """10d. Updates version in public-website projects.json."""

    __slots__ = ("_info", "_ops", "_skips")

    _info: ProjectInfo
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls, info: ProjectInfo, *, ops: ReleaseOps, skips: SkipRecorder
    ) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._ops = ops
        self._skips = skips
        return self

    def run(
        self,
        version: str,
        *,
        dry_run: bool,
        merge_sibling: Callable[..., bool],
    ) -> None:
        info = self._info
        ops = self._ops
        # The website is optional: look for its sibling before asking for the
        # slug, so a missing sibling is not reported as a skipped step needing
        # manual action.
        website_sibling = SiblingRepo.resolve(info.root, "public-website", ops=ops)
        if website_sibling is None:
            ops.info("Sibling public-website not found — skipping website update")
            return

        sibling = website_sibling.path
        projects_json = sibling / "src" / "data" / "projects.json"
        if not projects_json.exists():
            ops.info("projects.json not found in public-website — skipping")
            return

        slug = ProjectRemote(
            info.root, ops=ops, skips=self._skips, step="website propagation"
        ).slug()
        if slug is None:
            return
        project_name = slug.name

        if dry_run:
            ops.dry(
                f"../public-website/projects.json: {project_name} version={version}"
            )
            return

        website_sibling.validate()

        projects_file = JsonFile(projects_json)
        data = cast("list[dict[str, object]]", projects_file.load())
        matcher = EntryMatcher.for_website(slug)

        found = False
        for project in data:
            if matcher.claims_website(project):
                project["version"] = version
                # The same recognizer Phase 11 verifies the installCommand with.
                install_cmd = str(project.get("installCommand") or "")
                if install_cmd:
                    install_sha = ReleaseProject(info, ops=ops).install_sh_sha()
                    currency = PinCurrency(install_sha, cwd=info.root, ops=ops)
                    project["installCommand"] = InstallUrlRecognizer(
                        slug.owner, project_name
                    ).repinned(install_cmd, install_sha, is_current=currency.is_current)
                found = True
                break

        if not found:
            self._skips.record(
                "SKIPPED — manual action required: public-website projects.json has "
                f"no entry for {project_name}, so its version was not propagated "
                f"for v{version}. Add the entry manually."
            )
            return

        projects_file.save(data)

        branch = f"propagate/v{version}-{project_name}-public-website"
        if merge_sibling(
            sibling,
            branch,
            ["src/data/projects.json"],
            f"chore: bump {project_name} to v{version}",
            "public-website",
            dry_run=dry_run,
        ):
            ops.ok(f"website: {project_name} version={version}")
        else:
            ops.ok(f"website: {project_name} already current")
