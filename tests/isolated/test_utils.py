import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from importlib.machinery import ModuleSpec
from math import isnan
from pathlib import Path
from unittest.mock import patch

import pytest

from psynet.pytest_psynet import path_to_demo_experiment
from psynet.timeline import Module
from psynet.utils import (
    DuplicateKeyError,
    ExperimentDirectoryNameError,
    check_todos_before_deployment,
    corr,
    ensure_experiment_directory_name_does_not_conflict,
    format_timedelta,
    generate_text_file,
    get_authenticated_session,
    get_folder_size_mb,
    get_installed_package_source_directory,
    get_locales_dir_from_path,
    get_package_name,
    get_package_source_directory,
    get_psynet_root,
    git_repository_available,
    is_in_repo_experiment,
    linspace,
    list_experiment_dirs,
    list_isolated_tests,
    logger,
    make_parents,
    md5_directory,
    merge_dicts,
    organize_by_key,
    pretty_format_seconds,
    psynet_source_prefixes,
    safe,
    working_directory,
)


def test_psynet_source_prefixes_is_package_directory():
    (prefix,) = psynet_source_prefixes()
    package_dir = Path(prefix)

    assert prefix.endswith(os.sep)
    assert package_dir.name == "psynet"
    assert (package_dir / "utils.py").is_file()
    assert not (package_dir / "demos").exists()


def test_is_in_repo_experiment(tmp_path):
    from psynet.pytest_psynet import path_to_test_experiment

    assert is_in_repo_experiment(path_to_demo_experiment("hello_world"))
    assert is_in_repo_experiment(
        path_to_demo_experiment("hello_world"), roots=("demos",)
    )
    assert is_in_repo_experiment(path_to_test_experiment("static"))
    assert not is_in_repo_experiment(
        path_to_test_experiment("static"), roots=("demos",)
    )
    assert is_in_repo_experiment(
        get_psynet_root() / "tests/playwright/experiments/adversarial_lifecycle"
    )
    (tmp_path / "experiment.py").touch()
    assert not is_in_repo_experiment(tmp_path)


def test_is_in_repo_experiment_finds_checkout_when_package_root_differs(
    tmp_path, monkeypatch
):
    """Wheel/ASV installs should still recognize demos under a source checkout."""
    checkout = tmp_path / "PsyNet"
    demo = checkout / "demos" / "experiments" / "demo"
    demo.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "psynet"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (demo / "experiment.py").write_text("class Exp: pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "psynet.light_utils.get_psynet_root",
        lambda: tmp_path / "site-packages",
    )
    assert is_in_repo_experiment(demo)
    assert not is_in_repo_experiment(demo, roots=("tests/experiments",))


def test_make_dirs():
    with tempfile.TemporaryDirectory() as tempdir:
        subdir = "abc123"
        path = os.path.join(tempdir, subdir, "test.txt")

        with pytest.raises(FileNotFoundError):
            with open(path, "w") as file:
                file.write("Test")

        with open(make_parents(path), "w") as file:
            file.write("Test")

        assert make_parents(path) == path


def test_generate_text_file_uses_custom_text(tmp_path):
    target = tmp_path / "custom.txt"

    generate_text_file(target, text="Custom contents")

    assert target.read_text() == "Custom contents"


def test_linspace():
    assert linspace(0, 5, 6) == [0, 1, 2, 3, 4, 5]
    assert linspace(-1, 1, 5) == [-1, -0.5, 0, 0.5, 1]
    assert linspace(2, 5, 1) == [2]


def test_merge_dicts():
    x = {"a": 1, "b": 2, "c": 3}
    y = {"b": 5, "c": 4, "d": 11}
    z = {"c": 10, "d": -5, "e": 5}

    assert merge_dicts(x, y, z, overwrite=True) == {
        "a": 1,
        "b": 5,
        "c": 10,
        "d": -5,
        "e": 5,
    }

    with pytest.raises(DuplicateKeyError):
        merge_dicts(x, y, z, overwrite=False)


def test_corr():
    x = [1, 5, 2, 6, 8]
    y = [2, 7, 3, 4, 5]
    assert corr(x, y) == pytest.approx(0.658647361238887)

    x = [1, 1]
    y = [1, 1]
    assert isnan(corr(x, y))


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=1), "1 second"),
        (timedelta(seconds=0), "0 seconds"),
        (timedelta(seconds=-1), "-1 second"),
        (timedelta(minutes=1), "1 minute"),
        (timedelta(minutes=2, seconds=5), "2 minutes, 5 seconds"),
        (timedelta(hours=1), "1 hour"),
        (timedelta(hours=3, minutes=2), "3 hours, 2 minutes"),
        (timedelta(days=1), "1 day"),
        (timedelta(days=1, hours=1), "1 day, 1 hour"),
        (timedelta(hours=-2, minutes=-5), "-2 hours, 5 minutes"),
    ],
)
def test_format_timedelta(delta, expected):
    assert format_timedelta(delta) == expected


