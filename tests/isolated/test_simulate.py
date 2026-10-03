import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from psynet.audit.cli import init_audit
from psynet.command_line import psynet
from psynet.pytest_psynet import path_to_demo_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory", "audit_directory")
def test_simulate():
    runner = CliRunner()
    result = runner.invoke(
        psynet,
        ["audit", "simulate"],
        catch_exceptions=False,
    )
    print(result.output)
    assert result.exit_code == 0

    export = Path("audit/simulate/analysis/simulated_export")
    assert export.is_dir()
    assert (export / "database" / "participant.csv").is_file()
    assert (export / "participant_identifiers.csv").is_file()
    assert (export / "manifest.json").is_file()
    assert not (export / "source_code.zip").exists()
    assert not Path("data/simulated_data").exists()
    assert not Path("exports").exists()


@pytest.fixture
def audit_directory():
    path = Path("audit")
    init_audit(path)
    yield path
    shutil.rmtree(path)
