import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_PAGES = ROOT / "docs" / "scripts" / "build_pages.sh"


def write_executable(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def fake_pages_repo(tmp_path):
    docs_scripts = tmp_path / "docs" / "scripts"
    docs_scripts.mkdir(parents=True)
    shutil.copy(BUILD_PAGES, docs_scripts / "build_pages.sh")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    write_executable(
        bin_dir / "pip",
        """#!/usr/bin/env bash
set -euo pipefail
exit 0
""",
    )
    write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "fetch" ]; then
    exit 0
fi
if [ "$1" = "worktree" ] && [ "$2" = "add" ]; then
    worktree_dir="$4"
    ref="$5"
    mkdir -p "$worktree_dir/docs/_static"
    printf "%s\\n" "$ref" > "$worktree_dir/docs/ref.txt"
    exit 0
fi
if [ "$1" = "worktree" ] && [ "$2" = "remove" ]; then
    rm -rf "$4"
    exit 0
fi
echo "Unexpected git invocation: $*" >&2
exit 1
""",
    )
    write_executable(
        bin_dir / "python",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" != "docs/scripts/generate_version_switcher.py" ]; then
    echo "Unexpected python invocation: $*" >&2
    exit 1
fi
shift
output=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            output="$2"
            shift 2
            ;;
        --print-alpha-version)
            echo "${ALPHA_VERSION:-13.3.0a0}"
            exit 0
            ;;
        --print-highest-stable)
            echo "${HIGHEST_STABLE:-v13.2.0}"
            exit 0
            ;;
        --print-selected-stable-tags)
            echo "${SELECTED_STABLE_TAGS:-v13.2.0}"
            exit 0
            ;;
        --print-latest-rc-tag)
            if [ -n "${LATEST_RC:-}" ]; then
                echo "$LATEST_RC"
            fi
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done
if [ -n "$output" ]; then
    mkdir -p "$(dirname "$output")"
    printf '{"entries": []}\\n' > "$output"
    exit 0
fi
echo "Missing expected generate_version_switcher.py option" >&2
exit 1
""",
    )
    write_executable(
        bin_dir / "sphinx-build",
        """#!/usr/bin/env bash
set -euo pipefail
output_dir="${@: -1}"
mkdir -p "$output_dir/_static"
printf "%s\\n" "${DOCS_VERSION:-missing}" > "$output_dir/index.html"
printf '{"entries": []}\\n' > "$output_dir/_static/version_switcher.json"
""",
    )

    return tmp_path, bin_dir


def run_build_pages(repo_dir, bin_dir, **env):
    full_env = os.environ.copy()
    full_env.update(
        {
            "PATH": f"{bin_dir}:{full_env['PATH']}",
            "CI_DEFAULT_BRANCH": "master",
        }
    )
    full_env.update({key: value for key, value in env.items() if value is not None})
    full_env.pop("CI_COMMIT_TAG", None) if env.get("CI_COMMIT_TAG") is None else None

    subprocess.run(
        ["bash", "docs/scripts/build_pages.sh"],
        cwd=repo_dir,
        env=full_env,
        check=True,
    )


def read_text(path):
    return path.read_text(encoding="utf-8")


def test_default_branch_rebuilds_only_alpha_docs(tmp_path):
    repo_dir, bin_dir = fake_pages_repo(tmp_path)
    (repo_dir / "public" / "v13.1.0").mkdir(parents=True)
    (repo_dir / "public" / "v13.1.0" / "index.html").write_text(
        "old stable\n", encoding="utf-8"
    )
    (repo_dir / "public" / "rc" / "v13.2.0rc0").mkdir(parents=True)
    (repo_dir / "public" / "rc" / "v13.2.0rc0" / "index.html").write_text(
        "old rc\n", encoding="utf-8"
    )

    run_build_pages(repo_dir, bin_dir, CI_COMMIT_BRANCH="master")

    assert read_text(repo_dir / "public" / "alpha" / "index.html") == "13.3.0a0\n"
    assert read_text(repo_dir / "public" / "v13.1.0" / "index.html") == "old stable\n"
    assert (repo_dir / "public" / "rc" / "v13.2.0rc0").exists()


def test_rc_tag_builds_current_rc_and_removes_older_same_base_docs(tmp_path):
    repo_dir, bin_dir = fake_pages_repo(tmp_path)
    (repo_dir / "public" / "rc" / "v13.2.0rc0").mkdir(parents=True)
    (repo_dir / "public" / "rc" / "v13.1.0rc0").mkdir(parents=True)

    run_build_pages(
        repo_dir,
        bin_dir,
        CI_COMMIT_TAG="v13.2.0rc1",
        LATEST_RC="v13.2.0rc1",
    )

    assert read_text(repo_dir / "public" / "rc" / "v13.2.0rc1" / "index.html") == (
        "v13.2.0rc1\n"
    )
    assert not (repo_dir / "public" / "rc" / "v13.2.0rc0").exists()
    assert (repo_dir / "public" / "rc" / "v13.1.0rc0").exists()
    assert not (repo_dir / "public" / "alpha").exists()


def test_highest_stable_tag_updates_versioned_docs_root_and_stale_rc_docs(tmp_path):
    repo_dir, bin_dir = fake_pages_repo(tmp_path)
    (repo_dir / "public" / "rc" / "v13.2.0rc1").mkdir(parents=True)
    (repo_dir / "public" / "rc" / "v13.1.0rc0").mkdir(parents=True)

    run_build_pages(
        repo_dir,
        bin_dir,
        CI_COMMIT_TAG="v13.2.0",
        HIGHEST_STABLE="v13.2.0",
    )

    assert read_text(repo_dir / "public" / "v13.2.0" / "index.html") == "v13.2.0\n"
    assert read_text(repo_dir / "public" / "index.html") == "v13.2.0\n"
    assert not (repo_dir / "public" / "rc" / "v13.2.0rc1").exists()
    assert (repo_dir / "public" / "rc" / "v13.1.0rc0").exists()
    assert not (repo_dir / "public" / "alpha").exists()


def test_non_highest_stable_tag_does_not_update_root_docs(tmp_path):
    repo_dir, bin_dir = fake_pages_repo(tmp_path)
    (repo_dir / "public").mkdir()
    (repo_dir / "public" / "index.html").write_text("old root\n", encoding="utf-8")

    run_build_pages(
        repo_dir,
        bin_dir,
        CI_COMMIT_TAG="v13.2.1",
        HIGHEST_STABLE="v13.3.0",
    )

    assert read_text(repo_dir / "public" / "v13.2.1" / "index.html") == "v13.2.1\n"
    assert read_text(repo_dir / "public" / "index.html") == "old root\n"
