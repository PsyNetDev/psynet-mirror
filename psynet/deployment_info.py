"""Persist launch metadata and deployment-scoped Git provenance.

Git identifies the commit that anchors a deployment, while ``deploy.toml``
identifies the files that are actually packaged. Dirty-state checks therefore
intersect Git changes with the deployment plan instead of treating unrelated,
excluded files as deployment changes. Git path output is normalized to the
experiment directory so nested repositories compare cleanly.
"""

import copy
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import jsonpickle
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from .utils import find_git_repo, get_logger

logger = get_logger()

path = ".deploy/deployment_info.json"

# ``(cache_key, content)``, replaced in a single assignment so threads never
# observe a partially updated cache.
_cache = None


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


def policy_selects_path(path, policy):
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


def _anchor_gitignore_rules(text, prefix):
    """Rewrite gitignore rules written for directory ``prefix`` to match from the repository root."""
    if not prefix:
        return text
    escaped_prefix = re.sub(r"([\\\[\]*?])", r"\\\1", prefix)
    lines = []
    for line in text.splitlines():
        negation = "!" if line.startswith("!") else ""
        pattern = line[len(negation) :]
        # Git ignores unescaped trailing spaces when deciding whether a rule
        # is anchored, i.e. contains a slash other than a trailing one.
        significant = re.sub(r"(?<!\\) +$", "", pattern)
        if significant and not line.startswith("#") and "/" in significant.rstrip("/"):
            line = negation + escaped_prefix + pattern.lstrip("/")
        lines.append(line)
    return "\n".join(lines) + "\n"


def _global_gitignore_rules():
    """Return the rules of the user's global Git excludes file, if any."""
    path = _git_output("config", "--path", "core.excludesFile")
    if not path:
        config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
        path = Path(config_home) / "git" / "ignore"
    path = Path(path).expanduser()
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _git_ignored_deployment_paths(extra_excludes_file=None):
    """Return deployment-selected paths ignored by Git, or ``None`` if Git cannot tell.

    ``extra_excludes_file`` adds the rules of another gitignore-format file,
    matched as if it were a ``.gitignore`` in the current directory.
    """
    plan = _deployment_plan()
    if plan is None:
        return None
    if not plan.destinations:
        return ()

    with tempfile.TemporaryDirectory() as tmp:
        command = ["git"]
        if extra_excludes_file is not None:
            prefix = _git_output("rev-parse", "--show-prefix")
            if prefix is None:
                logger.warning(
                    "Could not locate the experiment within its Git repository."
                )
                return None
            excludes = Path(tmp) / "excludes"
            try:
                # core.excludesFile replaces the user's global excludes file,
                # so keep its rules too.
                rules = _global_gitignore_rules() + "\n"
                rules += _anchor_gitignore_rules(
                    Path(extra_excludes_file).read_text(encoding="utf-8"), prefix
                )
            except (OSError, UnicodeDecodeError) as error:
                logger.warning("Could not read gitignore rules: %s", error)
                return None
            excludes.write_text(rules, encoding="utf-8")
            command += ["-c", f"core.excludesFile={excludes}"]
        command += ["check-ignore", "--stdin", "-z"]
        try:
            result = subprocess.run(
                command,
                input="\0".join(sorted(plan.destinations)) + "\0",
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("Could not run git to list Git-ignored deployment files.")
            return None
    if result.returncode not in {0, 1}:
        logger.warning(
            "git check-ignore failed while listing Git-ignored deployment files: %s",
            result.stderr.strip(),
        )
        return None
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
        path for path in deleted if policy_selects_path(path, plan.policy)
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
        # Replacing the file atomically gives it a new inode, so readers in other
        # processes never see a partial write or reuse a stale cache entry.
        tmp_path = f"{path}.{os.getpid()}.tmp"
        with open(tmp_path, "w") as file:
            file.write(encoded)
        os.replace(tmp_path, path)

    _clear_cache()
    try:
        f()
    except FileNotFoundError:
        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
        f()


def write(**kwargs):
    content = read_all()
    content.update(**kwargs)
    write_all(content)


def read_all():
    """Return the deployment info, decoding the file only when it has changed.

    Asset deposits read several keys per asset, so re-decoding the file on
    every call slowed deployment preparation for large asset sets. The cache
    is keyed on the file's path, inode, modification and change times, and
    size, so writes from other processes are still picked up.
    """
    return copy.deepcopy(_cached_content())


@retry(
    retry=retry_if_not_exception_type(FileNotFoundError),
    stop=stop_after_attempt(5),
    wait=wait_fixed(1),
    reraise=True,
)
def _cached_content():
    """Return the decoded deployment info, shared between callers; do not mutate.

    Retries cover reading a file that another process is still writing.
    """
    global _cache

    stat = os.stat(path)
    key = (
        os.path.abspath(path),
        stat.st_ino,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_size,
    )
    cache = _cache
    if cache is not None and cache[0] == key:
        return cache[1]
    with open(path, "r") as file:
        return loads(file.read())


def loads(txt: str) -> dict:
    """Decode a ``deployment_info.json`` document, for example one read from a server."""
    content = jsonpickle.decode(txt, keys=True)
    assert isinstance(content, dict)
    _cache = (key, content)
    return content


def _clear_cache():
    """Forget the decoded deployment info after this process changes the file."""
    global _cache
    _cache = None


def read(key):
    """Return a copy of one deployment-info value."""
    return copy.deepcopy(_cached_content()[key])


def delete():
    _clear_cache()
    os.remove(path)
