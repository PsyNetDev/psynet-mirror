from benchmarks.fast.debug_launch import (
    _LEGACY_LOCAL_RUN_SCAFFOLD_PATHS,
    StaticFilesDebugLaunch,
    _local_run_scaffold_paths,
    _prepare_benchmark_experiment,
    _prepared_benchmark_experiment,
    _temporary_static_payload,
)
from psynet.experiment_scaffold import scaffold_paths_required_for_local_run


def test_temporary_static_payload_is_created_and_cleaned_up(tmp_path):
    with _temporary_static_payload(tmp_path, count=3, file_size=7) as payload_dir:
        files = list(payload_dir.iterdir())
        assert len(files) == 3
        assert {file.stat().st_size for file in files} == {7}

    assert not payload_dir.exists()
    assert not (tmp_path / "static").exists()


def test_temporary_static_payload_preserves_existing_static_files(tmp_path):
    sentinel = tmp_path / "static" / "asv-generated" / "sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep me")

    with _temporary_static_payload(tmp_path, count=1, file_size=1) as payload_dir:
        assert payload_dir != sentinel.parent
        assert sentinel.read_text() == "keep me"

    assert sentinel.read_text() == "keep me"


def test_temporary_static_payload_preserves_files_created_during_launch(tmp_path):
    with _temporary_static_payload(tmp_path, count=1, file_size=1):
        runtime_file = tmp_path / "static" / "assets" / "runtime.txt"
        runtime_file.parent.mkdir()
        runtime_file.write_text("keep me")

    assert runtime_file.read_text() == "keep me"


def test_local_run_scaffold_paths_match_scaffold_helper():
    """Benchmark prep must track the scaffold module's local-run path set."""
    assert _local_run_scaffold_paths() == scaffold_paths_required_for_local_run()
    assert _LEGACY_LOCAL_RUN_SCAFFOLD_PATHS == scaffold_paths_required_for_local_run()


def test_prepared_benchmark_experiment_restores_created_scaffold(tmp_path):
    repo_root = tmp_path / "repo"
    templates = repo_root / "psynet" / "resources" / "experiment_scripts"
    templates.mkdir(parents=True)
    (templates / "Dockerfile").write_text("FROM python:3.13\n")
    (templates / "config.txt").write_text("[Config]\n")
    (templates / "test.py").write_text("# test\n")
    (templates / ".gitignore").write_text("*.pyc\n")

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    (demo_dir / "experiment.py").write_text("class Exp:\n    pass\n")

    with _prepared_benchmark_experiment(demo_dir, repo_root) as created:
        assert created
        assert (demo_dir / "Dockerfile").exists()
        assert (demo_dir / "constraints.txt").exists()
        assert not (demo_dir / "docker").exists()

    assert not (demo_dir / "Dockerfile").exists()
    assert not (demo_dir / "constraints.txt").exists()
    assert not (demo_dir / "docker").exists()
    assert (demo_dir / "experiment.py").exists()


def test_prepare_benchmark_experiment_follows_scaffold_path_helper(
    tmp_path, monkeypatch
):
    """New local-run paths from scaffold are copied without editing the benchmark."""
    repo_root = tmp_path / "repo"
    templates = repo_root / "psynet" / "resources" / "experiment_scripts"
    templates.mkdir(parents=True)
    (templates / "Dockerfile").write_text("FROM template\n")
    (templates / "extra-required.txt").write_text("new\n")

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()

    monkeypatch.setattr(
        "benchmarks.fast.debug_launch._local_run_scaffold_paths",
        lambda: frozenset({"Dockerfile", "extra-required.txt"}),
    )

    created = _prepare_benchmark_experiment(demo_dir, repo_root)

    assert (demo_dir / "Dockerfile").read_text() == "FROM template\n"
    assert (demo_dir / "extra-required.txt").read_text() == "new\n"
    assert demo_dir / "Dockerfile" in created
    assert demo_dir / "extra-required.txt" in created


def test_prepare_benchmark_experiment_skips_existing_files(tmp_path):
    repo_root = tmp_path / "repo"
    templates = repo_root / "psynet" / "resources" / "experiment_scripts"
    templates.mkdir(parents=True)
    (templates / "Dockerfile").write_text("FROM template\n")

    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    (demo_dir / "Dockerfile").write_text("FROM existing\n")

    created = _prepare_benchmark_experiment(demo_dir, repo_root)

    assert (demo_dir / "Dockerfile").read_text() == "FROM existing\n"
    assert demo_dir / "Dockerfile" not in created


def test_static_files_debug_launch_tracks_each_profile():
    benchmark = StaticFilesDebugLaunch()
    results = {profile: index for index, profile in enumerate(benchmark.params)}

    for profile, expected in results.items():
        assert benchmark.track_launch_time_s(results, profile) == expected
