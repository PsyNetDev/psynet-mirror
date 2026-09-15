"""Validate scaffold prompts and round trips on representative demos."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from psynet.experiment_scaffold import (
    missing_scaffold_paths_required_for_local_run,
    prune_experiment_scaffold,
    scaffold_experiment_directory,
    scaffold_managed_paths,
    scaffold_missing_files,
)
from psynet.pytest_psynet import (
    local_only,
    path_to_demo_experiment,
    path_to_demo_feature,
)
from psynet.utils import get_psynet_root, working_directory

ROUNDTRIP_DEMOS = [
    ("experiments/hello_world", Path(path_to_demo_experiment("hello_world"))),
    ("features/api", Path(path_to_demo_feature("api"))),
    ("experiments/vocabulary_test", Path(path_to_demo_experiment("vocabulary_test"))),
]

RUNTIME_DEMOS = [
    ("experiments/hello_world", Path(path_to_demo_experiment("hello_world"))),
    ("features/api", Path(path_to_demo_feature("api"))),
]

SCAFFOLD_MANAGED_PATHS = {
    Path(relative_path)
    for relative_path in scaffold_managed_paths()
    if relative_path != "README.md"
}
PRUNABLE_RESOURCE_PATHS = {Path("templates/.keep")}


def _tracked_experiment_dirs(tracked_paths):
    """Return relative experiment dirs from tracked ``experiment.py`` paths.

    Prefer git-tracked paths over filesystem globs so leftover virtualenvs under
    a demo (which contain packaged ``experiment.py`` files) are ignored.
    """
    return sorted(
        {
            Path(path).parent
            for path in tracked_paths
            if Path(path).name == "experiment.py"
        }
    )


def test_demo_sources_contain_only_authored_experiment_files():
    psynet_root = get_psynet_root()
    managed_paths = scaffold_managed_paths() - {"README.md"}
    tracked_paths = set(
        subprocess.check_output(
            ["git", "ls-files", "demos"],
            cwd=psynet_root,
            text=True,
        ).splitlines()
    )

    for relative_demo in _tracked_experiment_dirs(tracked_paths):
        demo = psynet_root / relative_demo
        assert (relative_demo / "constraints.txt").as_posix() not in tracked_paths
        assert (demo / "requirements.txt").read_text().splitlines()[0] == "psynet"
        for relative_path in managed_paths:
            tracked_path = (relative_demo / relative_path).as_posix()
            assert tracked_path not in tracked_paths, (
                f"{demo} tracks scaffold-managed path {relative_path}"
            )


def test_tracked_experiment_dirs_ignore_untracked_venv_paths():
    tracked = {
        "demos/experiments/timeline/experiment.py",
        "demos/experiments/timeline/requirements.txt",
    }
    assert _tracked_experiment_dirs(tracked) == [Path("demos/experiments/timeline")]
    # A filesystem-only venv path is never in git ls-files output.
    assert Path("demos/experiments/timeline/.venv/lib/dallinger") not in [
        Path(p).parent for p in tracked if Path(p).name == "experiment.py"
    ]


TEST_EXPERIMENT_TREE_PREFIXES = (
    "tests/experiments/",
    "tests/playwright/experiments/",
    "tests/deployment/",
)

# Custom config.txt files that remain tracked under test experiment trees.
# Stock configs are gitignored; add new customs with ``git add -f``.
TEST_EXPERIMENT_CUSTOM_CONFIGS = {
    "tests/experiments/async_processes/config.txt",
    "tests/playwright/experiments/adversarial_lifecycle/config.txt",
    "tests/playwright/experiments/broken_page_dependency/config.txt",
    "tests/playwright/experiments/broken_page_module/config.txt",
    "tests/playwright/experiments/deferred_page_scripts/config.txt",
    "tests/playwright/experiments/js_var_globals/config.txt",
    "tests/playwright/experiments/legacy_page_javascript/config.txt",
    "tests/playwright/experiments/media_download_progress/config.txt",
    "tests/playwright/experiments/same_session_page_update/config.txt",
    "tests/deployment/payment_flows_prolific/config.txt",
    "tests/deployment/audio_gibbs/config.txt",
}

AUTHORED_TEST_EXPERIMENT_FILENAMES = {
    "experiment.py",
    "requirements.txt",
    "utils.py",
    "local_helper.py",
    "test_imports.py",
    "debug.sh",
    "shell.sh",
    "lucid_recruitment_config.json",
    "qualification_prolific_en.json",
    "DEPLOYMENT_ID",
    "custom_synth.py",
    "pre_deployed_assets.csv",
}


def _is_authored_test_experiment_path(relative_path: str) -> bool:
    """Return whether a tracked path is an allowed authored test-experiment file."""
    if relative_path in TEST_EXPERIMENT_CUSTOM_CONFIGS:
        return True

    name = Path(relative_path).name
    parts = Path(relative_path).parts
    if name in AUTHORED_TEST_EXPERIMENT_FILENAMES:
        return True
    # Recruiter/deployment variants, e.g. experiment.py.prolific / config.txt.lucid.
    if name.startswith("experiment.py") or name.startswith("config.txt"):
        return True
    if name.endswith((".wav", ".csv")):
        return True
    if "templates" in parts and name.endswith(".html"):
        return True
    if "static" in parts and name.endswith((".js", ".css")):
        return True
    if "locales" in parts and name.endswith((".po", ".pot")):
        return True
    if "synth_files" in parts or "consents_cococo" in parts:
        return True
    return False


def test_test_experiment_sources_contain_only_authored_files():
    """Test experiments track authored files only, like minimal demos."""
    psynet_root = get_psynet_root()
    managed_paths = scaffold_managed_paths()
    tracked_paths = set(
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "tests/experiments",
                "tests/playwright/experiments",
                "tests/deployment",
            ],
            cwd=psynet_root,
            text=True,
        ).splitlines()
    )

    for relative_experiment in _tracked_experiment_dirs(tracked_paths):
        experiment = psynet_root / relative_experiment
        assert (relative_experiment / "constraints.txt").as_posix() not in tracked_paths
        assert (experiment / "requirements.txt").read_text().splitlines()[0] == "psynet"
        for relative_path in managed_paths:
            tracked_path = (relative_experiment / relative_path).as_posix()
            if (
                relative_path == "config.txt"
                and tracked_path in TEST_EXPERIMENT_CUSTOM_CONFIGS
            ):
                continue
            assert tracked_path not in tracked_paths, (
                f"{experiment} tracks scaffold-managed path {relative_path}"
            )

    for config_path in TEST_EXPERIMENT_CUSTOM_CONFIGS:
        assert config_path in tracked_paths, f"missing custom config {config_path}"

    for tracked_path in tracked_paths:
        if not tracked_path.startswith(TEST_EXPERIMENT_TREE_PREFIXES):
            continue
        assert _is_authored_test_experiment_path(tracked_path), (
            f"unexpected tracked path under test experiment: {tracked_path}"
        )


def test_test_experiment_stock_config_is_gitignored():
    """Stock config.txt under test trees is ignored; tracked customs stay tracked."""
    psynet_root = get_psynet_root()
    stock_configs = [
        "tests/experiments/static/config.txt",
        "tests/playwright/experiments/static/config.txt",
        "tests/deployment/example/config.txt",
    ]
    for relative_path in stock_configs:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", relative_path],
            cwd=psynet_root,
        )
        assert result.returncode == 0, f"{relative_path} should be gitignored"

    tracked_customs = set(
        subprocess.check_output(
            ["git", "ls-files", *TEST_EXPERIMENT_CUSTOM_CONFIGS],
            cwd=psynet_root,
            text=True,
        ).splitlines()
    )
    assert tracked_customs == TEST_EXPERIMENT_CUSTOM_CONFIGS


def test_vendored_consent_package_init_is_not_gitignored():
    """Deployment consent packages stay addable despite scaffold ``__init__.py`` ignores."""
    psynet_root = get_psynet_root()
    relative_path = "tests/deployment/audio_gibbs/consents_cococo/__init__.py"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", relative_path],
        cwd=psynet_root,
    )
    assert result.returncode == 1, (
        f"{relative_path} should not match scaffold ignore rules"
    )


def test_skipped_dependency_check_does_not_require_constraints(monkeypatch):
    from psynet.experiment import Experiment

    monkeypatch.setenv("SKIP_DEPENDENCY_CHECK", "1")
    Experiment.check_python_dependencies(object())


def test_bundled_demo_dependency_check_does_not_require_constraints(monkeypatch):
    from psynet.experiment import Experiment

    monkeypatch.delenv("SKIP_DEPENDENCY_CHECK", raising=False)
    monkeypatch.setattr("psynet.experiment.is_in_repo_experiment", lambda: True)
    Experiment.check_python_dependencies(object())


def test_bundled_demo_dependency_check_ignores_leftover_constraints(
    tmp_path, monkeypatch
):
    from psynet.experiment import Experiment

    monkeypatch.delenv("SKIP_DEPENDENCY_CHECK", raising=False)
    monkeypatch.setattr("psynet.experiment.is_in_repo_experiment", lambda: True)
    (tmp_path / "constraints.txt").write_text("some-package==1.0.0\n")
    with working_directory(tmp_path):
        Experiment.check_python_dependencies(object())


def test_in_experiment_directory_sets_skip_only_outside_repo(tmp_path, monkeypatch):
    """Temp experiment dirs without constraints still get SKIP_DEPENDENCY_CHECK."""
    import psynet.pytest_psynet as pytest_psynet

    config = "[Custom]\nvalue = true\n"
    dockerfile = "# Existing scaffold leftover\n"
    monkeypatch.delenv("SKIP_DEPENDENCY_CHECK", raising=False)
    monkeypatch.setattr(pytest_psynet.redis_vars, "clear", lambda: None)
    monkeypatch.setattr(pytest_psynet, "clean_sys_modules", lambda: None)
    monkeypatch.setattr(pytest_psynet, "clear_all_caches", lambda: None)
    pytest_psynet.loaded_experiment_directory = None

    experiment_dir = tmp_path / "temp_experiment"
    experiment_dir.mkdir()
    (experiment_dir / "experiment.py").write_text(
        "from psynet.experiment import Experiment\n\nclass Exp(Experiment):\n    pass\n"
    )
    (experiment_dir / "requirements.txt").write_text("psynet==10.1.0\n")
    (experiment_dir / "config.txt").write_text(config)
    (experiment_dir / "Dockerfile").write_text(dockerfile)

    fixture = pytest_psynet.in_experiment_directory
    generator = fixture.__wrapped__(str(experiment_dir))
    try:
        next(generator)
        assert os.environ.get("SKIP_DEPENDENCY_CHECK") == "1"
    finally:
        try:
            next(generator)
        except StopIteration:
            pass
        pytest_psynet.loaded_experiment_directory = None
        os.environ.pop("SKIP_DEPENDENCY_CHECK", None)

    assert (experiment_dir / "config.txt").read_text() == config
    assert (experiment_dir / "Dockerfile").read_text() == dockerfile
    assert not (experiment_dir / "test.py").exists()


def test_in_experiment_directory_sets_skip_for_in_repo(tmp_path, monkeypatch):
    """In-repo demos set SKIP_DEPENDENCY_CHECK so Dallinger won't invent constraints."""
    import psynet.pytest_psynet as pytest_psynet

    monkeypatch.delenv("SKIP_DEPENDENCY_CHECK", raising=False)
    monkeypatch.setattr(pytest_psynet.redis_vars, "clear", lambda: None)
    monkeypatch.setattr(pytest_psynet, "clean_sys_modules", lambda: None)
    monkeypatch.setattr(pytest_psynet, "clear_all_caches", lambda: None)
    monkeypatch.setattr(pytest_psynet, "is_in_repo_experiment", lambda: True)
    pytest_psynet.loaded_experiment_directory = None

    experiment_dir = tmp_path / "in_repo_experiment"
    experiment_dir.mkdir()
    (experiment_dir / "experiment.py").write_text("class Exp:\n    pass\n")
    (experiment_dir / "requirements.txt").write_text("psynet\n")

    fixture = pytest_psynet.in_experiment_directory
    generator = fixture.__wrapped__(str(experiment_dir))
    try:
        next(generator)
        assert os.environ.get("SKIP_DEPENDENCY_CHECK") == "1"
        assert (experiment_dir / "test.py").exists()
    finally:
        try:
            next(generator)
        except StopIteration:
            pass
        pytest_psynet.loaded_experiment_directory = None
        os.environ.pop("SKIP_DEPENDENCY_CHECK", None)

    # Teardown restores the authored-only tree.
    assert not (experiment_dir / "test.py").exists()
    assert not (experiment_dir / "Dockerfile").exists()
    assert "SKIP_DEPENDENCY_CHECK" not in os.environ