def test_pretty_format_seconds_rounding():
    assert pretty_format_seconds(59.6) == "1 min"
    assert pretty_format_seconds(59.4) == "0 min 59 sec"


@patch("psynet.timeline.Module.started_and_finished_times")
def test_median_finish_time_in_s(mock_started_and_finished_times):
    started_and_finished_times = [
        {
            "time_started": get_datetime("2020-08-26 22:34:58.333641"),
            "time_finished": get_datetime("2020-08-26 22:35:16.742562"),
        },
        {
            "time_started": get_datetime("2020-08-26 22:35:16.742562"),
            "time_finished": get_datetime("2020-08-26 22:37:35.132272"),
        },
        {
            "time_started": get_datetime("2020-08-26 22:36:22.188457"),
            "time_finished": get_datetime("2020-08-26 22:37:51.007836"),
        },
        {
            "time_started": get_datetime("2020-08-26 22:37:21.643429"),
            "time_finished": get_datetime("2020-08-26 23:59:28.508135"),
        },
    ]
    mock_started_and_finished_times.return_value = started_and_finished_times
    assert Module.median_finish_time_in_s("participants", "module_id") == 113.6045445


@patch("psynet.timeline.Module.started_and_finished_times")
def test_median_finish_time_in_s_incomplete_none(mock_started_and_finished_times):
    started_and_finished_times = [
        {
            "time_started": get_datetime("2020-08-26 22:34:58.333641"),
            "time_finished": None,
        }
    ]
    mock_started_and_finished_times.return_value = started_and_finished_times
    assert Module.median_finish_time_in_s("participants", "module_id") is None


@patch("psynet.timeline.Module.started_and_finished_times")
def test_median_finish_time_in_s_incomplete_blank(mock_started_and_finished_times):
    started_and_finished_times = [
        {
            "time_started": get_datetime("2020-08-26 22:34:58.333641"),
            "time_finished": "",
        }
    ]
    mock_started_and_finished_times.return_value = started_and_finished_times
    assert Module.median_finish_time_in_s("participants", "module_id") is None


@patch("psynet.timeline.Module.started_and_finished_times")
def test_median_finish_time_in_s_incomplete_empty(mock_started_and_finished_times):
    mock_started_and_finished_times.return_value = []
    assert (
        Module.median_finish_time_in_s("started_and_finished_times", "module_id")
        is None
    )


def test_organize_by_key():
    assert organize_by_key(
        [["a", 3], ["b", 7], ["a", 1], ["b", 9]],
        key=lambda x: x[0],
    ) == {
        "a": [["a", 3], ["a", 1]],
        "b": [["b", 7], ["b", 9]],
    }


def get_datetime(str):
    return datetime.strptime(str, "%Y-%m-%d %H:%M:%S.%f")


def test_demo_dirs():
    psynet_root = get_psynet_root()
    dirs = list_experiment_dirs()
    assert psynet_root.joinpath("demos/experiments/mcmcp").__str__() in dirs
    assert (
        psynet_root.joinpath("tests/experiments/recruiters/lab_recruiter").__str__()
        in dirs
    )
    assert (
        psynet_root.joinpath("tests/deployment/payment_flows_prolific").__str__()
        in dirs
    )
    assert (
        psynet_root.joinpath(
            "tests/playwright/experiments/adversarial_lifecycle"
        ).__str__()
        in dirs
    )

    dirs = list_experiment_dirs(for_ci_tests=True)
    assert psynet_root.joinpath("demos/experiments/mcmcp").__str__() in dirs
    assert (
        psynet_root.joinpath("tests/experiments/recruiters/lab_recruiter").__str__()
        not in dirs
    )
    assert (
        psynet_root.joinpath("tests/deployment/payment_flows_prolific").__str__()
        not in dirs
    )
    assert (
        psynet_root.joinpath(
            "tests/playwright/experiments/adversarial_lifecycle"
        ).__str__()
        not in dirs
    )


