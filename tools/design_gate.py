"""Gate the pinned design scanner's advisory JSON verdict."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import cast


def main() -> int:
    """Print the complete report and fail on regressions or invalid output."""
    result = subprocess.run(
        ["oo-ratchet", "design", sys.argv[1], "--shadow-check", sys.argv[2], "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode:
        return result.returncode
    try:
        report = json.loads(result.stdout)
    except ValueError:
        sys.stderr.write("FAIL: invalid design JSON report\n")
        return 2
    verdict = (
        cast("dict[str, object]", report).get("verdict")
        if isinstance(report, dict)
        else None
    )
    if verdict in ("neutral", "good-deed", "good-deed: trade"):
        return 0
    if verdict in ("would-fail: tier0", "would-fail: tier1", "would-fail: tier2"):
        return 1
    sys.stderr.write("FAIL: missing or unknown design verdict\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