def test_scaffold_missing_files_restores_preexisting_tree(tmp_path):
    (tmp_path / "experiment.py").write_text("class Exp:\n    pass\n")
    (tmp_path / "requirements.txt").write_text("psynet\n")
    (tmp_path / "config.txt").write_text("[Custom]\nvalue = true\n")
    (tmp_path / "Dockerfile").write_text("# Existing scaffold leftover\n")
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "custom").write_text("# Custom helper\n")
    (tmp_path / "constraints.txt").write_text("# Existing constraints\n")

    with working_directory(tmp_path):
        with scaffold_missing_files():
            assert Path("test.py").exists()
            assert Path("docker/custom").exists()
            Path("static/assets").mkdir(parents=True)

    assert (tmp_path / "config.txt").read_text() == "[Custom]\nvalue = true\n"
    assert (tmp_path / "Dockerfile").read_text() == "# Existing scaffold leftover\n"
    assert (tmp_path / "docker" / "custom").read_text() == "# Custom helper\n"
    assert (tmp_path / "constraints.txt").read_text() == "# Existing constraints\n"
    assert not (tmp_path / "test.py").exists()
    assert not (tmp_path / "docker" / "run").exists()
    assert not (tmp_path / "static" / "assets").exists()


def test_prune_include_modified_keeps_git_files_and_removes_generated(tmp_path):
    demo = Path(path_to_demo_experiment("hello_world"))
    # scaffold_missing_files() restores the authored-only tree even if an
    # assertion below fails, so a failure cannot leave generated files behind in
    # the repository for later tests to trip over.
    with working_directory(demo), scaffold_missing_files():
        Path("constraints.txt").write_text("# leftover\n")
        Path("static").mkdir(exist_ok=True)
        assets = Path("static/assets")
        if assets.exists() or assets.is_symlink():
            if assets.is_dir() and not assets.is_symlink():
                shutil.rmtree(assets)
            else:
                assets.unlink()
        assets.symlink_to(tmp_path / "missing-assets")
        assert Path("test.py").exists()

        result = prune_experiment_scaffold(include_modified=True)

    assert "README.md" in result["preserved_tracked"]
    assert result["removed_assets"] is True
    assert result["removed_constraints"] is True
    assert not (demo / "test.py").exists()
    assert not (demo / "Dockerfile").exists()
    assert not (demo / "constraints.txt").exists()
    assert not (demo / "static" / "assets").exists()
    assert (demo / "experiment.py").exists()
    assert (demo / "README.md").exists()


