import hashlib
import io
import json
import stat
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import click
import pandas as pd
import pytest
from click.testing import CliRunner

from psynet.command_line import (
    _check_constraints,
    _create_sql_profile_run_dir,
    _enable_sql_profile,
    check_dockerfile,
    psynet,
)
from psynet.experiment_scaffold import (
    _remove_empty_parent_dirs,
    missing_scaffold_paths_required_for_local_run,
    prune_experiment_scaffold,
    scaffold_experiment_directory,
)
from psynet.pytest_psynet import path_to_test_experiment
from psynet.utils import working_directory


@pytest.fixture(autouse=True)
def stub_scaffold_constraints_generation(monkeypatch):
    """Avoid dependency resolution while exercising scaffold orchestration."""

    @click.command()
    def generate_constraints():
        Path("constraints.txt").write_text("# generated constraints\n")

    def _fake_generate_constraints_file():
        Path("constraints.txt").write_text("# generated constraints\n")

    monkeypatch.setattr(
        "dallinger.command_line.generate_constraints", generate_constraints
    )
    monkeypatch.setattr(
        "psynet.constraints_compile.generate_constraints_file",
        _fake_generate_constraints_file,
    )
    monkeypatch.setattr("psynet.command_line.reset_console", lambda: None)


class TestCommandLine(object):
    @pytest.fixture
    def export(self):
        from psynet.command_line import export

        return export

    def test_psynet_no_args(self):
        result = subprocess.run(["psynet"], capture_output=True, text=True)
        assert "Usage: psynet [OPTIONS] COMMAND [ARGS]" in result.stderr

    def test_psynet_help(self):
        output = subprocess.check_output(["psynet", "--help"])
        assert b"Options:" in output
        assert b"Commands:" in output

    def test_psynet_docs_command_is_not_registered(self):
        from psynet.command_line import psynet

        result = CliRunner().invoke(psynet, ["docs", "--help"])

        assert result.exit_code != 0
        assert "No such command 'docs'" in result.output

    def test_dev_changelog_dispatches_to_builder(self, monkeypatch, tmp_path):
        from psynet.command_line import psynet
        from psynet.dev import changelog as changelog_module

        calls = []

        fragments_dir = tmp_path / "changelog.d"
        fragments_dir.mkdir()
        changelog_path = tmp_path / "CHANGELOG.md"
        changelog_path.write_text("# CHANGELOG\n", encoding="utf-8")

        monkeypatch.setattr(changelog_module, "FRAGMENTS_DIR", fragments_dir)
        monkeypatch.setattr(changelog_module, "CHANGELOG_PATH", changelog_path)
        monkeypatch.setattr(
            changelog_module,
            "new_command",
            lambda c, d: calls.append(("new", c, d)) or 0,
        )
        monkeypatch.setattr(
            changelog_module,
            "release_command",
            lambda v, d: calls.append(("release", v, d)) or 0,
        )
        monkeypatch.setattr(
            changelog_module,
            "build_command",
            lambda: calls.append(("build",)) or 0,
        )
        monkeypatch.setattr(
            changelog_module,
            "check_mr_command",
            lambda b, h: calls.append(("check-mr", b, h)) or 0,
        )

        runner = CliRunner()

        result = runner.invoke(
            psynet, ["dev", "changelog", "new", "fixed", "Fix thing"]
        )
        assert result.exit_code == 0, result.output
        assert calls == [("new", "fixed", "Fix thing")]

        result = runner.invoke(
            psynet,
            ["dev", "changelog", "release", "13.2.0", "2026-03-13"],
        )
        assert result.exit_code == 0, result.output
        assert calls[-1] == ("release", "13.2.0", "2026-03-13")

        result = runner.invoke(psynet, ["dev", "changelog", "preview"])
        assert result.exit_code == 0, result.output
        assert calls[-1] == ("build",)

        result = runner.invoke(psynet, ["dev", "changelog", "check-mr", "base", "head"])
        assert result.exit_code == 0, result.output
        assert calls[-1] == ("check-mr", "base", "head")

    def test_dev_changelog_check_mr_is_hidden_from_help(self):
        result = subprocess.run(
            ["psynet", "dev", "changelog", "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "check-mr" not in result.stdout

    def test_dev_changelog_requires_source_checkout(self, tmp_path):
        from psynet.command_line import psynet

        runner = CliRunner()
        with working_directory(tmp_path):
            result = runner.invoke(psynet, ["dev", "changelog", "preview"])

        assert result.exit_code != 0
        assert "Run from a PsyNet source checkout" in result.output

    def test_dev_ci_update_dallinger_constraints_dispatches_to_script(
        self, monkeypatch
    ):
        from psynet.command_line import psynet
        from psynet.dev import ci as ci_module

        calls = []
        monkeypatch.setattr(
            ci_module,
            "update_dallinger_constraints_command",
            lambda check_compile: calls.append(check_compile) or 0,
        )

        result = CliRunner().invoke(
            psynet,
            ["dev", "ci", "update-dallinger-constraints", "--skip-compile-check"],
        )

        assert result.exit_code == 0, result.output
        assert calls == [False]

    def test_dev_update_experiments_dispatches_to_script(self, monkeypatch):
        from psynet.command_line import psynet
        from psynet.dev import experiments as experiments_module

        calls = []
        monkeypatch.setattr(
            experiments_module,
            "update_command",
            lambda: calls.append(True) or 0,
        )

        result = CliRunner().invoke(
            psynet,
            ["dev", "experiments", "update"],
        )

        assert result.exit_code == 0
        assert calls == [True]

    def test_dev_update_experiments_help(self):
        from psynet.command_line import psynet

        result = CliRunner().invoke(psynet, ["dev", "experiments", "update", "--help"])

        assert result.exit_code == 0, result.output
        assert "Update canonical experiment templates." in result.output

    def test_dev_update_experiments_requires_source_checkout(self, tmp_path):
        from psynet.command_line import psynet

        runner = CliRunner()
        with working_directory(tmp_path):
            result = runner.invoke(psynet, ["dev", "experiments", "update"])

        assert result.exit_code != 0
        assert (
            "This command must be run from the PsyNet source checkout root directory"
            in result.output
        )

    def test_dev_docs_make_dispatches_to_builder(self, monkeypatch):
        from psynet.command_line import psynet
        from psynet.dev import docs as docs_module

        calls = []
        monkeypatch.setattr(
            docs_module,
            "make_command",
            lambda **kwargs: calls.append(kwargs) or 0,
        )

        result = CliRunner().invoke(
            psynet,
            [
                "dev",
                "docs",
                "make",
                "dirhtml",
                "--clean",
                "--live-preview",
                "--port",
                "8001",
                "--strict",
                "--jobs",
                "auto",
                "--sphinx-option=--nitpicky",
            ],
        )

        assert result.exit_code == 0, result.output
        assert calls == [
            {
                "target": "dirhtml",
                "clean": True,
                "open_browser": True,
                "live_preview": True,
                "live_preview_port": 8001,
                "strict": True,
                "jobs": "auto",
                "sphinx_options": ("--nitpicky",),
            }
        ]

    def test_dev_docs_make_reports_subprocess_failure(self, monkeypatch):
        from psynet.command_line import psynet
        from psynet.dev import docs as docs_module

        def fail(**kwargs):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["sphinx-autobuild"],
            )

        monkeypatch.setattr(docs_module, "make_command", fail)

        result = CliRunner().invoke(psynet, ["dev", "docs", "make", "--live-preview"])

        assert result.exit_code == 1
        assert "Docs command failed with exit code 1." in result.output
        assert "Traceback" not in result.output

    def test_dev_docs_make_help(self):
        from psynet.command_line import psynet

        result = CliRunner().invoke(psynet, ["dev", "docs", "make", "--help"])

        assert result.exit_code == 0, result.output
        assert "--clean" in result.output
        assert "--open" in result.output
        assert "--live-preview" in result.output
        assert "--port" in result.output
        assert "sphinx-autobuild" in result.output
        assert "--strict" in result.output
        assert "--jobs" in result.output
        assert "deterministic output" in result.output
        assert "--sphinx-option" in result.output
        assert "Uses --jobs 1 by default" in result.output

    def test_dev_docs_linkcheck_dispatches_to_builder(self, monkeypatch):
        from psynet.command_line import psynet
        from psynet.dev import docs as docs_module

        calls = []
        monkeypatch.setattr(
            docs_module,
            "linkcheck_command",
            lambda **kwargs: calls.append(kwargs) or 0,
        )

        result = CliRunner().invoke(
            psynet,
            [
                "dev",
                "docs",
                "linkcheck",
                "--clean",
                "--jobs",
                "auto",
                "--sphinx-option=-q",
            ],
        )

        assert result.exit_code == 0, result.output
        assert calls == [
            {
                "clean": True,
                "jobs": "auto",
                "sphinx_options": ("-q",),
            }
        ]

    def test_dev_docs_linkcheck_cleans_by_default(self, monkeypatch):
        from psynet.command_line import psynet
        from psynet.dev import docs as docs_module

        calls = []
        monkeypatch.setattr(
            docs_module,
            "linkcheck_command",
            lambda **kwargs: calls.append(kwargs) or 0,
        )

        result = CliRunner().invoke(psynet, ["dev", "docs", "linkcheck"])

        assert result.exit_code == 0, result.output
        assert calls == [
            {
                "clean": True,
                "jobs": "1",
                "sphinx_options": (),
            }
        ]

    def test_dev_docs_linkcheck_can_skip_clean(self, monkeypatch):
        from psynet.command_line import psynet
        from psynet.dev import docs as docs_module

        calls = []
        monkeypatch.setattr(
            docs_module,
            "linkcheck_command",
            lambda **kwargs: calls.append(kwargs) or 0,
        )

        result = CliRunner().invoke(psynet, ["dev", "docs", "linkcheck", "--no-clean"])

        assert result.exit_code == 0, result.output
        assert calls == [
            {
                "clean": False,
                "jobs": "1",
                "sphinx_options": (),
            }
        ]

    def test_dev_docs_linkcheck_help(self):
        from psynet.command_line import psynet

        result = CliRunner().invoke(psynet, ["dev", "docs", "linkcheck", "--help"])

        assert result.exit_code == 0, result.output
        assert "Wrap Sphinx's linkcheck builder" in result.output
        assert "make linkcheck" in result.output
        assert "--clean / --no-clean" in result.output
        assert "--jobs" in result.output
        assert "--sphinx-option" in result.output

    def test_install_autocomplete_help(self):
        """Test that the install autocomplete command shows help."""
        output = subprocess.check_output(
            ["psynet", "install", "autocomplete", "--help"]
        )
        assert b"Install shell tab completion" in output

    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("os.chmod")
    def test_install_autocomplete_success(self, mock_chmod, mock_exists, mock_run):
        """Test successful installation of autocomplete."""
        from psynet.command_line import install_autocomplete

        mock_exists.return_value = True
        mock_run.return_value.returncode = 0

        runner = CliRunner()
        result = runner.invoke(install_autocomplete)

        assert result.exit_code == 0
        # Check that the script was made executable and run
        mock_chmod.assert_called_once()
        mock_run.assert_called_once()

        # Verify the last call to exists was for the install script
        last_exists_call = mock_exists.call_args_list[-1]
        assert "install-completion.sh" in str(last_exists_call)

    @patch("os.path.exists")
    def test_install_autocomplete_script_not_found(self, mock_exists):
        """Test that install autocomplete fails when script is not found."""
        from psynet.command_line import install_autocomplete

        mock_exists.return_value = False

        runner = CliRunner()
        result = runner.invoke(install_autocomplete)

        assert result.exit_code != 0
        assert "Installation script not found" in result.output


# Disabled because our method of importing means that we can't patch
# the necessary Dallinger commands. I think this is fine, I don't
# think these tests add much value.
#
# @pytest.mark.parametrize("experiment_directory", [path_to_test_experiment("timeline")], indirect=True)
# @pytest.mark.usefixtures("in_experiment_directory")
# class TestDebug:
#     # Note:
#     # We do not test non-legacy debug here because of an issue whereby you
#     # can't use hot-refresh mode when running PsyNet demos unless the
#     # PsyNet installation folder is renamed to something other than 'psynet'.
#     # It's not a big deal but maybe we fix this sometime.
#     @patch("psynet.command_line.prepare")
#     @patch("dallinger.command_line.debug")
#     def test_debug(self, dallinger_debug, prepare):
#         from psynet.command_line import debug
#
#         CliRunner().invoke(debug, ["--legacy"], catch_exceptions=False)
#
#         # We can no longer run this test for prepare, because it is now called in a subprocess,
#         # so isn't caught by the mock.
#         # prepare.assert_called_once_with(force=False)
#
#         dallinger_debug.assert_called_once_with(
#             verbose=False,
#             bot=False,
#             proxy=None,
#             no_browsers=False,
#             exp_config={"threads": "1"},
#             archive=None,
#         )
#
#     @patch("psynet.command_line.prepare")
#     @patch("dallinger.command_line.debug")
#     def test_debug_all_non_default(self, dallinger_debug, prepare):
#         from psynet.command_line import debug
#
#         CliRunner().invoke(
#             debug,
#             [
#                 "--legacy",
#                 "--verbose",
#                 "--bot",
#                 "--proxy=5001",
#                 "--no-browsers",
#                 "--force-prepare",
#             ],
#             catch_exceptions=False,
#         )
#
#         # We can no longer run this test for prepare, because it is now called in a subprocess,
#         # so isn't caught by the mock.
#         # prepare.assert_called_once_with(force=True)
#
#         dallinger_debug.assert_called_once_with(
#             verbose=True,
#             bot=True,
#             proxy="5001",
#             no_browsers=True,
#             exp_config={"threads": "1"},
#         )
#
#
# @pytest.mark.parametrize("experiment_directory", [path_to_test_experiment("timeline")], indirect=True)
# @pytest.mark.usefixtures("in_experiment_directory")
# class TestDeploy:
#     @pytest.fixture
#     def deploy(self):
#         from psynet.command_line import deploy
#
#         return deploy
#
#     @pytest.fixture
#     def prepare(self):
#         with patch("psynet.command_line.prepare") as mock_prepare:
#             yield mock_prepare
#
#     @pytest.fixture
#     def dallinger_deploy(self):
#         with patch("dallinger.command_line.deploy") as mock_dallinger_deploy:
#             yield mock_dallinger_deploy
#
#     def test_deploy(self, deploy, prepare, dallinger_deploy):
#         CliRunner().invoke(deploy, [], catch_exceptions=False)
#
#         # We can no longer run this test for prepare, because it is now called in a subprocess,
#         # so isn't caught by the mock.
#         # prepare.assert_called_once_with(force=False)
#
#         dallinger_deploy.assert_called_once_with(verbose=False, app=None, archive=None)
#
#     def test_deploy_all_non_default(self, deploy, prepare, dallinger_deploy):
#         CliRunner().invoke(
#             deploy,
#             [
#                 "--verbose",
#                 "--app=some_app_name",
#                 "--archive=/path/to/some_archive",
#                 "--force-prepare",
#             ],
#             catch_exceptions=False,
#         )
#
#         # We can no longer run this test for prepare, because it is now called in a subprocess,
#         # so isn't caught by the mock.
#         # prepare.assert_called_once_with(force=True)
#
#         dallinger_deploy.assert_called_once_with(
#             verbose=True, app="some_app_name", archive="/path/to/some_archive"
#         )
#
#
# @pytest.mark.parametrize("experiment_directory", [path_to_test_experiment("timeline")], indirect=True)
# @pytest.mark.usefixtures("in_experiment_directory")
# class TestSandbox:
#     @pytest.fixture
#     def sandbox(self):
#         from psynet.command_line import sandbox
#
#         return sandbox
#
#     @pytest.fixture
#     def prepare(self):
#         with patch("psynet.command_line.prepare") as mock_prepare:
#             yield mock_prepare
#
#     @pytest.fixture
#     def dallinger_sandbox(self):
#         with patch("dallinger.command_line.sandbox") as mock_dallinger_sandbox:
#             yield mock_dallinger_sandbox
#
#     def test_sandbox(self, sandbox, prepare, dallinger_sandbox):
#         CliRunner().invoke(sandbox, [], catch_exceptions=False)
#
#         # We can no longer run this test for prepare, because it is now called in a subprocess,
#         # so isn't caught by the mock.
#         # prepare.assert_called_once_with(force=False)
#
#         dallinger_sandbox.assert_called_once_with(verbose=False, app=None, archive=None)
#
#     def test_sandbox_all_non_default(self, sandbox, prepare, dallinger_sandbox):
#         CliRunner().invoke(
#             sandbox,
#             [
#                 "--verbose",
#                 "--app=some_app_name",
#                 "--archive=/path/to/some_archive",
#                 "--force-prepare",
#             ],
#             catch_exceptions=False,
#         )
#
#         # We can no longer run this test for prepare, because it is now called in a subprocess,
#         # so isn't caught by the mock.
#         # prepare.assert_called_once_with(force=True)
#
#         dallinger_sandbox.assert_called_once_with(
#             verbose=True, app="some_app_name", archive="/path/to/some_archive"
#         )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestEstimate:
    @pytest.fixture
    def estimate(self):
        from psynet.command_line import estimate

        return estimate

    @pytest.fixture
    def prepare(self):
        with patch("psynet.command_line.prepare") as mock_prepare:
            yield mock_prepare

    @pytest.fixture
    def import_local_experiment(self):
        with patch(
            "psynet.experiment.import_local_experiment"
        ) as mock_import_local_experiment:
            yield mock_import_local_experiment

    @pytest.fixture
    def pretty_format_seconds(self):
        with patch(
            "psynet.command_line.pretty_format_seconds"
        ) as mock_pretty_format_seconds:
            yield mock_pretty_format_seconds

    def test_estimate(
        self, estimate, prepare, import_local_experiment, pretty_format_seconds
    ):
        CliRunner().invoke(estimate, [], catch_exceptions=False)
        prepare.assert_not_called()
        import_local_experiment.assert_called_once()
        pretty_format_seconds.assert_called_once()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestExport:
    @pytest.fixture
    def export(self):
        from psynet.command_line import export

        return export

    @pytest.fixture
    def prepare(self):
        with patch("psynet.command_line.prepare") as mock_prepare:
            yield mock_prepare

    @pytest.fixture
    def dallinger_data_export(self):
        with patch(
            "psynet.command_line.dallinger_data.export"
        ) as mock_dallinger_data_export:
            yield mock_dallinger_data_export

    @pytest.fixture
    def import_local_experiment(self):
        with patch(
            "psynet.experiment.import_local_experiment"
        ) as mock_import_local_experiment:
            yield mock_import_local_experiment

    @pytest.fixture
    def create_export_dirs(self):
        with patch("psynet.command_line.create_export_dirs") as mock_create_export_dirs:
            yield mock_create_export_dirs

    @pytest.fixture
    def move_snapshot_file(self):
        with patch("psynet.command_line.move_snapshot_file") as mock_move_snapshot_file:
            yield mock_move_snapshot_file

    @pytest.fixture
    def export_data(self):
        with patch("psynet.command_line.export_data") as mock_export_data:
            yield mock_export_data

    def test_export_logs_success(self, tmp_path):
        """Test successful log file export."""
        from unittest.mock import Mock, patch

        from psynet.command_line import export_logs

        mock_executor = Mock()
        mock_sftp = Mock()
        mock_server_info = {"host": "test-host", "user": "test-user"}
        mock_spinner = Mock()

        with (
            patch(
                "dallinger.command_line.docker_ssh.CONFIGURED_HOSTS",
                {"test-server": mock_server_info},
            ),
            patch("dallinger.command_line.docker_ssh.get_sftp", return_value=mock_sftp),
            patch(
                "dallinger.command_line.docker_ssh.Executor", return_value=mock_executor
            ),
            patch("psynet.command_line.log") as mock_log,
            patch("psynet.command_line.yaspin") as mock_yaspin,
        ):
            mock_yaspin.return_value.__enter__.return_value = mock_spinner
            mock_executor.run.return_value.strip.return_value = "/home/testuser"

            # Test log file export
            export_logs("test-app", "test-server", str(tmp_path))

            # Verify the call was made
            assert mock_sftp.get.call_count == 1

            # Verify correct path
            mock_sftp.get.assert_called_with(
                "/home/testuser/dallinger/test-app/logs.jsonl",
                str(tmp_path / "logs.jsonl"),
            )

            # Verify log message
            mock_log.assert_called_with(f"Exporting logs to {tmp_path}/logs.jsonl")

            # Verify success spinner was shown (function ran to completion)
            assert mock_yaspin.call_count == 1
            mock_yaspin.assert_called_with(text="Logs exported.", color="green")
            assert mock_spinner.ok.call_count == 1

    def test_export_logs_error_handling(self, tmp_path):
        """Test error handling in log file export."""
        from unittest.mock import Mock, patch

        from psynet.command_line import export_logs

        mock_executor = Mock()
        mock_sftp = Mock()
        mock_server_info = {"host": "test-host", "user": "test-user"}

        # Test SFTP failure
        mock_sftp.get.side_effect = Exception("Permission denied")

        with (
            patch(
                "dallinger.command_line.docker_ssh.CONFIGURED_HOSTS",
                {"test-server": mock_server_info},
            ),
            patch("dallinger.command_line.docker_ssh.get_sftp", return_value=mock_sftp),
            patch(
                "dallinger.command_line.docker_ssh.Executor", return_value=mock_executor
            ),
            patch("psynet.command_line.log") as mock_log,
        ):
            mock_executor.run.return_value.strip.return_value = "/home/testuser"

            export_logs("test-app", "test-server", str(tmp_path))

            # Verify the error message includes the specific path
            mock_log.assert_called_with(
                "Warning: Failed to export logs from /home/testuser/dallinger/test-app/logs.jsonl: Permission denied"
            )


def _setup_basic_data_export(monkeypatch, basic_data):
    class DummyExperiment:
        def get_basic_data(self, context=None, **kwargs):
            assert context == "export"
            return basic_data

    def fake_get_experiment():
        return DummyExperiment()

    @contextmanager
    def dummy_spinner(*args, **kwargs):
        class Spinner:
            def ok(self, *_args, **_kwargs):
                return None

        yield Spinner()

    monkeypatch.setattr("psynet.experiment.get_experiment", fake_get_experiment)
    monkeypatch.setattr(
        "psynet.command_line.dump_db_to_disk", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("psynet.command_line.yaspin", dummy_spinner)


@pytest.fixture
def run_basic_data_export(tmp_path):
    from psynet.command_line import export_data

    def _run(anonymize):
        export_path = tmp_path / "export"
        export_path.mkdir()
        export_data(
            local=True,
            anonymize=anonymize,
            database_zip_path=str(tmp_path / "database.zip"),
            export_path=str(export_path),
        )
        return export_path

    return _run


def test_export_data_writes_basic_data_json(monkeypatch, run_basic_data_export):
    basic_data = {"participant": [{"id": 1}]}
    _setup_basic_data_export(monkeypatch, basic_data)
    export_path = run_basic_data_export(anonymize=True)

    basic_data_path = export_path / "anonymous" / "basic_data.json"
    assert basic_data_path.exists()
    with open(basic_data_path, "r") as file:
        assert json.load(file) == basic_data


def test_export_data_skips_basic_data_when_none(monkeypatch, run_basic_data_export):
    _setup_basic_data_export(monkeypatch, None)
    export_path = run_basic_data_export(anonymize=True)

    basic_data_json = export_path / "anonymous" / "basic_data.json"
    basic_data_zip = export_path / "anonymous" / "basic_data.zip"
    assert not basic_data_json.exists()
    assert not basic_data_zip.exists()


def test_export_data_writes_basic_data_folder_for_dataframes(
    monkeypatch, run_basic_data_export
):
    basic_data = {
        "participant": pd.DataFrame([{"id": 1}]),
        "trial": pd.DataFrame([{"id": 2, "answer": "ok"}]),
    }
    _setup_basic_data_export(monkeypatch, basic_data)
    export_path = run_basic_data_export(anonymize=False)

    basic_data_dir = export_path / "regular" / "basic_data"
    assert basic_data_dir.exists()
    assert sorted(path.name for path in basic_data_dir.iterdir()) == [
        "participant.csv",
        "trial.csv",
    ]


def test_export_data_sanitizes_basic_data_dataframe_keys(
    monkeypatch, run_basic_data_export
):
    basic_data = {
        "trial/results": pd.DataFrame([{"id": 1}]),
        "trial results": pd.DataFrame([{"id": 2}]),
    }
    _setup_basic_data_export(monkeypatch, basic_data)
    export_path = run_basic_data_export(anonymize=False)

    basic_data_dir = export_path / "regular" / "basic_data"
    assert basic_data_dir.exists()
    assert sorted(path.name for path in basic_data_dir.iterdir()) == [
        "trial_results.csv",
        "trial_results_2.csv",
    ]


def test_export_data_avoids_suffix_filename_collisions(
    monkeypatch, run_basic_data_export
):
    basic_data = {
        "trial": pd.DataFrame([{"id": 1}]),
        "trial_2": pd.DataFrame([{"id": 2}]),
        "trial/": pd.DataFrame([{"id": 3}]),
    }
    _setup_basic_data_export(monkeypatch, basic_data)
    export_path = run_basic_data_export(anonymize=False)

    basic_data_dir = export_path / "regular" / "basic_data"
    assert basic_data_dir.exists()
    assert sorted(path.name for path in basic_data_dir.iterdir()) == [
        "trial.csv",
        "trial_2.csv",
        "trial_3.csv",
    ]


def test_check_constraints():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with pytest.raises(
                click.ClickException,
                match="Experiment directory is missing a requirements.txt file.",
            ):
                _check_constraints()

            with open("requirements.txt", "w") as requirements:
                requirements.write("psynet")
                requirements.flush()

                with pytest.raises(
                    click.ClickException,
                    match="Experiment directory is missing a constraints.txt file.",
                ):
                    _check_constraints()

                with open("constraints.txt", "w") as constraints:
                    with pytest.raises(
                        click.ClickException,
                        match="The constraints.txt file is not up-to-date with the requirements.txt file.",
                    ):
                        _check_constraints()

                    requirements_hash = hashlib.md5(
                        Path("requirements.txt").read_bytes()
                    ).hexdigest()
                    constraints.write(requirements_hash)
                    constraints.flush()

                    _check_constraints()


def test_check_dockerfile():
    """Test that check_dockerfile detects missing and outdated Dockerfiles."""
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Test 1: No Dockerfile - should raise
            with pytest.raises(
                click.UsageError,
                match="Docker deployments require a Dockerfile",
            ):
                check_dockerfile()

            # Test 2: Dockerfile with new format - should not raise
            # Use scaffold overwrite to generate a proper Dockerfile
            with patch("click.echo"):  # Suppress output
                scaffold_experiment_directory(overwrite=True)
            check_dockerfile()

            # Test 3: Dockerfile with old format (version tag) - should raise
            with open("Dockerfile", "w") as f:
                f.write("FROM registry.gitlab.com/psynetdev/psynet:v13.0.3\n")
                f.write("RUN mkdir /experiment\n")

            with pytest.raises(
                click.UsageError,
                match="Your Dockerfile appears to be using an outdated format",
            ):
                check_dockerfile()

            # Test 4: Dockerfile with old format (master tag) - should raise
            with open("Dockerfile", "w") as f:
                f.write("FROM registry.gitlab.com/psynetdev/psynet:master\n")
                f.write("RUN mkdir /experiment\n")

            with pytest.raises(
                click.UsageError,
                match="Your Dockerfile appears to be using an outdated format",
            ):
                check_dockerfile()


def test_scripts_update_installs_managed_skills_and_preserves_user_skills():
    with tempfile.TemporaryDirectory() as directory:
        with working_directory(directory):
            Path("experiment.py").write_text("class Exp:\n    pass\n", encoding="utf-8")
            custom_skill = Path(".cursor/skills/custom/SKILL.md")
            custom_skill.parent.mkdir(parents=True)
            custom_skill.write_text("# Custom skill\n", encoding="utf-8")

            stale_skill = Path(".cursor/skills/psynet/stale/SKILL.md")
            stale_skill.parent.mkdir(parents=True)
            stale_skill.write_text("# Stale managed skill\n", encoding="utf-8")

            with patch("click.echo"):
                scaffold_experiment_directory(overwrite=True)

            assert custom_skill.read_text(encoding="utf-8") == "# Custom skill\n"
            assert not stale_skill.exists()
            assert Path(".cursor/skills/psynet/implement-experiment/SKILL.md").is_file()
            assert Path(
                ".cursor/skills/psynet/record-participant-video/SKILL.md"
            ).is_file()
            assert not Path(".cursor/skills/psynet/release").exists()


def test_scripts_scaffold_bootstraps_empty_directory():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code == 0, result.output
            assert "Scaffolded experiment in" in result.output
            assert "created: experiment.py, requirements.txt, and" in result.output
            assert "boilerplate files" in result.output
            assert "tip:" not in result.output
            assert "...creating" not in result.output
            assert Path("experiment.py").exists()
            assert "class Exp" in Path("experiment.py").read_text()
            assert Path("requirements.txt").exists()
            assert "psynet" in Path("requirements.txt").read_text()
            assert Path("Dockerfile").exists()
            assert Path("config.txt").exists()
            assert Path("constraints.txt").read_text() == "# generated constraints\n"
            gitignore = Path(".gitignore").read_text(encoding="utf-8")
            assert ".cursor/skills/psynet/" in gitignore
            dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
            assert ".cursor/skills/psynet/" in dockerignore


def test_scripts_scaffold_uses_running_python_version(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_python_major_minor",
        lambda: "3.14",
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".python-version").read_text() == "3.14\n"


def test_scripts_scaffold_escapes_directory_name_in_experiment_label(tmp_path):
    runner = CliRunner()
    experiment_directory = tmp_path / 'my "demo"'
    experiment_directory.mkdir()

    with working_directory(experiment_directory):
        result = runner.invoke(psynet, ["scripts", "scaffold"])
        source = Path("experiment.py").read_text()

    assert result.exit_code == 0, result.output
    compile(source, "experiment.py", "exec")
    assert "label = 'my \"demo\"'" in source


def test_scripts_scaffold_generates_resolvable_alpha_requirement(tmp_path, monkeypatch):
    from psynet.command_line import check_psynet_requirement_is_unambiguous

    commit = "a" * 40
    monkeypatch.setattr("psynet.experiment_scaffold.psynet_version", "13.4.0a0")
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold.commit_psynet_requirement",
        lambda _source: (
            f"psynet[experiment]@git+https://gitlab.com/alice/PsyNet@{commit}#egg=psynet"
        ),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

        assert result.exit_code == 0, result.output
        requirement_line = Path("requirements.txt").read_text().splitlines()[0]
        assert requirement_line == (
            f"psynet[experiment]@git+https://gitlab.com/alice/PsyNet@{commit}#egg=psynet"
        )
        assert "PsyNetDev/PsyNet" not in requirement_line
        check_psynet_requirement_is_unambiguous()


def test_scripts_scaffold_alpha_warns_and_degrades_on_unpushed_commit(
    tmp_path, monkeypatch
):
    """Scaffold still succeeds when the checkout commit cannot be served."""
    commit = "b" * 40
    monkeypatch.setattr("psynet.experiment_scaffold.psynet_version", "13.4.0a0")
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )

    def _fail(_source):
        raise ValueError(
            f"Commit {commit[:12]} is not available on git remote 'origin'. "
            "Push your PsyNet commits first (`git push origin HEAD`), then retry."
        )

    monkeypatch.setattr(
        "psynet.experiment_scaffold.commit_psynet_requirement",
        _fail,
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

        assert result.exit_code == 0, result.output
        assert "not available on git remote 'origin'" in result.output
        assert Path("experiment.py").exists()
        requirement_line = Path("requirements.txt").read_text().splitlines()[0]
        assert requirement_line.startswith("-e ")
        assert "PsyNetDev/PsyNet" not in requirement_line


def test_scripts_scaffold_rejects_conflicting_directory_name():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as parent:
        conflicting_dir = Path(parent) / "code"
        conflicting_dir.mkdir()
        with working_directory(conflicting_dir):
            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code != 0
            assert "Python's module 'code'" in result.output
            assert not Path("experiment.py").exists()
            assert not Path("Dockerfile").exists()


def test_scripts_scaffold_rejects_dotted_directory_name(tmp_path):
    experiment_directory = tmp_path / "experiment.v2"
    experiment_directory.mkdir()

    with working_directory(experiment_directory):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code != 0
    assert "cannot import this experiment reliably" in result.output
    assert not (experiment_directory / "experiment.py").exists()


def test_scripts_scaffold_preserves_existing_constraints(tmp_path):
    requirements = "psynet==0.0.0\n"
    digest = hashlib.md5(requirements.encode()).hexdigest()
    constraints = f"# existing constraints\n# requirements md5: {digest}\n"
    (tmp_path / "requirements.txt").write_text(requirements)
    (tmp_path / "constraints.txt").write_text(constraints)

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "constraints.txt").read_text() == constraints


def test_scripts_scaffold_pins_psynet_and_preserves_extra_requirements(
    tmp_path, monkeypatch
):
    (tmp_path / "requirements.txt").write_text("psynet\nmusic21==9.1.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    monkeypatch.setattr(
        "psynet.experiment_scaffold._default_psynet_requirement",
        lambda: "psynet==13.4.0",
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "requirements.txt").read_text() == (
        "psynet==13.4.0\nmusic21==9.1.0\n"
    )
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"


def test_scripts_scaffold_surfaces_existing_pin_failure_as_usage_error(
    tmp_path, monkeypatch
):
    (tmp_path / "requirements.txt").write_text("psynet\n")
    monkeypatch.setattr("psynet.experiment_setup.is_in_repo_experiment", lambda: False)

    def _fail():
        raise ValueError(
            "Commit deadbeefdead is not available on git remote 'origin'. "
            "Push your PsyNet commits first (`git push origin HEAD`), then retry."
        )

    monkeypatch.setattr(
        "psynet.experiment_scaffold._default_psynet_requirement",
        _fail,
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code != 0
    assert "not available on git remote 'origin'" in result.output
    assert (tmp_path / "requirements.txt").read_text() == "psynet\n"
    assert not (tmp_path / "Dockerfile").exists()
    assert not (tmp_path / "config.txt").exists()
    assert not (tmp_path / "docker").exists()


def test_scripts_scaffold_skips_constraints_and_psynet_pinning(tmp_path):
    requirements = "psynet\nmusic21==9.1.0\n"
    (tmp_path / "requirements.txt").write_text(requirements)

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["scripts", "scaffold", "--skip-constraints"],
        )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "requirements.txt").read_text() == requirements
    assert not (tmp_path / "constraints.txt").exists()