def test_list_experiment_dirs_skips_hidden_venv_trees(tmp_path, monkeypatch):
    """Leftover .venv trees must not be treated as experiment directories."""
    demos = tmp_path / "demos" / "experiments"
    real_demo = demos / "timeline"
    real_demo.mkdir(parents=True)
    (real_demo / "experiment.py").write_text("class Exp: pass\n")

    venv_experiment = (
        real_demo
        / ".venv-psynet-3.13"
        / "lib"
        / "python3.13"
        / "site-packages"
        / "dallinger"
    )
    venv_experiment.mkdir(parents=True)
    (venv_experiment / "experiment.py").write_text("# packaged dallinger\n")

    monkeypatch.setattr("psynet.utils.get_psynet_root", lambda: tmp_path)
    monkeypatch.setattr("psynet.utils._IN_REPO_EXPERIMENT_ROOTS", ("demos",))

    dirs = list_experiment_dirs()
    assert str(real_demo) in dirs
    assert str(venv_experiment) not in dirs
    assert all("/.venv" not in path for path in dirs)


def test_isolated_tests():
    psynet_root = get_psynet_root()
    tests = list_isolated_tests()

    assert (
        psynet_root.joinpath(
            "tests/isolated/experiments/test_experiment_timeline.py"
        ).__str__()
        in tests
    )


def test_check_todos_before_deployment_raise():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("file1.py", "w") as file:
                file.write("# TODO (1) line with a Python comment")
                file.flush()

            with open("file2.py", "w") as file:
                file.write("# TODO (2) line with a Python comment\n")
                file.write("// TODO (3) line with a JavaScript comment")
                file.flush()

            os.mkdir("subdir")
            with open("subdir/file.js", "w") as file:
                file.write("// TODO (4) line with a JavaScript comment\n")
                file.write("// TODO (5) line with a second JavaScript comment")
                file.flush()

            with open("subdir/file.html", "w") as file:
                file.write("// TODO (6) line with a JavaScript comment")
                file.flush()

            with pytest.raises(
                AssertionError,
                match="You have 6 TODOs in 4 file\\(s\\) in your experiment folder. "
                "Please fix them or remove them before deploying. To view all "
                "TODOs in your project in PyCharm, go to 'View' > 'Tool Windows' > 'TODO'. "
                "You can skip this check by writing `export SKIP_TODO_CHECK=1` "
                "\\(without quotes\\) in your terminal.",
            ):
                check_todos_before_deployment()


def test_check_todos_before_deployment_no_raise():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("no_raise.py", "w") as file:
                file.write("# FIXME line with unrecognized")
                file.flush()

            with open("no_raise.txt", "w") as file:
                file.write("# TODO line in a file with unsupported file extension")
                file.flush()

            try:
                check_todos_before_deployment()
            except AssertionError:
                assert False


def test_check_todos_before_deployment_skips_venv_and_bad_encoding():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            os.makedirs("venv/lib", exist_ok=True)
            with open("venv/lib/ignored.py", "w") as file:
                file.write("# TODO should be ignored")
                file.flush()

            with open("bad_encoding.py", "wb") as file:
                file.write(b"\xb1\xff")
                file.flush()

            try:
                check_todos_before_deployment()
            except AssertionError:
                assert False


def test_get_folder_size_mb():
    with tempfile.TemporaryDirectory() as tempdir:
        subdir = os.path.join(tempdir, "subdir")
        os.mkdir(subdir)

        file1_path = os.path.join(tempdir, "file1.txt")
        file2_path = os.path.join(subdir, "file2.txt")

        with open(file1_path, "w") as file1:
            file1.write("a" * 1024 * 1024)  # 1 MB

        with open(file2_path, "w") as file2:
            file2.write("b" * 512 * 1024)  # 0.5 MB

        assert get_folder_size_mb(tempdir) == pytest.approx(1.5, rel=1e-2)
        assert get_folder_size_mb(subdir) == pytest.approx(0.5, rel=1e-2)


@pytest.fixture
def temp_package_dir():
    with tempfile.TemporaryDirectory() as tempdir:
        with working_directory(tempdir):
            yield tempdir


@pytest.fixture
def pyproject_package(temp_package_dir):
    with open("pyproject.toml", "w") as f:
        f.write(
            """
[project]
name = "test-package"
"""
        )
    return "test-package"


@pytest.fixture
def setup_package(temp_package_dir):
    with open("setup.py", "w") as f:
        f.write(
            """
from setuptools import setup

setup(
    name="test-package",
    version="0.1",
)
"""
        )
    return "test-package"


def test_get_package_name_from_pyproject(pyproject_package):
    assert get_package_name() == pyproject_package


def test_get_package_name_from_setup(setup_package):
    assert get_package_name() == setup_package


