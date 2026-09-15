"""End-to-end benchmarks for local debug startup."""

import os
import random
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# These generated files are deliberately not used by the experiment itself.
# They represent bundled stimuli or other static resources that launch and
# deployment tooling must still scan, copy, and package; historically, large
# static trees made both local debugging and deployment substantially slower.
_STATIC_FILE_PROFILES = {
    "baseline": (0, 0),
    "many_small_files": (50_000, 1),
    "few_large_files": (25, 4 * 1024 * 1024),
}

# Used only when the installed PsyNet lacks scaffold_paths_required_for_local_run
# (ASV continuous can compare against older commits). Keep aligned with today's
# ``_TEMPLATE_FILES_REQUIRED_FOR_LOCAL_RUN``.
_LEGACY_LOCAL_RUN_SCAFFOLD_PATHS = frozenset(
    {
        ".gitignore",
        ".python-version",
        "Dockerfile",
        "config.txt",
        "deploy.toml",
        "test.py",
    }
)


@contextmanager
def _temporary_static_payload(experiment_dir, count, file_size):
    """Create deterministic static files for the duration of a benchmark."""
    static_dir = Path(experiment_dir) / "static"
    static_dir_existed = static_dir.exists()
    payload_dir = None

    try:
        if count:
            static_dir.mkdir(parents=True, exist_ok=True)
            payload_dir = Path(
                tempfile.mkdtemp(prefix="asv-generated-", dir=static_dir)
            )
            contents = random.Random(0).randbytes(file_size)
            for index in range(count):
                (payload_dir / f"file-{index:05d}.bin").write_bytes(contents)
        yield payload_dir
    finally:
        if payload_dir is not None:
            shutil.rmtree(payload_dir)
        if (
            not static_dir_existed
            and static_dir.exists()
            and not any(static_dir.iterdir())
        ):
            static_dir.rmdir()


@contextmanager
def _prepared_benchmark_experiment(demo_dir: Path, repo_root: Path):
    """Copy missing scaffold files for ASV, then restore the demo tree."""
    created_paths = _prepare_benchmark_experiment(demo_dir, repo_root)
    try:
        yield created_paths
    finally:
        _restore_benchmark_experiment(created_paths)


def _local_run_scaffold_paths() -> frozenset[str]:
    """Return scaffold paths required for local debug of the installed PsyNet.

    Prefer the installed package's public helper so ASV prep stays aligned with
    what ``psynet debug local`` checks. Fall back to a frozen legacy set when
    comparing against older commits that lack the helper.
    """
    try:
        from psynet.experiment_scaffold import scaffold_paths_required_for_local_run
    except ImportError:
        return _LEGACY_LOCAL_RUN_SCAFFOLD_PATHS
    return frozenset(scaffold_paths_required_for_local_run())


def _prepare_benchmark_experiment(demo_dir: Path, repo_root: Path) -> list[Path]:
    """Ensure pruned in-repo demos can launch under older PsyNet checkouts.

    ASV continuous installs each compared commit into its env, but runs
    benchmarks from the current tree. Older PsyNet versions always open
    ``constraints.txt`` during debug pre-checks, and pruned demos omit
    tracked scaffold files. Copy missing local-run templates from this
    checkout and write a stub constraints file when needed — without calling
    the ``psynet`` CLI, which may be an older build that lacks
    ``scripts scaffold``.

    Returns
    -------
    list of Path
        Paths created by this helper so callers can restore the tree.
    """
    templates = repo_root / "psynet" / "resources" / "experiment_scripts"
    created_paths: list[Path] = []

    for relative_path in sorted(_local_run_scaffold_paths()):
        destination = demo_dir / relative_path
        source = templates / relative_path
        if destination.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, destination)
            created_paths.append(destination)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            created_paths.append(destination)

    constraints_path = demo_dir / "constraints.txt"
    if not constraints_path.is_file():
        constraints_path.write_text(
            "# Generated for ASV debug-launch benchmarks.\n",
            encoding="utf-8",
        )
        created_paths.append(constraints_path)

    return created_paths


def _restore_benchmark_experiment(created_paths: list[Path]) -> None:
    """Remove scaffold files created by ``_prepare_benchmark_experiment``."""
    for path in reversed(created_paths):
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)


class StaticFilesDebugLaunch:
    """Benchmark debug launch with representative static-file payloads."""

    params = list(_STATIC_FILE_PROFILES)
    param_names = ["profile"]
    timeout = 180
    version = 2

    def setup_cache(self):
        """Launch the static_big experiment once for each file profile."""
        from psynet.command_line import (
            _start_local_server_and_wait_for_ready,
            _stop_server,
        )

        repo_root = Path(__file__).parents[2]
        demo_dir = repo_root / "tests/experiments/static_big"
        original_directory = Path.cwd()
        results = {}

        try:
            with _prepared_benchmark_experiment(demo_dir, repo_root):
                os.chdir(demo_dir)
                for profile, (count, file_size) in _STATIC_FILE_PROFILES.items():
                    server_info = None
                    with _temporary_static_payload(demo_dir, count, file_size):
                        started_at = time.perf_counter()
                        try:
                            server_info = _start_local_server_and_wait_for_ready(
                                ["debug", "local"]
                            )
                            results[profile] = time.perf_counter() - started_at
                        finally:
                            if server_info is not None:
                                _stop_server(server_info)
        finally:
            os.chdir(original_directory)

        return results

    def track_launch_time_s(self, results, profile):
        """Return launch time for one static-file profile."""
        return results[profile]

    track_launch_time_s.unit = "s"
    track_launch_time_s.pretty_name = "Static files debug launch time"