def test_scripts_scaffold_skips_pinning_for_in_repo_experiments(tmp_path, monkeypatch):
    requirements = "psynet\nmusic21==9.1.0\n"
    (tmp_path / "requirements.txt").write_text(requirements)
    monkeypatch.setattr("psynet.experiment_setup.is_in_repo_experiment", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_scaffold._default_psynet_requirement",
        lambda: "psynet==13.4.0",
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "requirements.txt").read_text() == requirements
    assert not (tmp_path / "constraints.txt").exists()


def test_scripts_scaffold_regenerates_empty_constraints(tmp_path):
    (tmp_path / "constraints.txt").touch()

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"


def _assume_git_repository(monkeypatch):
    """Treat setup tests as already inside a git work tree."""
    monkeypatch.setattr(
        "psynet.experiment_setup.git_repository_available",
        lambda: True,
    )


def _stub_new_venv_delegation(monkeypatch, tmp_path):
    """Stub uv and the delegated setup run for the dedicated-venv path.

    Returns ``(uv_calls, delegated)``, where ``delegated`` records the
    ``psynet setup`` invocations made through the new environment's entry point.
    """
    uv_calls = []
    delegated = []
    entry_point = tmp_path / ".venv" / "bin" / "psynet"

    def fake_run_uv(args, description, quiet=False):
        uv_calls.append((args, description, quiet))
        if args and args[0] == "venv":
            # uv would create the environment, including its entry points.
            entry_point.parent.mkdir(parents=True, exist_ok=True)
            entry_point.touch()

    def fake_subprocess_run(command, env=None, check=False, **kwargs):
        if len(command) > 1 and command[1] == "setup":
            delegated.append((command, env))
            return Mock(returncode=0)
        return Mock(returncode=0, stdout=str(tmp_path), stderr="")

    monkeypatch.setattr("psynet.experiment_setup._run_uv", fake_run_uv)
    monkeypatch.setattr("psynet.experiment_setup.subprocess.run", fake_subprocess_run)
    return uv_calls, delegated


