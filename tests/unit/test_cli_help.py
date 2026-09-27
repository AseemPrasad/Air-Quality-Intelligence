"""``aq --help`` must render with the dependency versions pyproject allows."""

from typer.testing import CliRunner

from aq_engine.cli import cli_app


def test_top_level_help_renders():
    result = CliRunner().invoke(cli_app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


def test_subcommand_help_renders():
    result = CliRunner().invoke(cli_app, ["ingest", "--help"])

    assert result.exit_code == 0, result.output
