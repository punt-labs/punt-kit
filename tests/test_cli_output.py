"""Tests for rendering finite command results."""

import json

import pytest
import typer

from punt_kit.cli_output import Output
from punt_kit.errors import CommandFailure


def test_quiet_json_preserves_structured_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = Output(json=True, quiet=True)
    with pytest.raises(typer.Exit) as caught, output.engine_output():
        typer.echo("routine progress")
        raise CommandFailure("cannot finish", {"changes": ["first"]})

    result = capsys.readouterr()
    assert caught.value.exit_code == 1
    assert json.loads(result.out) == {"error": "cannot finish", "changes": ["first"]}
    assert not result.err