def _mock_dedicated_experiment_venv(monkeypatch):
    """Treat setup tests as using a dedicated experiment venv, not the shared one."""
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_experiment_local_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )


def _mock_foreign_experiment_venv(monkeypatch, foreign_venv):
    """Active interpreter is a non-experiment, non-shared virtualenv."""
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setenv("VIRTUAL_ENV", str(foreign_venv))
    monkeypatch.setattr("psynet.experiment_setup.sys.prefix", str(foreign_venv))


def test_setup_initialises_git_repository_when_missing(tmp_path, monkeypatch):
    """Setup creates the repository itself and says so."""
    calls = []
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup.git_repository_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.git_command_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append((args, description)),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "existing"],
        )

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".git").is_dir()
    assert "Initialised a Git repository" in result.output
    assert "You can try running the experiment with the following command:" in (
        result.output
    )
    assert "  psynet debug local" in result.output
    # Setup already did it, so it must not be listed as a command to run.
    assert "  git init" not in result.output
    # This shell is already using the experiment environment.
    assert "source .venv/bin/activate" not in result.output
    assert "does not appear to be installed" not in result.output
    assert (tmp_path / "Dockerfile").exists()
    assert calls  # setup still syncs


def test_setup_tells_delegated_users_to_activate_the_new_environment(
    tmp_path, monkeypatch
):
    """A delegated run's shell is not using .venv yet, so activation is required.

    Without it the user runs a different interpreter than ``.python-version``.
    """
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setenv("PSYNET_SETUP_DELEGATED", "1")
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv", lambda args, description: None
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "existing"],
        )

    assert result.exit_code == 0, result.output
    assert "Activate it yourself before continuing" in result.output
    activate_index = result.output.index("source .venv/bin/activate")
    debug_index = result.output.index("psynet debug local")
    assert activate_index < debug_index


