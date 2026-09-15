"""Persist launch metadata and deployment-scoped Git provenance.

Git identifies the commit that anchors a deployment, while ``deploy.toml``
identifies the files that are actually packaged. Dirty-state checks therefore
intersect Git changes with the deployment plan instead of treating unrelated,
excluded files as deployment changes. Git path output is normalized to the
experiment directory so nested repositories compare cleanly.
"""

import os
import subprocess
import uuid
from pathlib import Path

import jsonpickle
from tenacity import retry, stop_after_attempt, wait_fixed

from .utils import find_git_repo

path = ".deploy/deployment_info.json"


def _git_output(*args):
    """Run Git and return stripped output, or ``None`` when unavailable."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_path_set(*args, prefix=""):
    """Run Git with NUL output and return experiment-relative paths.

    ``git ls-files`` reports paths relative to the current directory, while
    ``git diff --name-only`` reports paths relative to the repository root.
    Strip ``prefix`` (from ``git rev-parse --show-prefix``) so both can be
    compared with deployment-plan destinations.
    """
    output = _git_output(*args, "-z", "--", ".")
    if output is None:
        return None
    return {
        _experiment_relative_git_path(path, prefix)
        for path in output.split("\0")
        if path
    }


def _git_worktree_prefix():
    """Return the repository-relative prefix of the current directory."""
    prefix = _git_output("rev-parse", "--show-prefix")
    if prefix is None:
        return None
    return prefix


def _experiment_relative_git_path(path, prefix):
    """Return a Git path relative to the experiment working directory."""
    posix = path.replace("\\", "/")
    if prefix and posix.startswith(prefix):
        return posix[len(prefix) :]
    return posix


def _policy_selects_path(path, policy):
    """Return whether ``path`` would be copied under ``policy`` if it existed."""
    from dallinger.deployment_plan import _is_excluded, _is_omitted_anywhere

    parts = tuple(part for part in path.replace("\\", "/").split("/") if part)
    if not parts:
        return False
    names = frozenset(policy.exclude_names)
    suffixes = policy.exclude_suffixes
    if any(_is_omitted_anywhere(part, names, suffixes) for part in parts):
        return False
    return not _is_excluded(parts, frozenset(policy.exclude_paths))


def _deployment_plan():
    """Build the current deployment plan, or return ``None`` before migration."""
    if not Path("deploy.toml").is_file():
        return None
    from dallinger.deployment_plan import build_deployment_plan

    return build_deployment_plan(Path.cwd())


def _git_ignored_deployment_paths():
    """Return deployment-selected paths currently ignored by Git."""
    plan = _deployment_plan()
    if plan is None or not plan.destinations:
        return ()

    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            input="\0".join(sorted(plan.destinations)) + "\0",
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ()
    if result.returncode not in {0, 1}:
        return ()
    return tuple(path for path in result.stdout.split("\0") if path)


def _get_git_provenance():
    """Return the current commit SHA and deployment-scoped dirty state."""
    commit_sha = _git_output("rev-parse", "HEAD")
    if commit_sha is None:
        return None, None

    plan = _deployment_plan()
    if plan is None:
        status = _git_output(
            "status", "--porcelain", "--untracked-files=normal", "--", "."
        )
        return commit_sha, None if status is None else bool(status)

    prefix = _git_worktree_prefix()
    if prefix is None:
        return commit_sha, None

    tracked = _git_path_set("ls-files", "--cached", prefix=prefix)
    changed = _git_path_set("diff", "--name-only", "HEAD", prefix=prefix)
    deleted = _git_path_set(
        "diff", "--name-only", "--diff-filter=D", "HEAD", prefix=prefix
    )
    if tracked is None or changed is None or deleted is None:
        return commit_sha, None

    selected = plan.destinations
    selected_untracked = selected - tracked
    selected_changed = selected & changed
    selected_deleted = {
        path for path in deleted if _policy_selects_path(path, plan.policy)
    }
    return commit_sha, bool(selected_untracked or selected_changed or selected_deleted)


def init(
    redeploying_from_archive: bool,
    mode: str,
    is_local_deployment: bool,
    is_ssh_deployment: bool,
    server: str,
    app: str,
    folder_name: str = os.path.basename(os.getcwd()),
):
    secret = uuid.uuid4()
    origin = find_git_repo()
    git_commit_sha, git_dirty = _get_git_provenance()
    write_all(locals())


def is_available():
    return os.path.exists(path)


def reset():
    write_all({})


def write_all(content: dict):
    encoded = jsonpickle.encode(content, indent=4, keys=True)

    def f():
        with open(path, "w") as file:
            file.write(encoded)

    try:
        f()
    except FileNotFoundError:
        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
        f()


def write(**kwargs):
    content = read_all()
    content.update(**kwargs)
    write_all(content)


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1), reraise=True)
def read_all():
    with open(path, "r") as file:
        txt = file.read()
    content = jsonpickle.decode(txt, keys=True)
    assert isinstance(content, dict)
    return content


def read(key):
    content = read_all()
    return content[key]


def delete():
    os.remove(path)
