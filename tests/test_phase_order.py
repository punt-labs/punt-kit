"""Tests for the phase order that --resume-from and the recap share."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.phase_order import PhaseOrder


def test_every_phase_number_round_trips_through_its_name() -> None:
    for number in range(1, len(PhaseOrder.ORDER) + 1):
        assert PhaseOrder.NUMBERS[PhaseOrder.name_of(number)] == number


@pytest.mark.parametrize("number", [0, -1, 12])
def test_a_number_outside_the_pipeline_has_no_name(number: int) -> None:
    assert PhaseOrder.name_of(number) == "unknown"


def test_release_is_an_alias_for_release_pr() -> None:
    assert PhaseOrder.NUMBERS["release"] == PhaseOrder.NUMBERS["release-pr"]


def test_unlanded_is_the_running_phase_and_everything_after_it() -> None:
    assert PhaseOrder.unlanded_from(10) == ("propagate", "verify")
    assert PhaseOrder.unlanded_from(0) == PhaseOrder.ORDER