def test_setup_initialises_nested_repo_when_parent_ignores_experiment(
    tmp_path, monkeypatch
):
    """A parent repo that ignores the experiment would package no files.

    Setup must give it a dedicated repository rather than trust the containing
    work tree, which Dallinger's ``git ls-files`` packaging would leave empty.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("experiment/\n")
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "requirements.txt").write_text("psynet==0.0.0\n")
    (experiment / "constraints.txt").write_text("# stale constraints\n")
    (experiment / "experiment.py").write_text("class Exp:\n    pass\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv", lambda args, description: None
    )

    with working_directory(experiment):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "existing"],
        )

    assert result.exit_code == 0, result.output
    assert (experiment / ".git").is_dir()
    assert "ignores this experiment directory" in result.output


def test_useful_commands_reports_failed_git_init_distinctly(capsys):
    """A failed git init must not be reported as Git being absent."""
    from psynet.experiment_setup import _echo_useful_commands, _GitStatus

    _echo_useful_commands(git_status=_GitStatus.INIT_FAILED, activation_required=False)
    output = capsys.readouterr().out
    assert "could not initialise a Git repository" in output
    assert "not installed" not in output
    assert "git init" in output


def test_setup_leaves_existing_work_tree_alone(tmp_path, monkeypatch):
    """An experiment nested in a repository must not get a nested repository."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "requirements.txt").write_text("psynet==0.0.0\n")
    (experiment / "constraints.txt").write_text("# stale constraints\n")
    (experiment / "experiment.py").write_text("class Exp:\n    pass\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv", lambda args, description: None
    )

    with working_directory(experiment):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "existing"],
        )

    assert result.exit_code == 0, result.output
    assert not (experiment / ".git").exists()
    assert "Using the existing Git repository" in result.output


def test_setup_suggests_installing_git_when_command_missing(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup.git_repository_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.git_command_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append((args, description)),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "existing"],
        )

    assert result.exit_code == 0, result.output
    assert "does not appear to be installed" in result.output
    assert "git-scm.com/downloads" in result.output
    # Git is unavailable, so the user must run git init themselves later.
    assert "  git init" in result.output
    assert "  psynet debug local" in result.output
    assert calls


def test_setup_scaffolds_synchronizes_and_checks_dependencies(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append((args, description)),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "existing"],
        )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"
    assert calls == [
        (
            [
                "pip",
                "sync",
                "constraints.txt",
                "--strict",
            ],
            "synchronize experiment dependencies",
        ),
        (["pip", "check"], "verify experiment dependencies"),
    ]


def test_setup_requires_active_virtualenv(monkeypatch):
    from psynet.experiment_setup import _ensure_active_virtualenv

    monkeypatch.setattr("psynet.experiment_setup.sys.prefix", "/usr")
    monkeypatch.setattr("psynet.experiment_setup.sys.base_prefix", "/usr")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    with pytest.raises(click.UsageError, match="uv venv"):
        _ensure_active_virtualenv()


def test_setup_prepares_bundled_demo_without_dependency_changes(tmp_path, monkeypatch):
    requirements = "psynet\nmusic21==9.1.0\n"
    (tmp_path / "requirements.txt").write_text(requirements)
    monkeypatch.setattr("psynet.experiment_setup.is_in_repo_experiment", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("Bundled demo setup must not synchronize"),
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: pytest.fail("Bundled demo setup must not gate on shared venv"),
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "requirements.txt").read_text() == requirements
    assert not (tmp_path / "constraints.txt").exists()
    assert (tmp_path / "Dockerfile").exists()
    assert "bundled demo or test experiment" in result.output
    assert "does not install packages here" in result.output
    assert "Prepared in-repo" not in result.output


def test_setup_requires_source_choice_for_noninteractive_editable_install(
    tmp_path, monkeypatch
):
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet\n")
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: False)
    _mock_dedicated_experiment_venv(monkeypatch)

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"])

    assert result.exit_code != 0
    assert "--psynet-source editable" in result.output
    assert "requirements.txt" in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_prompts_to_preserve_editable_psynet(tmp_path, monkeypatch):
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet\nmusic21==9.1.0\n")
    calls = []
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append(args),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="1\n")

    assert result.exit_code == 0, result.output
    assert "How should setup record it in this experiment's requirements.txt?" in (
        result.output
    )
    assert "What do you want to do?" in result.output
    assert "point requirements at this local checkout" in result.output
    assert (tmp_path / "requirements.txt").read_text() == (
        f"-e {source.as_uri()}#egg=psynet[experiment]\nmusic21==9.1.0\n"
    )
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"
    assert calls == [
        ["pip", "sync", "constraints.txt", "--strict"],
        ["pip", "check"],
    ]


def test_setup_can_pin_editable_psynet_commit(tmp_path, monkeypatch):
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet\n")
    requirement = (
        f"psynet@git+https://gitlab.com/PsyNetDev/PsyNet@{'a' * 40}#egg=psynet"
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.commit_psynet_requirement",
        lambda path: requirement,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._editable_checkout_is_dirty",
        lambda path: False,
    )
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr("psynet.experiment_setup._run_uv", lambda *args: None)

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--psynet-source", "commit"],
        )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "requirements.txt").read_text() == f"{requirement}\n"


