"""Fault-injection test harness for the release engine.

See ``docs/design-release-failure-harness.md`` for the design this
implements. It ships the primitives — ``FaultRule`` and
``FaultInjectingOps``.
"""

from __future__ import annotations

from .fault_ops import CompletedProcessSpec, FaultInjectingOps, FaultRule

__all__ = ["CompletedProcessSpec", "FaultInjectingOps", "FaultRule"]
