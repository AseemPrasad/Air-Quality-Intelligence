"""A bad --config-dir must end the command with a message and exit code 1.

``_load_config`` reported errors with ``console.print(..., file=sys.stderr)``, but
rich's ``Console.print`` has no ``file`` parameter, so the error handler itself
raised ``TypeError`` and the user got a traceback instead of the message.
"""

from unittest.mock import patch

import pytest
import typer

from aq_engine import cli


def test_missing_config_exits_with_code_1(capsys):
    with patch.object(cli, "load_config", side_effect=FileNotFoundError("configs/app.yaml")):
        with pytest.raises(typer.Exit) as exc_info:
            cli._load_config("./nonexistent")

    assert exc_info.value.exit_code == 1
    assert "configs/app.yaml" in capsys.readouterr().err


def test_invalid_config_exits_with_code_1(capsys):
    with patch.object(cli, "load_config", side_effect=ValueError("port must be an integer")):
        with pytest.raises(typer.Exit) as exc_info:
            cli._load_config("./configs")

    assert exc_info.value.exit_code == 1
    assert "Configuration error: port must be an integer" in capsys.readouterr().err
