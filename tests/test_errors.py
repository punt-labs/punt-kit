"""Tests for structured command failures."""

from punt_kit.errors import CommandFailure


def test_command_failure_keeps_engine_exit_and_owns_details() -> None:
    failure = CommandFailure("failed")
    failure.details["changes"] = ["first"]

    assert failure.code == 1
    assert failure.message == "failed"
    assert CommandFailure("other failure").details == {}