def test_setup_no_install_skips_sync_outside_shared_env(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("no-install must not run uv pip sync/check"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"
    assert "without installing packages" in result.output
    assert "Next steps" in result.output


def test_setup_docker_skips_install_and_points_to_docker_docs(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_dedicated_experiment_venv(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("docker setup must not install"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup", "--docker"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "Dockerfile").exists()
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"
    assert "Prepared experiment files for Docker" in result.output
    assert "docker/docs" in result.output


def test_setup_rejects_docker_with_force_shared_env(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--docker", "--force-shared-env"],
        )

    assert result.exit_code != 0
    assert "cannot be used together" in result.output


def test_setup_rejects_force_shared_env_outside_shared_venv(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    _mock_dedicated_experiment_venv(monkeypatch)

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup", "--force-shared-env"])

    assert result.exit_code != 0
    assert "--force-shared-env is only applicable" in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_rejects_no_install_with_force_shared_env(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["setup", "--no-install", "--force-shared-env"],
        )

    assert result.exit_code != 0
    assert "cannot be used together" in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_shared_env_noninteractive_requires_explicit_flag(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: False)

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"])

    assert result.exit_code != 0
    assert "--no-install" in result.output
    assert "--force-shared-env" in result.output
    assert "uv venv" in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_shared_env_no_install_skips_sync(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("no-install must not run uv pip sync/check"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "constraints.txt").read_text() == "# generated constraints\n"
    assert "without installing packages" in result.output


def test_setup_shared_env_force_syncs_with_warning(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append(args),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup", "--force-shared-env"])

    assert result.exit_code == 0, result.output
    assert "can remove packages" in result.output
    assert calls == [
        ["pip", "sync", "constraints.txt", "--strict"],
        ["pip", "check"],
    ]


def test_setup_foreign_env_noninteractive_scaffolds_then_refuses_sync(
    tmp_path, monkeypatch
):
    foreign = tmp_path / "other" / ".venv"
    foreign.mkdir(parents=True)
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    _mock_foreign_experiment_venv(monkeypatch, foreign)
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: False)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args, **kwargs: pytest.fail("foreign env must not sync"),
    )

    with working_directory(experiment):
        result = CliRunner().invoke(psynet, ["setup"])

    assert result.exit_code != 0
    assert "--force-foreign-env" in result.output
    assert (experiment / "Dockerfile").exists()


def test_setup_foreign_env_force_flag_syncs_with_warning(tmp_path, monkeypatch):
    calls = []
    foreign = tmp_path / "other" / ".venv"
    foreign.mkdir(parents=True)
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    _mock_foreign_experiment_venv(monkeypatch, foreign)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append(args),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup", "--force-foreign-env"])

    assert result.exit_code == 0, result.output
    assert "not this experiment's ./.venv" in result.output
    assert calls == [
        ["pip", "sync", "constraints.txt", "--strict"],
        ["pip", "check"],
    ]


def test_is_experiment_local_virtualenv_matches_cwd_venv(tmp_path, monkeypatch):
    from psynet.experiment_setup import _is_experiment_local_virtualenv

    local = tmp_path / ".venv"
    local.mkdir()
    monkeypatch.setenv("VIRTUAL_ENV", str(local))
    with working_directory(tmp_path):
        assert _is_experiment_local_virtualenv()

    foreign = tmp_path / "other" / ".venv"
    foreign.mkdir(parents=True)
    monkeypatch.setenv("VIRTUAL_ENV", str(foreign))
    with working_directory(tmp_path):
        assert not _is_experiment_local_virtualenv()


def test_setup_shared_env_interactive_cancel_makes_no_changes(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("cancel must not synchronize"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="2\n")

    assert result.exit_code == 0, result.output
    assert "Cancelled setup" in result.output
    assert "Aborted!" not in result.output
    assert "dedicated virtualenv" in result.output
    assert not (tmp_path / "Dockerfile").exists()
    assert (tmp_path / "requirements.txt").read_text() == "psynet==0.0.0\n"


def test_setup_shared_env_interactive_no_install(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("no-install must not synchronize"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="3\n")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "Dockerfile").exists()
    assert "without installing packages" in result.output


def test_setup_no_install_skips_editable_source_prompt(tmp_path, monkeypatch):
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args, **kwargs: pytest.fail("no-install must not synchronize"),
    )

    with working_directory(tmp_path):
        # Only the shared-env menu answer; no second editable/commit prompt.
        result = CliRunner().invoke(psynet, ["setup"], input="3\n")

    assert result.exit_code == 0, result.output
    assert "How should setup record it" not in result.output
    assert (tmp_path / "requirements.txt").read_text() == (
        f"-e {source.as_uri()}#egg=psynet[experiment]\n"
    )
    assert "without installing packages" in result.output


def test_setup_no_install_keeps_existing_explicit_pin(tmp_path, monkeypatch):
    source = tmp_path / "psynet-source"
    source.mkdir()
    requirements = "psynet==0.0.0\n"
    (tmp_path / "requirements.txt").write_text(requirements)
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args, **kwargs: pytest.fail("no-install must not synchronize"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="3\n")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "requirements.txt").read_text() == requirements
    assert "How should setup record it" not in result.output


def test_setup_shared_env_interactive_new_venv(tmp_path, monkeypatch):
    """Choosing a dedicated venv installs this PsyNet there and finishes setup."""
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    calls, delegated = _stub_new_venv_delegation(monkeypatch, tmp_path)

    with working_directory(tmp_path):
        # First answer picks the dedicated venv; second records editable PsyNet.
        result = CliRunner().invoke(psynet, ["setup"], input="1\n1\n")

    assert result.exit_code == 0, result.output
    assert "Create a dedicated .venv here and finish setup in it" in result.output
    # The source-recording question is asked up front, before the long steps.
    setup_index = result.output.index("How should setup record it")
    created_index = result.output.index("Created ./.venv.")
    assert setup_index < created_index
    assert "Created ./.venv." in result.output
    assert "Installed PsyNet into ./.venv." in result.output

    # The dedicated environment is created, then this PsyNet is installed there.
    assert calls[0] == (
        ["venv", "--python=3.13"],
        "create a dedicated experiment virtual environment",
        True,
    )
    install_args = calls[1][0]
    assert install_args[:3] == ["pip", "install", "--python"]
    assert install_args[-2:] == ["-e", str(source)]

    # Setup is finished by the new environment's own entry point, and the
    # resolved source choice is forwarded so the delegated run never re-prompts.
    assert len(delegated) == 1
    command, env = delegated[0]
    assert command[0] == str(tmp_path / ".venv" / "bin" / "psynet")
    assert command[1] == "setup"
    assert command[2:] == ["--psynet-source", "editable"]
    assert env["VIRTUAL_ENV"] == str((tmp_path / ".venv").resolve())
    assert env["PSYNET_SETUP_DELEGATED"] == "1"
    # The outer process must not scaffold or repin; the inner run owns that.
    assert not (tmp_path / "Dockerfile").exists()
    assert (tmp_path / "requirements.txt").read_text() == "psynet==0.0.0\n"


def test_setup_detects_psynet_running_from_other_virtualenv(tmp_path, monkeypatch):
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    experiment_venv = tmp_path / ".venv"
    experiment_venv.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    shared_prefix = tmp_path / "shared-venv"
    shared_prefix.mkdir()
    source = tmp_path / "psynet-source"
    source.mkdir()

    monkeypatch.setenv("VIRTUAL_ENV", str(experiment_venv))
    monkeypatch.setattr("psynet.experiment_setup.sys.prefix", str(shared_prefix))
    monkeypatch.setattr(
        "psynet.experiment_setup.sys.base_prefix", str(tmp_path / "base")
    )
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args, **kwargs: pytest.fail("mismatch must fail before uv"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"])

    assert result.exit_code != 0
    assert "not installed in the activated environment" in result.output
    assert f"uv pip install -e {source}" in result.output
    assert "shared checkout environment" not in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_shared_env_interactive_new_venv_suggests_editable_install(
    tmp_path, monkeypatch
):
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: source,
    )
    uv_calls, _delegated = _stub_new_venv_delegation(monkeypatch, tmp_path)

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="1\n1\n")

    assert result.exit_code == 0, result.output
    # The editable checkout is installed into the new environment, not merely
    # suggested to the user.
    install_args = next(
        args for args, _, _ in uv_calls if args[:2] == ["pip", "install"]
    )
    assert install_args[-2:] == ["-e", str(source)]


def test_delegated_setup_does_not_inherit_pythonpath(tmp_path, monkeypatch):
    """PYTHONPATH precedes site-packages, so it must not leak into delegation.

    Otherwise the delegated run could import a different PsyNet than the one
    installed into the experiment's environment.
    """
    source = tmp_path / "psynet-source"
    source.mkdir()
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else/PsyNet")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services", lambda **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv", lambda: True
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source", lambda: source
    )
    _uv_calls, delegated = _stub_new_venv_delegation(monkeypatch, tmp_path)

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="1\n1\n")

    assert result.exit_code == 0, result.output
    _command, env = delegated[0]
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_setup_delegated_run_does_not_create_another_venv(tmp_path, monkeypatch):
    """The delegated setup must never recurse into creating a second venv."""
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setenv("PSYNET_SETUP_DELEGATED", "1")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services", lambda **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv", lambda: True
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source", lambda: None
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args, **kwargs: pytest.fail("delegated setup must not create a venv"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="1\n")

    assert result.exit_code != 0
    assert "Delegated setup tried to create another dedicated environment" in (
        result.output
    )


def test_setup_shared_env_interactive_new_venv_default(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source", lambda: None
    )
    uv_calls, delegated = _stub_new_venv_delegation(monkeypatch, tmp_path)

    with working_directory(tmp_path):
        # Accept the recommended default (new-venv); no editable source prompt.
        result = CliRunner().invoke(psynet, ["setup"], input="\n")

    assert result.exit_code == 0, result.output
    assert [args for args, _, _ in uv_calls][0] == ["venv", "--python=3.13"]
    assert len(delegated) == 1
    assert "Aborted!" not in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_shared_env_interactive_new_venv_rejects_existing_venv(
    tmp_path, monkeypatch
):
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source", lambda: None
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda *args: pytest.fail("must not recreate an existing .venv"),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="1\n")

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_setup_shared_env_interactive_sync(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# stale constraints\n")
    monkeypatch.setattr(
        "psynet.experiment_setup._ensure_active_virtualenv", lambda: None
    )
    _assume_git_repository(monkeypatch)
    monkeypatch.setattr(
        "psynet.experiment_setup._handle_setup_services",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._is_psynet_checkout_virtualenv",
        lambda: True,
    )
    monkeypatch.setattr("psynet.experiment_setup._is_interactive", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment_setup.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_setup._run_uv",
        lambda args, description: calls.append(args),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["setup"], input="4\n")

    assert result.exit_code == 0, result.output
    assert "can remove packages" in result.output
    assert calls == [
        ["pip", "sync", "constraints.txt", "--strict"],
        ["pip", "check"],
    ]


def test_is_psynet_checkout_virtualenv_detects_checkout_venv(tmp_path, monkeypatch):
    from psynet.experiment_setup import _is_psynet_checkout_virtualenv

    root = tmp_path / "psynet"
    venv = root / ".venv"
    venv.mkdir(parents=True)
    monkeypatch.setattr("psynet.experiment_setup.get_psynet_root", lambda: root)
    monkeypatch.setattr("psynet.experiment_setup.sys.prefix", str(venv))

    assert _is_psynet_checkout_virtualenv() is True

    nested = root / "demos" / "features" / "foo" / ".venv"
    nested.mkdir(parents=True)
    monkeypatch.setattr("psynet.experiment_setup.sys.prefix", str(nested))
    assert _is_psynet_checkout_virtualenv() is False

    monkeypatch.setattr(
        "psynet.experiment_setup.sys.prefix", str(tmp_path / "other-venv")
    )
    assert _is_psynet_checkout_virtualenv() is False


def test_scripts_scaffold_preserves_empty_config_for_existing_experiment(tmp_path):
    (tmp_path / "experiment.py").write_text("class Exp:\n    config = {'title': 'X'}\n")
    (tmp_path / "requirements.txt").write_text("psynet==0.0.0\n")
    (tmp_path / "constraints.txt").write_text("# existing constraints\n")
    (tmp_path / "config.txt").touch()

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["scripts", "scaffold"])
        missing_boilerplate = missing_scaffold_paths_required_for_local_run()

    assert result.exit_code == 0, result.output
    assert (tmp_path / "config.txt").read_text() == ""
    assert missing_boilerplate == []


def test_missing_scaffold_boilerplate_requires_minimal_local_run_set(tmp_path):
    with working_directory(tmp_path):
        assert missing_scaffold_paths_required_for_local_run() == [
            ".gitignore",
            ".python-version",
            "Dockerfile",
            "config.txt",
            "docker",
            "test.py",
        ]

        (tmp_path / ".gitignore").write_text("source_code.zip\n")
        (tmp_path / ".python-version").write_text("3.13\n")
        (tmp_path / "config.txt").touch()
        assert missing_scaffold_paths_required_for_local_run() == [
            "Dockerfile",
            "docker",
            "test.py",
        ]

        (tmp_path / "Dockerfile").write_text("FROM python:3.13\n")
        (tmp_path / "test.py").write_text("def test_dummy():\n    assert True\n")
        (tmp_path / "docker").mkdir()
        assert missing_scaffold_paths_required_for_local_run() == []

        (tmp_path / "docker").rmdir()
        (tmp_path / "docker").write_text("not a directory\n")
        assert missing_scaffold_paths_required_for_local_run() == ["docker"]


def test_prepare_in_repo_experiment_satisfies_scaffold_boilerplate(
    tmp_path, monkeypatch
):
    from psynet.command_line import _prepare_in_repo_experiment
    from psynet.experiment_scaffold import scaffold_paths_required_for_local_run

    (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
    (tmp_path / "requirements.txt").write_text("psynet\n")
    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: True)

    with working_directory(tmp_path):
        assert _prepare_in_repo_experiment() is True
        assert missing_scaffold_paths_required_for_local_run() == []
        for relative_path in scaffold_paths_required_for_local_run():
            assert (tmp_path / relative_path).exists()


def test_check_experiment_directory_reports_missing_boilerplate(tmp_path):
    from psynet.command_line import _check_experiment_directory

    with working_directory(tmp_path):
        with pytest.raises(click.ClickException, match="psynet setup") as exc:
            _check_experiment_directory("debug")
    message = str(exc.value)
    assert "standalone" in message.lower()
    for required_path in (
        ".gitignore",
        ".python-version",
        "config.txt",
        "Dockerfile",
        "test.py",
        "docker",
    ):
        assert required_path in message


def test_check_experiment_directory_suggests_scaffold_for_in_repo(
    tmp_path, monkeypatch
):
    from psynet.command_line import _check_experiment_directory

    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: True)
    monkeypatch.setattr(
        "psynet.command_line._prepare_in_repo_experiment",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.command_line.missing_scaffold_paths_required_for_local_run",
        lambda: ["Dockerfile"],
    )

    with working_directory(tmp_path):
        with pytest.raises(
            click.ClickException, match="psynet scripts scaffold"
        ) as exc:
            _check_experiment_directory("debug")
    assert (
        "bundled demo" in str(exc.value).lower()
        or "test experiment" in str(exc.value).lower()
    )


def test_check_experiment_directory_reports_partial_boilerplate(tmp_path, monkeypatch):
    from psynet.command_line import _check_experiment_directory

    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: False)
    (tmp_path / ".gitignore").write_text("source_code.zip\n")
    (tmp_path / ".python-version").write_text("3.13\n")
    (tmp_path / "config.txt").touch()

    with working_directory(tmp_path):
        with pytest.raises(click.ClickException, match="psynet setup") as exc:
            _check_experiment_directory("debug")
    missing_section = str(exc.value).split("(")[1].split(")")[0]
    assert "Dockerfile" in missing_section
    assert "test.py" in missing_section
    assert "docker" in missing_section
    assert ".gitignore" not in missing_section
    assert "config.txt" not in missing_section
    assert "touch config.txt" not in str(exc.value)


def test_missing_boilerplate_fix_mentions_blank_config_for_upgrades():
    from psynet.command_line import _missing_boilerplate_fix

    message = _missing_boilerplate_fix(
        mode="debug", missing_paths=["config.txt", "Dockerfile"]
    )
    assert "touch config.txt" in message
    assert "Experiment.config" in message

    without_config = _missing_boilerplate_fix(
        mode="debug", missing_paths=["Dockerfile"]
    )
    assert "touch config.txt" not in without_config