def test_get_package_name_from_path(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "temp-package"
"""
    )
    with working_directory(get_psynet_root()):
        assert get_package_name(tmp_path) == "temp-package"


def test_get_psynet_package_name():
    psynet_root = get_psynet_root()
    with working_directory(psynet_root):
        assert get_package_name() == "psynet"


def test_get_psynet_package_source_directory():
    """
    Test that get_package_source_directory works correctly for the psynet package.
    """
    psynet_root = get_psynet_root()
    with working_directory(psynet_root):
        source_dir = get_package_source_directory()
        assert source_dir == "psynet"
        assert os.path.isdir(source_dir)


def test_experiment_directory_name_rejects_non_package_module(tmp_path):
    experiment_directory = tmp_path / "code"
    experiment_directory.mkdir()
    (experiment_directory / "experiment.py").write_text("")

    with pytest.raises(ExperimentDirectoryNameError, match="Python's module 'code'"):
        ensure_experiment_directory_name_does_not_conflict(experiment_directory)


def test_experiment_directory_name_rejects_conflict_without_experiment_py(tmp_path):
    experiment_directory = tmp_path / "code"
    experiment_directory.mkdir()

    with pytest.raises(ExperimentDirectoryNameError, match="Python's module 'code'"):
        ensure_experiment_directory_name_does_not_conflict(experiment_directory)


def test_experiment_directory_name_allows_package_resolution(tmp_path, monkeypatch):
    experiment_directory = tmp_path / "static"
    experiment_directory.mkdir()
    (experiment_directory / "experiment.py").write_text("")
    spec = ModuleSpec("static", loader=None, is_package=True)

    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: spec if name == "static" else None,
    )

    ensure_experiment_directory_name_does_not_conflict(experiment_directory)


def test_get_locales_dir_from_path_uses_given_path(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "test-package"
[tool.setuptools.packages.find]
where = ["src"]
"""
    )
    expected = tmp_path / "src" / "locales"

    with working_directory(get_psynet_root()):
        locales_dir = get_locales_dir_from_path(tmp_path)

    assert locales_dir == expected


def test_get_installed_package_source_directory_supports_namespace_packages(
    tmp_path, monkeypatch
):
    """Deployment copies may omit gitignored ``__init__.py`` files."""
    import sys
    import types

    package_root = tmp_path / "deployed_experiment"
    package_root.mkdir()
    (package_root / "locales").mkdir()

    package = types.ModuleType("dallinger_experiment")
    package.__path__ = [str(package_root)]
    monkeypatch.setitem(sys.modules, "dallinger_experiment", package)

    assert get_installed_package_source_directory("dallinger_experiment") == (
        package_root.resolve()
    )


def test_get_package_source_directory_setuptools_where_list(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "test-package"
[tool.setuptools.packages.find]
where = ["src"]
"""
    )
    assert Path(get_package_source_directory(tmp_path)) == tmp_path / "src"


def test_get_package_source_directory_respects_path(tmp_path):
    package_dir = tmp_path / "my_pkg"
    package_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "my_pkg"
"""
    )

    with working_directory(get_psynet_root()):
        source_dir = get_package_source_directory(tmp_path)

    assert Path(source_dir) == package_dir


# def test_get_package_name(temp_package_dir):
#     # Test with pyproject.toml
#     with open("pyproject.toml", "w") as f:
#         f.write("""
# [project]
# name = "test-package-1"
# """)
#     assert get_package_name() == "test-package-1"

#     # Test with setup.py
#     os.remove("pyproject.toml")
#     with open("setup.py", "w") as f:
#         f.write("""
# from setuptools import setup

# setup(
#     name="test-package-2",
#     version="0.1",
# )
# """)
#     assert get_package_name() == "test-package-2"

#     # Test with no config files
#     os.remove("setup.py")
#     with pytest.raises(FileNotFoundError, match="Could not find pyproject.toml or setup.py in current directory"):
#         get_package_name()


