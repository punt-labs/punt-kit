"""Fault-injection test harness for the release engine.

See ``docs/design-release-failure-harness.md`` §2 for the design this
implements. Wave 0 ships the primitives only — ``FaultRule`` and
``FaultInjectingOps`` — with zero migration of existing
``tests/test_release.py`` scenarios.
"""

from __future__ import annotations

from .fault_ops import CompletedProcessSpec, FaultInjectingOps, FaultRule

__all__ = ["CompletedProcessSpec", "FaultInjectingOps", "FaultRule"]