def test_check_experiment_directory_reports_missing_git(tmp_path, monkeypatch):
    from psynet.command_line import _check_experiment_directory

    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: False)
    monkeypatch.setattr("psynet.command_line.git_repository_available", lambda: False)

    with working_directory(tmp_path):
        (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
        (tmp_path / "requirements.txt").write_text("psynet\n")
        scaffold_experiment_directory()
        with pytest.raises(click.ClickException, match="git init"):
            _check_experiment_directory("debug")


def test_check_experiment_directory_passes_with_scaffold_and_git(tmp_path, monkeypatch):
    from psynet.command_line import _check_experiment_directory

    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: False)
    monkeypatch.setattr("psynet.command_line.git_repository_available", lambda: True)

    with working_directory(tmp_path):
        (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
        (tmp_path / "requirements.txt").write_text("psynet\n")
        scaffold_experiment_directory()
        _check_experiment_directory("debug")


def test_test_local_reports_missing_scaffold_like_debug(tmp_path, monkeypatch):
    """Non-bundled dirs missing local-run scaffold fail the same way as debug."""
    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: False)
    (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
    runner = CliRunner()

    with working_directory(tmp_path):
        result = runner.invoke(psynet, ["test", "local"])

    assert result.exit_code != 0
    message = result.output
    assert "psynet setup" in message
    for required_path in (
        ".gitignore",
        ".python-version",
        "config.txt",
        "Dockerfile",
        "test.py",
        "docker",
    ):
        assert required_path in message


def test_test_local_prepares_bundled_demo_via_directory_check(tmp_path, monkeypatch):
    """Bundled demos are scaffolded inside _check_experiment_directory, then tested."""
    from psynet.experiment_scaffold import scaffold_paths_required_for_local_run

    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: True)
    monkeypatch.setattr("psynet.command_line.git_repository_available", lambda: True)

    (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
    (tmp_path / "requirements.txt").write_text("psynet\n")

    mock_exp = Mock()
    runner = CliRunner()

    with (
        working_directory(tmp_path),
        patch("psynet.experiment.get_experiment", return_value=mock_exp),
        patch("pytest.main", return_value=0) as mock_pytest_main,
    ):
        result = runner.invoke(psynet, ["test", "local"])

    assert result.exit_code == 0, result.output
    mock_pytest_main.assert_called_once_with(["test.py"])
    for relative_path in scaffold_paths_required_for_local_run():
        assert (tmp_path / relative_path).exists()


def test_test_local_existing_bypasses_scaffold_gate(tmp_path, monkeypatch):
    """--existing talks to a live server and must not require local scaffold/git."""
    (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
    mock_exp = Mock()
    runner = CliRunner()

    with (
        working_directory(tmp_path),
        patch(
            "psynet.command_line._check_experiment_directory"
        ) as mock_check_directory,
        patch("psynet.experiment.get_experiment", return_value=mock_exp),
    ):
        result = runner.invoke(psynet, ["test", "local", "--existing"])

    assert result.exit_code == 0, result.output
    mock_check_directory.assert_not_called()
    mock_exp.test_experiment.assert_called_once_with()


def test_scripts_scaffold_allows_incomplete_experiment_py():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("print('not an experiment yet')\n")

            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code == 0, result.output
            assert (
                Path("experiment.py").read_text() == "print('not an experiment yet')\n"
            )
            assert Path("Dockerfile").exists()
            assert Path("requirements.txt").exists()


def test_scripts_scaffold_reports_when_nothing_is_needed():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            first = runner.invoke(psynet, ["scripts", "scaffold"])
            assert first.exit_code == 0, first.output

            second = runner.invoke(psynet, ["scripts", "scaffold"])
            assert second.exit_code == 0, second.output
            assert (
                "Nothing to scaffold; experiment boilerplate is already present."
                in second.output
            )


def test_scripts_scaffold_preserves_existing_authored_files():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    label = 'Custom'\n")
            Path("requirements.txt").write_text("psynet==0.0.0\n")

            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code == 0, result.output
            assert (
                Path("experiment.py").read_text()
                == "class Exp:\n    label = 'Custom'\n"
            )
            assert Path("requirements.txt").read_text() == "psynet==0.0.0\n"


def test_scripts_update_does_not_overwrite_authored_bootstrap_files():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    label = 'Custom'\n")
            Path("requirements.txt").write_text("psynet==0.0.0\n")

            result = runner.invoke(psynet, ["scripts", "update"])

            assert result.exit_code == 0, result.output
            assert (
                Path("experiment.py").read_text()
                == "class Exp:\n    label = 'Custom'\n"
            )
            assert Path("requirements.txt").read_text() == "psynet==0.0.0\n"


def test_scripts_update_preserves_customized_config_txt():
    runner = CliRunner()
    custom_config = "[HIT Configuration]\ntitle = Custom experiment\n"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("config.txt").write_text(custom_config)

            result = runner.invoke(psynet, ["scripts", "update"])

            assert result.exit_code == 0, result.output
            assert Path("config.txt").read_text() == custom_config
            assert Path("Dockerfile").exists()


def test_scripts_update_preserves_customized_readme():
    runner = CliRunner()
    custom_readme = "# Custom experiment README\n\nAuthored notes.\n"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("README.md").write_text(custom_readme)

            result = runner.invoke(psynet, ["scripts", "update"])

            assert result.exit_code == 0, result.output
            assert Path("README.md").read_text() == custom_readme
            assert Path("Dockerfile").exists()


def test_scripts_prune_preserves_bootstrapped_authored_files():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            result = runner.invoke(psynet, ["scripts", "scaffold"])
            assert result.exit_code == 0, result.output

            result = runner.invoke(psynet, ["scripts", "prune"])
            assert result.exit_code == 0, result.output
            assert Path("experiment.py").exists()
            assert Path("requirements.txt").exists()
            assert Path("Dockerfile").exists() is False
            assert Path("config.txt").exists() is False
            assert Path("docker").exists() is False


def test_scaffold_creates_missing_files_without_overwriting_readme():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("requirements.txt").write_text("psynet==0.0.0\n")
            Path("README.md").write_text("# Custom README\n")

            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code == 0
            assert Path("README.md").read_text() == "# Custom README\n"
            assert Path("config.txt").exists()
            assert "title = Demo experiment" in Path("config.txt").read_text()
            assert Path("Dockerfile").exists()
            assert Path("test.py").exists()
            assert Path("docker/psynet").exists()
            assert Path(".gitignore").exists()
            assert Path(".python-version").exists()


def test_update_scripts_alias_emits_deprecation_warning():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")

            result = runner.invoke(psynet, ["update-scripts"])

            assert result.exit_code == 0
            assert (
                "psynet update-scripts is deprecated; "
                "use 'psynet scripts update' instead."
            ) in result.output
            assert Path("Dockerfile").exists()


def test_update_alias_emits_installation_update_deprecation(monkeypatch):
    calls = []

    def fake_update(dallinger_version, psynet_version, verbose):
        calls.append((dallinger_version, psynet_version, verbose))

    monkeypatch.setattr(
        "psynet.command_line._run_installation_update",
        fake_update,
    )
    result = CliRunner().invoke(psynet, ["update", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "psynet update is deprecated" in result.output
    assert "psynet installation update" in result.output
    assert calls == [("latest", "latest", True)]


def test_installation_update_help_mentions_scripts_update_distinction():
    result = CliRunner().invoke(psynet, ["installation", "update", "--help"])

    assert result.exit_code == 0, result.output
    assert "scripts update" in result.output
    assert "boilerplate" in result.output.lower() or "experiment" in result.output


def test_scripts_update_overwrites_boilerplate():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("Dockerfile").write_text("FROM outdated\n")

            result = runner.invoke(psynet, ["scripts", "update"])

            assert result.exit_code == 0
            assert "FROM outdated" not in Path("Dockerfile").read_text()
            assert Path("Dockerfile").read_text()


def test_scripts_update_reports_only_actual_changes(tmp_path):
    runner = CliRunner()

    with working_directory(tmp_path):
        scaffold = runner.invoke(psynet, ["scripts", "scaffold"])
        assert scaffold.exit_code == 0, scaffold.output

        no_op = runner.invoke(psynet, ["scripts", "update"])
        assert no_op.exit_code == 0, no_op.output
        assert "already up to date" in no_op.output
        assert "updated:" not in no_op.output

        Path("Dockerfile").write_text("FROM outdated\n")
        changed = runner.invoke(psynet, ["scripts", "update"])
        assert changed.exit_code == 0, changed.output
        assert "updated: 1 boilerplate file" in changed.output
        assert "FROM outdated" not in Path("Dockerfile").read_text()

        expected_run_script = Path("docker/run").read_text()
        Path("docker/run").write_text("# Outdated\n")
        changed_directory = runner.invoke(psynet, ["scripts", "update"])
        assert changed_directory.exit_code == 0, changed_directory.output
        assert "updated: 1 boilerplate file" in changed_directory.output
        assert Path("docker/run").read_text() == expected_run_script


def test_scripts_prune_removes_boilerplate_and_preserves_divergent_readme():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("requirements.txt").write_text("psynet==0.0.0\n")
            Path("constraints.txt").write_text("psynet==0.0.0\n")
            Path("README.md").write_text("# Minimal demo\n")

            scaffold_experiment_directory(overwrite=True)
            Path("README.md").write_text("# Minimal demo\n")
            Path("static").mkdir()
            Path("templates").mkdir()
            Path("templates/.keep").touch()

            result = runner.invoke(psynet, ["scripts", "prune"])

            assert result.exit_code == 0
            # Divergent README is preserved without --include-modified.
            assert Path("README.md").read_text() == "# Minimal demo\n"
            assert Path("requirements.txt").exists()
            assert Path("constraints.txt").exists() is False
            assert Path("Dockerfile").exists() is False
            assert Path("test.py").exists() is False
            assert Path("config.txt").exists() is False
            assert Path("docker").exists() is False
            assert Path("static").exists() is False
            assert Path("templates").exists() is False


def test_scripts_prune_preserves_authored_resource_directories(tmp_path):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        scaffold_experiment_directory(overwrite=True)
        Path("static").mkdir()
        Path("static/app.js").write_text("// Custom script\n")
        Path("templates").mkdir()
        Path("templates/custom.html").write_text("<p>Custom template</p>\n")

        result = CliRunner().invoke(psynet, ["scripts", "prune"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "static/app.js").exists()
    assert (tmp_path / "templates/custom.html").exists()


def test_scripts_prune_removes_generated_static_assets_symlink(tmp_path):
    assets_directory = tmp_path / "generated-assets"
    assets_directory.mkdir()
    (assets_directory / "asset.txt").write_text("Generated asset\n")

    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        scaffold_experiment_directory(overwrite=True)
        Path("static").mkdir()
        Path("static/assets").symlink_to(assets_directory, target_is_directory=True)

        result = CliRunner().invoke(psynet, ["scripts", "prune"])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "static").exists()
    assert (assets_directory / "asset.txt").read_text() == "Generated asset\n"


def test_scripts_prune_warns_before_forcing_unrecognized_boilerplate(tmp_path):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        scaffold_experiment_directory(overwrite=True)
        Path("test.py").write_text("# Custom test\n")
        Path("docker/psynet").write_text("# Custom helper\n")

        result = CliRunner().invoke(psynet, ["scripts", "prune"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "test.py").read_text() == "# Custom test\n"
    assert (tmp_path / "docker/psynet").read_text() == "# Custom helper\n"
    assert (
        "Preserved scaffold paths that differ from current PsyNet templates:"
        in result.output
    )
    assert "  - docker" in result.output
    assert "  - test.py" in result.output
    assert "may be customized or generated by another PsyNet version" in result.output
    assert (
        "If you are sure you want to delete them, run 'psynet scripts prune --include-modified'."
    ) in result.output
    assert not (tmp_path / "Dockerfile").exists()


def test_scripts_prune_include_modified_removes_divergent_boilerplate(tmp_path):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        scaffold_experiment_directory(overwrite=True)
        Path("test.py").write_text("# Custom test\n")
        Path("docker/psynet").write_text("# Custom helper\n")
        Path("config.txt").write_text("[Config]\ntitle = Custom experiment\n")
        Path("README.md").write_text("# Custom README\n")

        result = CliRunner().invoke(psynet, ["scripts", "prune", "--include-modified"])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "test.py").exists()
    assert not (tmp_path / "docker").exists()
    assert not (tmp_path / "config.txt").exists()
    assert not (tmp_path / "README.md").exists()


def test_scripts_prune_keeps_git_tracked_readme_by_default(tmp_path):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        Path("README.md").write_text("# Tracked README\n")
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "-qm",
                "init",
            ],
            check=True,
        )
        scaffold_experiment_directory(overwrite=True)
        Path("README.md").write_text("# Tracked README\n")

        result = CliRunner().invoke(psynet, ["scripts", "prune", "--include-modified"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "README.md").read_text() == "# Tracked README\n"
    assert not (tmp_path / "Dockerfile").exists()
    assert not (tmp_path / "test.py").exists()


def test_scripts_prune_keeps_tracked_files_under_docker_by_default(tmp_path):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        Path("docker").mkdir()
        Path("docker/psynet").write_text("# Tracked custom helper\n")
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "-qm",
                "init",
            ],
            check=True,
        )
        scaffold_experiment_directory(overwrite=True)
        Path("docker/psynet").write_text("# Tracked custom helper\n")

        result = CliRunner().invoke(psynet, ["scripts", "prune", "--include-modified"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "docker/psynet").read_text() == "# Tracked custom helper\n"
    assert not (tmp_path / "Dockerfile").exists()


def test_scripts_prune_errors_when_git_listing_fails(tmp_path, monkeypatch):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        Path("README.md").write_text("# Custom README\n")
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "-qm",
                "init",
            ],
            check=True,
        )
        scaffold_experiment_directory(overwrite=True)
        Path("README.md").write_text("# Custom README\n")

        real_check_output = subprocess.check_output

        def _fail_git_ls_files(*args, **kwargs):
            command = args[0]
            if isinstance(command, (list, tuple)) and "ls-files" in command:
                raise subprocess.CalledProcessError(128, command)
            return real_check_output(*args, **kwargs)

        monkeypatch.setattr(
            "psynet.experiment_scaffold.subprocess.check_output",
            _fail_git_ls_files,
        )

        result = CliRunner().invoke(psynet, ["scripts", "prune", "--include-modified"])

    assert result.exit_code != 0
    assert "Listing tracked files failed" in result.output
    assert (tmp_path / "README.md").read_text() == "# Custom README\n"


def test_scripts_prune_removes_template_identical_readme_by_default(tmp_path):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        scaffold_experiment_directory(overwrite=True)
        assert Path("README.md").exists()

        result = CliRunner().invoke(psynet, ["scripts", "prune"])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "README.md").exists()


def test_bootstrap_cli_prune_include_modified(tmp_path):
    from psynet.bootstrap_cli import _bootstrap

    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet==0.0.0\n")
        Path("README.md").write_text("# Tracked README\n")
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "-qm",
                "init",
            ],
            check=True,
        )
        scaffold_experiment_directory(overwrite=True)
        Path("README.md").write_text("# Tracked README\n")

        result = CliRunner().invoke(
            _bootstrap, ["scripts", "prune", "--include-modified"]
        )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "README.md").read_text() == "# Tracked README\n"
    assert not (tmp_path / "Dockerfile").exists()


def test_scripts_group_help_lists_subcommands():
    result = CliRunner().invoke(psynet, ["scripts", "--help"])

    assert result.exit_code == 0
    assert "scaffold" in result.output
    assert "update" in result.output
    assert "prune" in result.output


def test_scripts_prune_help_is_shared_across_cli_surfaces():
    from psynet.bootstrap_cli import _bootstrap

    for cli in (psynet, _bootstrap):
        result = CliRunner().invoke(cli, ["scripts", "prune", "--help"])
        assert result.exit_code == 0, result.output
        assert "--include-modified" in result.output
        assert "--include-tracked" in result.output
        # Click may rewrap text; check distinctive shared phrases.
        assert "unmodified, untracked scaffold" in result.output
        assert "static/assets" in result.output
        assert "include-modified" in result.output
        assert "Remove scaffold-managed boilerplate" in result.output


def test_scaffold_fills_partial_directories_without_overwriting_existing_files():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("docker").mkdir()
            Path("docker/psynet").write_text("# Custom helper\n")

            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code == 0
            assert Path("docker/psynet").read_text() == "# Custom helper\n"
            assert Path("docker/run").exists()