def test_prune_include_modified_deletes_untracked_readme(tmp_path):
    experiment_dir = tmp_path / "standalone"
    experiment_dir.mkdir()
    with working_directory(experiment_dir):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet\n")
        scaffold_experiment_directory()
        Path("README.md").write_text("# Custom README\n")

        prune_experiment_scaffold(include_modified=True)

        assert not Path("README.md").exists()
        assert Path("experiment.py").exists()


def test_prune_preserves_custom_docker_helpers(tmp_path):
    experiment_dir = tmp_path / "standalone"
    experiment_dir.mkdir()
    with working_directory(experiment_dir):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet\n")
        Path("docker").mkdir()
        Path("docker/psynet").write_text("# Tracked helper\n")
        Path("docker/custom").write_text("# Tracked custom\n")
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
        scaffold_experiment_directory()

        result = prune_experiment_scaffold(include_modified=True)

    assert "docker" not in result["preserved_tracked"]
    assert (experiment_dir / "docker" / "psynet").read_text() == "# Tracked helper\n"
    assert (experiment_dir / "docker" / "custom").read_text() == "# Tracked custom\n"
    assert not (experiment_dir / "Dockerfile").exists()


def test_prune_without_git_repo_treats_paths_as_untracked(tmp_path):
    experiment_dir = tmp_path / "standalone"
    experiment_dir.mkdir()
    with working_directory(experiment_dir):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet\n")
        scaffold_experiment_directory()
        Path("README.md").write_text("# Custom README\n")
        Path("constraints.txt").write_text("# leftover\n")

        prune_experiment_scaffold(include_modified=True)

        assert not Path("README.md").exists()
        assert not Path("constraints.txt").exists()
        assert Path("experiment.py").exists()


