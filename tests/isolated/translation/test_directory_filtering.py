"""
Test that translation extraction skips virtual environment directories.
"""

import tempfile
from pathlib import Path

from yaspin import yaspin

from psynet.translation.utils import _get_py_entries_from_dir


def test_skip_hidden_directories():
    """Test that hidden directories (starting with .) are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a normal Python file
        normal_file = Path(tmpdir) / "normal.py"
        normal_file.write_text('_("translatable")\n')

        # Create a hidden directory with Python files
        hidden_dir = Path(tmpdir) / ".hidden_venv"
        hidden_dir.mkdir()
        hidden_file = hidden_dir / "package.py"
        hidden_file.write_text('_("should not be extracted")\n')

        # Extract translations
        with yaspin(text="Testing...") as sp:
            entries = _get_py_entries_from_dir(tmpdir, sp)

        # Should only get entries from normal.py, not from .hidden_venv/
        assert len(entries) > 0, "Should extract from normal.py"

        # Verify no entries from hidden directory
        for entry in entries:
            for occurrence_path, _ in entry.occurrences:
                assert ".hidden_venv" not in occurrence_path, (
                    "Should not extract from hidden directories"
                )


def test_skip_common_venv_names():
    """Test that common virtual environment directory names are skipped."""
    venv_names = ["venv", ".venv", "env", ".env"]

    # Include "env" in the temporary root name to ensure only relative directory
    # components are checked below.
    with tempfile.TemporaryDirectory(prefix="env") as tmpdir:
        # Create a normal Python file
        normal_file = Path(tmpdir) / "experiment.py"
        normal_file.write_text('_("normal translation")\n')

        # Create venv directories with Python files
        for venv_name in venv_names:
            venv_dir = Path(tmpdir) / venv_name
            venv_dir.mkdir()
            venv_file = venv_dir / "site_package.py"
            venv_file.write_text('_("venv translation")\n')

        # Extract translations
        with yaspin(text="Testing...") as sp:
            entries = _get_py_entries_from_dir(tmpdir, sp)

        # Verify no entries from venv directories
        for entry in entries:
            for occurrence_path, _ in entry.occurrences:
                relative_path = Path(occurrence_path).relative_to(tmpdir)
                occurrence_dirs = relative_path.parts[:-1]
                assert not set(venv_names).intersection(occurrence_dirs)


def test_skip_ide_and_build_directories():
    """Test that IDE and build directories are skipped."""
    skip_dirs = ["__pycache__", ".vscode", ".github", "node_modules"]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a normal Python file
        normal_file = Path(tmpdir) / "app.py"
        normal_file.write_text('_("app translation")\n')

        # Create directories that should be skipped
        for skip_dir in skip_dirs:
            skip_path = Path(tmpdir) / skip_dir
            skip_path.mkdir()
            skip_file = skip_path / "file.py"
            skip_file.write_text('_("skip this")\n')

        # Extract translations
        with yaspin(text="Testing...") as sp:
            entries = _get_py_entries_from_dir(tmpdir, sp)

        # Verify no entries from skipped directories
        for entry in entries:
            for occurrence_path, _ in entry.occurrences:
                for skip_dir in skip_dirs:
                    assert skip_dir not in occurrence_path, (
                        f"Should not extract from {skip_dir} directory"
                    )


def test_normal_directories_still_processed():
    """Test that normal directories are still processed correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create nested normal directories
        subdir = Path(tmpdir) / "submodule"
        subdir.mkdir()

        file1 = Path(tmpdir) / "main.py"
        file1.write_text('_("main translation")\n')

        file2 = subdir / "sub.py"
        file2.write_text('_("sub translation")\n')

        # Extract translations
        with yaspin(text="Testing...") as sp:
            entries = _get_py_entries_from_dir(tmpdir, sp)

        # Should get entries from both files
        assert len(entries) == 2, "Should extract from all normal directories"

        # Verify both files are represented
        all_paths = []
        for entry in entries:
            for occurrence_path, _ in entry.occurrences:
                all_paths.append(occurrence_path)

        assert any("main.py" in p for p in all_paths), "Should extract from main.py"
        assert any("sub.py" in p for p in all_paths), (
            "Should extract from submodule/sub.py"
        )


def test_performance_with_large_venv():
    """Test that extraction completes quickly even with large venv directory."""
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a normal Python file
        normal_file = Path(tmpdir) / "experiment.py"
        normal_file.write_text('_("test")\n')

        # Create a .venv with many files (simulating real venv)
        venv_dir = Path(tmpdir) / ".venv" / "lib" / "python3.13" / "site-packages"
        venv_dir.mkdir(parents=True)

        # Create 100 Python files in venv
        for i in range(100):
            venv_file = venv_dir / f"package{i}.py"
            venv_file.write_text("# library code\n")

        # Extract should complete quickly
        start_time = time.time()
        with yaspin(text="Testing...") as sp:
            entries = _get_py_entries_from_dir(tmpdir, sp)
        elapsed = time.time() - start_time

        # Should complete in under 5 seconds (would hang indefinitely without fix)
        assert elapsed < 5, f"Extraction took {elapsed}s, should be under 5s"

        # Should only extract from experiment.py
        assert len(entries) == 1, "Should only extract from experiment.py, not venv"