def test_scaffold_rejects_symlinked_managed_directory(tmp_path):
    runner = CliRunner()
    experiment_directory = tmp_path / "experiment"
    outside_directory = tmp_path / "outside"
    experiment_directory.mkdir()
    outside_directory.mkdir()
    (experiment_directory / "docker").symlink_to(
        outside_directory, target_is_directory=True
    )

    with working_directory(experiment_directory):
        result = runner.invoke(psynet, ["scripts", "scaffold"])

    assert result.exit_code != 0
    assert "symlink" in result.output
    assert list(outside_directory.iterdir()) == []


def test_scaffold_makes_docker_entries_executable():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")

            result = runner.invoke(psynet, ["scripts", "scaffold"])

            assert result.exit_code == 0
            for path in Path("docker").iterdir():
                assert path.stat().st_mode & stat.S_IXUSR


def test_prune_experiment_scaffold_preserves_divergent_config_by_default():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("experiment.py").write_text("class Exp:\n    pass\n")
            Path("requirements.txt").write_text("psynet==0.0.0\n")
            Path("constraints.txt").write_text("psynet==0.0.0\n")

            scaffold_experiment_directory(overwrite=True)
            custom_config = "[Config]\ntitle = Custom experiment\n"
            Path("config.txt").write_text(custom_config)

            prune_result = prune_experiment_scaffold()

            assert Path("requirements.txt").exists()
            assert Path("constraints.txt").exists() is False
            assert Path("Dockerfile").exists() is False
            assert Path("test.py").exists() is False
            assert Path("config.txt").read_text() == custom_config
            assert Path("docker").exists() is False
            assert prune_result["preserved_unrecognized"] == ["config.txt"]
            assert prune_result["removed_constraints"] is True
            assert "Dockerfile" in prune_result["removed"]
            assert "test.py" in prune_result["removed"]
            assert "docker" in prune_result["removed"]
            assert "config.txt" not in prune_result["removed"]


def test_prune_experiment_scaffold_propagates_directory_deletion_errors(
    tmp_path, monkeypatch
):
    with working_directory(tmp_path):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        scaffold_experiment_directory(overwrite=True)

        def fail_unless_errors_are_ignored(path, *, ignore_errors=False):
            if not ignore_errors:
                raise PermissionError(path)

        monkeypatch.setattr(
            "psynet.experiment_scaffold.shutil.rmtree",
            fail_unless_errors_are_ignored,
        )

        with pytest.raises(PermissionError, match="docker"):
            prune_experiment_scaffold()


def test_remove_empty_parent_dirs_stops_at_workspace_root(tmp_path, monkeypatch):
    nested_directory = tmp_path / ".github/workflows"
    nested_directory.mkdir(parents=True)
    original_rmdir = Path.rmdir

    def guarded_rmdir(path):
        assert path.resolve() != tmp_path.resolve()
        return original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", guarded_rmdir)
    with working_directory(tmp_path):
        _remove_empty_parent_dirs(Path(".github/workflows"))

    assert not (tmp_path / ".github").exists()


def test_abort_if_app_exists():
    from psynet.command_line import _abort_if_app_exists

    app = Mock()
    app.name = "test-app"
    with (
        patch(
            "dallinger.command_line.docker_ssh.get_apps",
            return_value=[app],
        ),
        patch("psynet.command_line.click.echo") as mock_echo,
    ):
        with pytest.raises(click.Abort):
            _abort_if_app_exists(server="test-server", app="test-app")
    assert mock_echo.call_count == 1


def test_abort_if_app_exists_skips_missing_app():
    from psynet.command_line import _abort_if_app_exists

    app = Mock()
    app.name = "other-app"
    with (
        patch(
            "dallinger.command_line.docker_ssh.get_apps",
            return_value=[app],
        ),
        patch("psynet.command_line.click.echo") as mock_echo,
    ):
        _abort_if_app_exists(server="test-server", app="test-app")

    mock_echo.assert_not_called()


def test_pre_launch_aborts_when_app_exists():
    from psynet.command_line import _pre_launch

    ctx = Mock()
    with (
        patch("psynet.command_line._check_experiment_directory"),
        patch("psynet.command_line.redis_vars.clear"),
        patch("psynet.command_line.deployment_info.init"),
        patch("psynet.command_line.deployment_info.write"),
        patch("dallinger.command_line.docker_ssh.ensure_remote_host_in_known_hosts"),
        patch("psynet.command_line._abort_if_app_exists", side_effect=click.Abort),
        patch("psynet.command_line.run_pre_checks") as mock_run_pre_checks,
        patch(
            "psynet.command_line.CONFIGURED_HOSTS",
            {"test-server": {"host": "example.com", "user": "test-user"}},
        ),
    ):
        with pytest.raises(click.Abort):
            _pre_launch(
                ctx,
                mode="live",
                archive=None,
                local_=False,
                ssh=True,
                docker=True,
                server="test-server",
                app="test-app",
            )

    mock_run_pre_checks.assert_not_called()


def test_pre_launch_skips_dependency_check_for_in_repo_experiments(
    tmp_path, monkeypatch
):
    """In-repo demos must not let Dallinger invent constraints.txt."""
    import os

    from psynet.command_line import _pre_launch

    monkeypatch.delenv("SKIP_DEPENDENCY_CHECK", raising=False)
    monkeypatch.setattr("psynet.command_line.is_in_repo_experiment", lambda: True)
    monkeypatch.setattr(
        "psynet.command_line._check_experiment_directory", lambda mode: None
    )
    monkeypatch.setattr("psynet.services.ensure_local_services", lambda **kwargs: None)
    monkeypatch.setattr("psynet.command_line.redis_vars.clear", lambda: None)
    monkeypatch.setattr(
        "psynet.command_line.deployment_info.init", lambda **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.run_pre_checks", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.experiment.get_experiment",
        Mock(side_effect=RuntimeError("stop-after-skip")),
    )

    with working_directory(tmp_path):
        with pytest.raises(RuntimeError, match="stop-after-skip"):
            _pre_launch(
                Mock(),
                mode="debug",
                archive=None,
                local_=True,
                docker=False,
            )

    assert os.environ.get("SKIP_DEPENDENCY_CHECK") == "1"
    os.environ.pop("SKIP_DEPENDENCY_CHECK", None)


def test_pre_launch_checks_directory_before_redis():
    """Directory guidance must run before Redis I/O when Redis is unavailable."""
    from psynet.command_line import _pre_launch

    ctx = Mock()
    call_order = []

    with (
        patch(
            "psynet.command_line._check_experiment_directory",
            side_effect=lambda mode: call_order.append("directory"),
        ),
        patch(
            "psynet.command_line.redis_vars.clear",
            side_effect=ConnectionError("Redis unavailable"),
        ) as mock_redis_clear,
        patch("psynet.command_line.deployment_info.init"),
        patch("psynet.command_line.run_pre_checks"),
    ):
        with pytest.raises(ConnectionError, match="Redis unavailable"):
            _pre_launch(
                ctx,
                mode="debug",
                archive=None,
                local_=True,
            )

    assert call_order == ["directory"]
    mock_redis_clear.assert_called_once()


def test_pre_launch_reports_missing_boilerplate_without_redis(tmp_path):
    from psynet.command_line import _pre_launch

    ctx = Mock()
    with working_directory(tmp_path):
        with (
            patch(
                "psynet.command_line.redis_vars.clear",
                side_effect=AssertionError("Redis must not be touched"),
            ),
            patch("psynet.command_line.deployment_info.init"),
            patch("psynet.command_line.run_pre_checks"),
        ):
            with pytest.raises(click.ClickException, match="psynet setup"):
                _pre_launch(
                    ctx,
                    mode="debug",
                    archive=None,
                    local_=True,
                )


def test_enable_sql_profile_uses_unique_run_subdirectories(tmp_path, monkeypatch):
    monkeypatch.delenv("PSYNET_SQL_PROFILE", raising=False)
    monkeypatch.delenv("PSYNET_SQL_PROFILE_DIR", raising=False)
    monkeypatch.delenv("PSYNET_SQL_PROFILE_SILENT", raising=False)

    parent_dir = tmp_path / "profiles"
    profile_dir_1, keep_dir_1 = _enable_sql_profile(None, str(parent_dir))
    profile_dir_2, keep_dir_2 = _enable_sql_profile(None, str(parent_dir))

    assert keep_dir_1 is True
    assert keep_dir_2 is True
    assert profile_dir_1 != profile_dir_2
    assert Path(profile_dir_1).parent == parent_dir
    assert Path(profile_dir_2).parent == parent_dir
    assert Path(profile_dir_1).is_dir()
    assert Path(profile_dir_2).is_dir()


def test_create_sql_profile_run_dir_with_custom_parent(tmp_path):
    parent_dir = tmp_path / "profiles"

    profile_dir_1, keep_dir_1 = _create_sql_profile_run_dir(str(parent_dir))
    profile_dir_2, keep_dir_2 = _create_sql_profile_run_dir(str(parent_dir))

    assert keep_dir_1 is True
    assert keep_dir_2 is True
    assert profile_dir_1 != profile_dir_2
    assert Path(profile_dir_1).parent == parent_dir
    assert Path(profile_dir_2).parent == parent_dir


def test_create_sql_profile_run_dir_without_custom_parent():
    profile_dir, keep_dir = _create_sql_profile_run_dir(None)

    assert keep_dir is False
    assert Path(profile_dir).is_dir()
    assert Path(profile_dir).name.startswith("psynet-sql-profile-")


def test_start_local_server_uses_debug_local_subprocess():
    from psynet.command_line import _start_local_server_and_wait_for_ready, _stop_server

    process = Mock()
    process.expect_exact.return_value = None
    process.isalive.return_value = False
    command_args = ["debug", "local", "--legacy", "--no-browsers"]

    with patch("psynet.command_line.pexpect.spawn", return_value=process) as spawn:
        server_info = _start_local_server_and_wait_for_ready(
            command_args,
            debug=False,
            max_wait=5,
        )

    assert server_info["process"] is process
    args, kwargs = spawn.call_args
    assert args == ("psynet", command_args)
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["env"]["SKIP_DEPENDENCY_CHECK"] == "1"
    assert kwargs["env"]["BROWSER"] == "true"
    _stop_server(server_info)


def test_start_local_server_uses_exact_command_args():
    from psynet.command_line import _start_local_server_and_wait_for_ready, _stop_server

    process = Mock()
    process.expect_exact.return_value = None
    process.isalive.return_value = False
    command_args = ["debug", "local"]

    with patch("psynet.command_line.pexpect.spawn", return_value=process) as spawn:
        server_info = _start_local_server_and_wait_for_ready(
            command_args,
            debug=False,
            max_wait=5,
        )

    args, kwargs = spawn.call_args
    assert args == ("psynet", command_args)
    assert kwargs["encoding"] == "utf-8"
    _stop_server(server_info)


@pytest.mark.parametrize(
    ("exception_name", "expected_message"),
    [
        ("EOF", "Server process exited before becoming ready"),
        ("TIMEOUT", "Server failed to start within 5 seconds"),
    ],
)
def test_start_local_server_reports_the_correct_failure(
    capsys, exception_name, expected_message
):
    from psynet.command_line import (
        _start_local_server_and_wait_for_ready,
        pexpect,
    )

    process = Mock()
    process.expect_exact.side_effect = getattr(pexpect, exception_name)("failed")
    process.before = "underlying server error"
    process.isalive.return_value = False

    with (
        patch("psynet.command_line.pexpect.spawn", return_value=process),
        pytest.raises(click.ClickException, match="Failed to start experiment server"),
    ):
        _start_local_server_and_wait_for_ready(["debug", "local"], max_wait=5)

    captured = capsys.readouterr()
    assert expected_message in captured.err
    assert "underlying server error" in captured.err


def test_stop_server_gracefully_stops_debug_subprocess():
    from psynet.command_line import _stop_server

    process = Mock()
    process.isalive.return_value = True
    process.expect_exact.return_value = None
    log_file = Mock()

    server_info = {
        "process": process,
        "tmp_log_path": "/tmp/psynet_server_test.log",
        "log_file": log_file,
    }

    with patch("psynet.command_line.kill_psynet_worker_processes") as kill_workers:
        _stop_server(server_info)

    process.sendcontrol.assert_called_once_with("c")
    process.expect_exact.assert_called()
    process.close.assert_called_once()
    log_file.close.assert_called_once()
    kill_workers.assert_called_once()