def test_prune_include_tracked_deletes_tracked_readme(tmp_path):
    experiment_dir = tmp_path / "standalone"
    experiment_dir.mkdir()
    with working_directory(experiment_dir):
        Path("experiment.py").write_text("class Exp:\n    pass\n")
        Path("requirements.txt").write_text("psynet\n")
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
        scaffold_experiment_directory()
        Path("README.md").write_text("# Tracked README\n")

        prune_experiment_scaffold(include_modified=True, include_tracked=True)

        assert not Path("README.md").exists()
        assert Path("experiment.py").exists()


def _hash_file(path: Path) -> str:
    """Return a stable hash for one file in a temporary demo copy."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ignore_generated_static_assets(src: Path):
    """Ignore generated ``static/assets`` symlinks when copying a demo tree."""
    static_directory = (src / "static").resolve()

    def ignore_generated_paths(directory, names):
        if Path(directory).resolve() == static_directory and "assets" in names:
            return {"assets"}
        return set()

    return ignore_generated_paths


def _copy_demo_to_tmp(src: Path, tmp_path: Path, label: str, *, init_git=True) -> Path:
    """Copy a demo into a temporary directory for round-trip checks."""
    target = tmp_path / label.replace("/", "__")
    shutil.copytree(src, target, ignore=_ignore_generated_static_assets(src))
    if init_git:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "add", "-A"], cwd=target, check=True)
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
            cwd=target,
            check=True,
        )
    return target


def test_copy_demo_to_tmp_ignores_generated_static_assets(tmp_path):
    source = tmp_path / "source"
    static = source / "static"
    static.mkdir(parents=True)
    (source / "experiment.py").write_text("class Exp:\n    pass\n")
    (static / "assets").symlink_to(tmp_path / "missing-assets")
    copies = tmp_path / "copies"
    copies.mkdir()

    copied = _copy_demo_to_tmp(source, copies, "demo")

    assert (copied / "experiment.py").exists()
    assert not (copied / "static/assets").exists()
    assert not (copied / "static/assets").is_symlink()


def _run_command(args, cwd: Path, *, env_updates=None):
    """Run a subprocess in a demo directory and capture its output."""
    env = os.environ.copy()
    if env_updates:
        env.update(env_updates)
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )


def _test_local_after_policy_review(experiment_dir, env_updates=None):
    """Run ``psynet test local`` through the one-shot deploy.toml review pause.

    Scaffolding an experiment leaves a policy-review marker, so the first launch
    stops and asks the author to inspect the deployment plan. Automation reruns
    the command, which is what an author does after reviewing.
    """
    command = ["psynet", "test", "local"]
    first = _run_command(command, experiment_dir, env_updates=env_updates)
    if first.returncode == 0:
        return first
    combined = first.stdout + first.stderr
    assert "created a new deploy.toml" in combined, combined
    return _run_command(command, experiment_dir, env_updates=env_updates)


def test_empty_directory_scaffold_git_init_and_test_local(tmp_path):
    """Standalone Workflow A: empty dir → scaffold → git init → test local."""
    experiment_dir = tmp_path / "my_experiment"
    experiment_dir.mkdir()

    scaffold = _run_command(
        ["psynet", "scripts", "scaffold", "--skip-constraints"],
        experiment_dir,
    )
    assert scaffold.returncode == 0, scaffold.stdout + scaffold.stderr
    assert (experiment_dir / "experiment.py").exists()
    assert (experiment_dir / "config.txt").exists()
    assert (experiment_dir / "requirements.txt").exists()

    # Constraints are produced by setup / generate-constraints in real use; stub
    # them here so the e2e focuses on scaffold + git + test orchestration.
    (experiment_dir / "constraints.txt").write_text("# Test-only dependency metadata\n")
    assert not missing_scaffold_paths_required_for_local_run(experiment_dir)

    git_init = _run_command(["git", "init", "-q"], experiment_dir)
    assert git_init.returncode == 0, git_init.stderr

    first = _run_command(
        ["psynet", "test", "local"],
        experiment_dir,
        env_updates={"SKIP_DEPENDENCY_CHECK": "1"},
    )
    assert first.returncode != 0, first.stdout + first.stderr
    assert "created a new deploy.toml" in first.stdout + first.stderr

    result = _run_command(
        ["psynet", "test", "local"],
        experiment_dir,
        env_updates={"SKIP_DEPENDENCY_CHECK": "1"},
    )
    assert result.returncode == 0, (
        "Empty-directory Workflow A failed on rerun after policy review\n"
        f"FIRST STDOUT:\n{first.stdout}\n"
        f"FIRST STDERR:\n{first.stderr}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "passed" in result.stdout.lower()


def _preserved_snapshot(root: Path) -> dict[str, str]:
    """Capture hashes for files that should survive scaffold pruning unchanged."""
    snapshot = {}
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(root)
        # ``.deploy/`` holds generated local state (deployment records, policy
        # review marker), not authored experiment files.
        if relative_path.parts[0] in {".git", ".deploy"}:
            continue
        if relative_path in PRUNABLE_RESOURCE_PATHS:
            continue
        if any(
            relative_path == managed_path or managed_path in relative_path.parents
            for managed_path in SCAFFOLD_MANAGED_PATHS
        ):
            continue

        snapshot[relative_path.as_posix()] = _hash_file(file_path)
    return snapshot


def test_minimal_demo_prompts_for_scaffold_before_debug(tmp_path):
    demo_path = _copy_demo_to_tmp(
        Path(path_to_demo_feature("api")), tmp_path, "features/api"
    )
    with working_directory(demo_path):
        prune_experiment_scaffold(include_modified=True)

    result = _run_command(
        ["psynet", "debug", "local", "--legacy", "--no-browsers"], demo_path
    )

    assert result.returncode != 0
    combined_output = result.stdout + result.stderr
    assert "Run 'psynet setup'" in combined_output
    assert "required PsyNet boilerplate files" in combined_output
    assert "touch config.txt" in combined_output
    for required_path in (
        ".gitignore",
        ".python-version",
        "config.txt",
        "Dockerfile",
        "test.py",
    ):
        assert required_path in combined_output


def test_relative_imports_work_in_minimal_demo_without_init_py(tmp_path):
    demo_path = _copy_demo_to_tmp(
        Path(path_to_demo_feature("api")), tmp_path, "features/api"
    )
    with working_directory(demo_path):
        prune_experiment_scaffold(include_modified=True)

    assert not (demo_path / "__init__.py").exists()

    result = _run_command(
        [
            "python",
            "-c",
            (
                "from psynet.experiment import import_local_experiment; "
                "exp = import_local_experiment()['class'](); "
                "print(exp.__class__.__name__)"
            ),
        ],
        demo_path,
    )

    assert result.returncode == 0, result.stderr
    assert "Exp" in result.stdout


def test_scaffolded_copy_without_git_repo_prompts_for_git_init(tmp_path):
    source = Path(path_to_demo_feature("api"))
    # Ignore generated static/assets: in-repo demo runs in the same CI shard can
    # leave a dangling symlink that breaks a naive shutil.copytree.
    temp_demo = _copy_demo_to_tmp(source, tmp_path, "api_copy", init_git=False)

    with working_directory(temp_demo):
        scaffold_experiment_directory()
        Path("constraints.txt").write_text("# Test-only dependency metadata\n")

    result = _run_command(
        ["psynet", "debug", "local", "--legacy", "--no-browsers"], temp_demo
    )

    assert result.returncode != 0
    combined_output = result.stdout + result.stderr
    assert "git init" in combined_output
    assert "not a git repository" in combined_output


@pytest.mark.parametrize("label, demo_path", ROUNDTRIP_DEMOS)
def test_demo_roundtrip_preserves_authored_files(label, demo_path, tmp_path):
    temp_demo = _copy_demo_to_tmp(demo_path, tmp_path, label)
    original_snapshot = _preserved_snapshot(temp_demo)

    with working_directory(temp_demo):
        prune_experiment_scaffold(include_modified=True)

    assert _preserved_snapshot(temp_demo) == original_snapshot

    with working_directory(temp_demo):
        scaffold_experiment_directory()

    assert _preserved_snapshot(temp_demo) == original_snapshot

    for relative_path in scaffold_managed_paths():
        assert (temp_demo / relative_path).exists(), f"{label} missing {relative_path}"


@local_only
@pytest.mark.parametrize("label, demo_path", RUNTIME_DEMOS)
def test_demo_roundtrip_runs_local_test_command(label, demo_path, tmp_path):
    temp_demo = _copy_demo_to_tmp(demo_path, tmp_path, label)

    with working_directory(temp_demo):
        prune_experiment_scaffold(include_modified=True)

    scaffold_result = _run_command(["psynet", "scripts", "scaffold"], temp_demo)
    assert scaffold_result.returncode == 0, scaffold_result.stderr

    result = _test_local_after_policy_review(temp_demo)

    assert result.returncode == 0, (
        f"{label} failed after scaffold round-trip\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