def test_git_repository_available_true(tmp_path):
    # Create a temporary directory and initialize a git repo
    with working_directory(tmp_path):
        subprocess.run(["git", "init"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert git_repository_available() is True


def test_git_repository_available_false(tmp_path):
    # Use a fresh temporary directory with no git repo
    with working_directory(tmp_path):
        assert git_repository_available() is False


def test_git_command_available_matches_which(monkeypatch):
    from psynet.light_utils import git_command_available

    monkeypatch.setattr("psynet.light_utils.shutil.which", lambda name: "/usr/bin/git")
    assert git_command_available() is True
    monkeypatch.setattr("psynet.light_utils.shutil.which", lambda name: None)
    assert git_command_available() is False


def test_safe_decorator(caplog):
    @safe
    def no_error(x):
        return x * 2

    @safe
    def with_error(x):
        raise ValueError(f"bad value: {x}")

    # Normal case: should return correct value
    assert no_error(3) == 6

    # Exception case: should return None and log error
    with caplog.at_level(logging.ERROR, logger.name):
        result = with_error(5)
    assert result is None
    assert any(
        "Error in with_error: bad value: 5" in record.message
        and record.levelname == "ERROR"
        for record in caplog.records
    )
    # Should also include traceback
    assert any(
        "Traceback" in record.getMessage() or record.exc_info
        for record in caplog.records
    )


def test_safe_as_function_wrapper(caplog):
    def no_error(x):
        return x + 10

    def with_error(x):
        raise RuntimeError(f"fail: {x}")

    # Normal case
    assert safe(no_error)(5) == 15

    # Exception case
    with caplog.at_level(logging.ERROR, logger.name):
        result = safe(with_error)(7)
    assert result is None
    assert any(
        "Error in with_error: fail: 7" in record.message and record.levelname == "ERROR"
        for record in caplog.records
    )
    assert any(
        "Traceback" in record.getMessage() or record.exc_info
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("hello_world")], indirect=True
)
def test_get_authenticated_session_allows_dashboard_access(launched_experiment):
    """
    Test that get_authenticated_session allows access to a protected dashboard route.
    Uses the hello_world demo and the launched_experiment fixture.
    """
    base_url = launched_experiment.base_url
    session = get_authenticated_session(base_url)
    resp = session.get(f"{base_url}/dashboard/index")
    assert resp.status_code == 200
    assert "Config" in resp.text or "configuration" in resp.text


def test_md5_directory_ignores_hidden_files():
    """Test that md5_directory ignores hidden files and directories."""
    with tempfile.TemporaryDirectory() as tempdir:
        # Create a directory structure with visible and hidden files
        visible_file = os.path.join(tempdir, "visible.txt")
        hidden_file = os.path.join(tempdir, ".DS_Store")
        hidden_dir = os.path.join(tempdir, ".hidden_dir")
        visible_dir = os.path.join(tempdir, "visible_dir")
        visible_dir_file = os.path.join(visible_dir, "file.txt")

        with open(visible_file, "w") as f:
            f.write("visible content")

        with open(hidden_file, "w") as f:
            f.write("hidden content")

        os.makedirs(hidden_dir)
        with open(os.path.join(hidden_dir, "hidden_file.txt"), "w") as f:
            f.write("hidden dir content")

        os.makedirs(visible_dir)
        with open(visible_dir_file, "w") as f:
            f.write("visible dir content")

        # Get hash with hidden files
        hash_with_hidden = md5_directory(tempdir)

        # Modify hidden file - hash should remain the same
        with open(hidden_file, "w") as f:
            f.write("modified hidden content")

        hash_after_hidden_modification = md5_directory(tempdir)
        assert hash_with_hidden == hash_after_hidden_modification

        # Modify visible file - hash should change
        with open(visible_file, "w") as f:
            f.write("modified visible content")

        hash_after_visible_modification = md5_directory(tempdir)
        assert hash_with_hidden != hash_after_visible_modification

        # Add another hidden file - hash should remain the same
        with open(os.path.join(tempdir, ".another_hidden"), "w") as f:
            f.write("another hidden file")

        hash_after_adding_hidden = md5_directory(tempdir)
        assert hash_after_visible_modification == hash_after_adding_hidden

        # Add another visible file - hash should change
        with open(os.path.join(tempdir, "another_visible.txt"), "w") as f:
            f.write("another visible file")

        hash_after_adding_visible = md5_directory(tempdir)
        assert hash_after_visible_modification != hash_after_adding_visible


def test_md5_directory_consistency():
    """Test that md5_directory produces consistent hashes for identical directory contents."""
    with tempfile.TemporaryDirectory() as tempdir1:
        with tempfile.TemporaryDirectory() as tempdir2:
            # Create identical directory structures
            for tempdir in [tempdir1, tempdir2]:
                with open(os.path.join(tempdir, "file1.txt"), "w") as f:
                    f.write("content1")
                with open(os.path.join(tempdir, "file2.txt"), "w") as f:
                    f.write("content2")
                subdir = os.path.join(tempdir, "subdir")
                os.makedirs(subdir)
                with open(os.path.join(subdir, "file3.txt"), "w") as f:
                    f.write("content3")

            hash1 = md5_directory(tempdir1)
            hash2 = md5_directory(tempdir2)

            assert hash1 == hash2
            assert len(hash1) == 32  # MD5 hex digest is 32 characters