def test_stop_local_debug_process_reaps_workers_even_if_terminate_fails():
    from psynet.command_line import stop_local_debug_process

    process = Mock()

    with (
        patch(
            "psynet.command_line._terminate_server_process",
            side_effect=RuntimeError("boom"),
        ) as terminate,
        patch("psynet.command_line.kill_psynet_worker_processes") as kill_workers,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            stop_local_debug_process(process)

    terminate.assert_called_once_with(process)
    kill_workers.assert_called_once()


def test_terminate_server_process_escalates_when_sendcontrol_raises_oserror():
    from psynet.command_line import _terminate_server_process

    process = Mock()
    process.isalive.return_value = True
    process.pid = 12345
    process.sendcontrol.side_effect = OSError("PTY already gone")
    process.expect_exact.side_effect = [None]  # SIGTERM wait succeeds

    with (
        patch("psynet.command_line.os.getpgid", return_value=12345),
        patch("psynet.command_line.os.killpg") as killpg,
    ):
        _terminate_server_process(process)

    process.sendcontrol.assert_called_once_with("c")
    killpg.assert_called()
    process.close.assert_called_once_with(force=True)


def test_load_runtime_server_config_loads_generated_config():
    from psynet.command_line import _load_runtime_server_config

    config = Mock()
    config.ready = True

    with patch(
        "psynet.command_line.redis_vars.get",
        return_value="/tmp/dallinger_develop/exp",
    ):
        _load_runtime_server_config(config)

    config.load.assert_not_called()
    config.load_from_file.assert_called_once_with(
        "/tmp/dallinger_develop/exp/config.txt"
    )


def test_load_runtime_server_config_loads_launch_info_when_runtime_dir_is_missing(
    tmp_path, monkeypatch
):
    from psynet.command_line import _load_runtime_server_config

    deployment_id = "timeline-demo__mode=debug__launch=test"
    launch_info_dir = tmp_path / "psynet-data" / "launch-data" / deployment_id
    launch_info_dir.mkdir(parents=True)
    (launch_info_dir / "launch-info.json").write_text(
        json.dumps(
            {
                "dashboard_user": "admin",
                "dashboard_password": "generated-password",
            }
        ),
        encoding="utf-8",
    )

    config = Mock()
    config.ready = True
    monkeypatch.setenv("HOME", str(tmp_path))

    with patch("psynet.command_line.redis_vars.get", return_value=None):
        _load_runtime_server_config(config, deployment_id=deployment_id)

    config.load.assert_not_called()
    config.load_from_file.assert_not_called()
    config.extend.assert_called_once_with(
        {
            "dashboard_user": "admin",
            "dashboard_password": "generated-password",
        }
    )


def test_export_local_uses_runtime_dashboard_credentials(tmp_path, monkeypatch):
    from psynet.command_line import export_

    deployment_id = "timeline-demo__mode=debug__launch=test"
    launch_info_dir = tmp_path / "psynet-data" / "launch-data" / deployment_id
    launch_info_dir.mkdir(parents=True)
    (launch_info_dir / "launch-info.json").write_text(
        json.dumps(
            {
                "dashboard_user": "admin",
                "dashboard_password": "generated-password",
            }
        ),
        encoding="utf-8",
    )

    config = Mock()
    config.ready = True
    config.values = {}

    def get_config_value(key, default=None):
        if key in config.values:
            return config.values[key]
        if key == "base_port":
            return 5000
        if default is not None:
            return default
        raise KeyError(key)

    def extend_config(values):
        config.values.update(values)

    data_zip = io.BytesIO()
    with zipfile.ZipFile(data_zip, "w"):
        pass
    data_response = Mock(status_code=200, reason="OK", content=data_zip.getvalue())
    source_response = Mock(status_code=200, reason="OK", content=b"source-code")
    experiment_class = Mock(label="Timeline demo")
    experiment_class.export_path.return_value = str(tmp_path)
    config.extend.side_effect = extend_config
    config.get.side_effect = get_config_value
    monkeypatch.setenv("HOME", str(tmp_path))

    with (
        patch(
            "psynet.experiment.import_local_experiment",
            return_value={"class": experiment_class},
        ),
        patch("psynet.command_line.get_config", return_value=config),
        patch("psynet.command_line.redis_vars.get", return_value=None),
        patch(
            "psynet.command_line.get_experiment_url",
            side_effect=KeyError,
        ),
        patch(
            "psynet.command_line.requests.get",
            side_effect=[data_response, source_response],
        ) as request_get,
    ):
        export_(
            ctx=Mock(),
            exp_variables={
                "deployment_id": deployment_id,
                "label": "Timeline demo",
            },
            local=True,
            path=str(tmp_path),
            no_source=False,
            assets="experiment",
            anonymize="no",
        )

    config.extend.assert_called_once_with(
        {
            "dashboard_user": "admin",
            "dashboard_password": "generated-password",
        }
    )
    assert request_get.call_count == 2
    data_request, source_request = request_get.call_args_list
    assert data_request.args[0].startswith(
        "http://127.0.0.1:5000/dashboard/export/download?"
    )
    assert data_request.kwargs["auth"] == ("admin", "generated-password")
    assert source_request.args[0] == "http://127.0.0.1:5000/download_source"
    assert source_request.kwargs["auth"] == ("admin", "generated-password")


def test_run_performance_test_with_new_server_loads_runtime_server_config():
    from psynet.command_line import _run_performance_test_with_new_server

    process = Mock()
    server_info = {
        "process": process,
        "tmp_log_path": "/tmp/psynet_server_test.log",
        "log_file": Mock(),
    }

    with (
        patch(
            "psynet.command_line._start_local_server_and_wait_for_ready",
            return_value=server_info,
        ) as start_server,
        patch("psynet.command_line._load_runtime_server_config") as load_runtime_config,
        patch("psynet.command_line._run_performance_test_with_existing_server"),
        patch("psynet.command_line._stop_server"),
    ):
        _run_performance_test_with_new_server(
            n_bots="2", stagger=0.1, time_factor=1.0, duration_minutes=0.5, debug=False
        )

    start_server.assert_called_once_with(
        ["debug", "local", "--legacy", "--no-browsers"],
        debug=False,
    )
    load_runtime_config.assert_called_once_with()


def test_performance_test_preserves_explicit_zero_options():
    from psynet.command_line import _run_performance_test_with_existing_server

    experiment = Mock(
        authenticated_session=Mock(),
        base_url="http://localhost",
        label="test",
        test_n_bots=3,
        test_duration_minutes=2.0,
        test_parallel_stagger_interval_s=0.5,
        test_time_factor=2.5,
    )
    tester = Mock()
    tester.run.return_value = []
    bot_log_file = Mock(name="/tmp/psynet_bots_test.log")

    with (
        patch("logging.getLogger", return_value=Mock(handlers=[])),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch(
            "psynet.perf_test.PerformanceTester", return_value=tester
        ) as performance_tester,
        patch(
            "psynet.command_line.tempfile.NamedTemporaryFile",
            return_value=bot_log_file,
        ),
    ):
        _run_performance_test_with_existing_server(
            n_bots="1",
            stagger=0,
            time_factor=0,
            duration_minutes=0,
            debug=False,
        )

    performance_tester.assert_called_once_with(
        authenticated_session=experiment.authenticated_session,
        base_url=experiment.base_url,
        n_bots=experiment.test_n_bots,
        duration_minutes=0,
        stagger_interval_s=0.0,
        time_factor=0,
    )


def test_performance_test_uses_defaults_when_options_omitted():
    from psynet.command_line import _run_performance_test_with_existing_server

    experiment = Mock(
        authenticated_session=Mock(),
        base_url="http://localhost",
        label="test",
        test_n_bots=3,
        test_duration_minutes=2.0,
        test_parallel_stagger_interval_s=0.5,
        test_time_factor=2.5,
    )
    tester = Mock()
    tester.run.return_value = []
    bot_log_file = Mock(name="/tmp/psynet_bots_test.log")

    with (
        patch("logging.getLogger", return_value=Mock(handlers=[])),
        patch("psynet.experiment.get_experiment", return_value=experiment),
        patch(
            "psynet.perf_test.PerformanceTester", return_value=tester
        ) as performance_tester,
        patch(
            "psynet.command_line.tempfile.NamedTemporaryFile",
            return_value=bot_log_file,
        ),
    ):
        _run_performance_test_with_existing_server(
            n_bots=None,
            stagger=None,
            time_factor=None,
            duration_minutes=None,
            debug=False,
        )

    performance_tester.assert_called_once_with(
        authenticated_session=experiment.authenticated_session,
        base_url=experiment.base_url,
        n_bots=experiment.test_n_bots,
        duration_minutes=2.0,
        stagger_interval_s=0.5,
        time_factor=1.0,
    )


def test_ssh_performance_test_command_forwards_zero_valued_options():
    from psynet.command_line import _build_ssh_performance_test_cmd

    assert _build_ssh_performance_test_cmd(
        n_bots="5",
        stagger=0,
        time_factor=0,
        duration_minutes=0,
    ) == (
        "psynet performance-test local --existing "
        "--n-bots 5 --stagger 0 --time-factor 0 --duration-minutes 0"
    )


def test_ssh_performance_test_command_omits_unspecified_options():
    from psynet.command_line import _build_ssh_performance_test_cmd

    assert (
        _build_ssh_performance_test_cmd(
            n_bots=None,
            stagger=None,
            time_factor=None,
            duration_minutes=None,
        )
        == "psynet performance-test local --existing"
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (True, True),
        (False, False),
        (42, 42),
        ("hello", "hello"),
        (3.14, 3.14),
        (0.0, 0.0),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        (Decimal("1.5"), 1.5),
        (datetime(2025, 5, 7, 12, 30, 45), "2025-05-07T12:30:45"),
        (date(2025, 5, 7), "2025-05-07"),
        ((1, 2, 3), [1, 2, 3]),
    ],
)
def test_to_json_safe_scalars_and_simple_collections(value, expected):
    from psynet.perf_test import _to_json_safe

    assert _to_json_safe(value) == expected


def test_to_json_safe_decimal_returns_float_type():
    # `Decimal == float` compares by value; pin the type explicitly.
    from psynet.perf_test import _to_json_safe

    assert isinstance(_to_json_safe(Decimal("1.5")), float)


def test_to_json_safe_set_and_frozenset_are_sorted_lists():
    # Output must be deterministic so repeated runs produce identical JSON
    # (otherwise git diffs of stored results are noisy).
    from psynet.perf_test import _to_json_safe

    assert _to_json_safe({3, 1, 2}) == [1, 2, 3]
    assert _to_json_safe(frozenset({"b", "a", "c"})) == ["a", "b", "c"]


def test_to_json_safe_mixed_type_set_falls_back_to_unsorted_list():
    # Heterogeneous sets aren't sortable across types; the helper must still
    # return a list rather than raising.
    from psynet.perf_test import _to_json_safe

    result = _to_json_safe({1, "a", None})
    assert isinstance(result, list)
    assert set(result) == {1, "a", None}


def test_to_json_safe_recurses_through_nested_dict_and_list():
    from psynet.perf_test import _to_json_safe

    nested = {
        "rows": [
            {"value": Decimal("0.5"), "missing": float("nan")},
            {"value": Decimal("0.75"), "missing": None},
        ],
    }
    assert _to_json_safe(nested) == {
        "rows": [
            {"value": 0.5, "missing": None},
            {"value": 0.75, "missing": None},
        ],
    }


def test_collect_run_metadata_includes_environment_fields():
    from psynet.command_line import _collect_run_metadata

    metadata = _collect_run_metadata("my-experiment")
    assert metadata["experiment_label"] == "my-experiment"
    for key in ("psynet_version", "dallinger_version", "python_version", "platform"):
        assert isinstance(metadata[key], str) and metadata[key]


def test_write_json_results_emits_expected_schema_with_coerced_values(tmp_path):
    from psynet.command_line import _write_json_results

    json_output = str(tmp_path / "results.json")
    metadata = {
        "psynet_version": "13.2.0a0",
        "dallinger_version": "12.2.0",
        "python_version": "3.13.9",
        "platform": "Linux-test",
        "experiment_label": "static_big",
        "started_at": "2026-05-07T14:23:11",
        "finished_at": "2026-05-07T14:25:42",
    }
    options = {
        "n_bots_sweep": [1, 2],
        "duration_minutes": 1.5,
        "stagger_interval_s": 0.1,
        "time_factor": 1.0,
    }
    all_results = [
        {
            "n_bots": 1,
            "avg_latency": Decimal("0.5"),
            "nan_value": float("nan"),
            "inf_value": float("inf"),
            "process_stats": [{"avg": Decimal("0.001"), "max": float("nan")}],
        },
        {"n_bots": 2, "avg_latency": Decimal("0.6")},
    ]

    _write_json_results(
        json_output, metadata=metadata, options=options, all_results=all_results
    )

    with open(json_output) as f:
        payload = json.load(f)

    assert payload["schema_version"] == 1
    for key, expected in metadata.items():
        assert payload[key] == expected
    assert payload["options"] == options
    assert len(payload["results"]) == 2

    first = payload["results"][0]
    assert first["avg_latency"] == 0.5
    assert first["nan_value"] is None
    assert first["inf_value"] is None
    assert first["process_stats"][0]["avg"] == 0.001
    assert first["process_stats"][0]["max"] is None
