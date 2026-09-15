"""Create, update, and prune PsyNet experiment scaffold files."""

import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import metadata, resources
from pathlib import Path
from urllib.parse import unquote, urlparse

import click

from psynet.light_utils import md5_directory
from psynet.version import psynet_version

_TEMPLATE_FILES = (
    ".gitignore",
    "Dockerfile",
    "README.md",
    "__init__.py",
    "pytest.ini",
    "test.py",
    "config.txt",
    "deploy.toml",
    ".github/workflows/test.yml",
    ".vscode/launch.json",
    "AGENTS.md",
)

# Create these when missing, but never overwrite existing copies (authors customize them).
_PRESERVE_EXISTING_TEMPLATE_FILES = frozenset(
    {"config.txt", "README.md", "deploy.toml"}
)

# Copied into experiments by ``psynet scripts update``; not a packaged template
# directory (canonical source is ``.cursor/skills/experiment/`` in the PsyNet
# checkout).
_EXPERIMENT_SKILLS_DIRECTORY = ".cursor/skills/psynet"
_MANAGED_DIRECTORIES = (_EXPERIMENT_SKILLS_DIRECTORY,)

# Minimal scaffold subset needed to run locally (debug/test). Omits IDE/CI-only
# templates such as ``.vscode/`` and ``.github/workflows/``.
_TEMPLATE_FILES_REQUIRED_FOR_LOCAL_RUN = (
    ".gitignore",
    ".python-version",
    "Dockerfile",
    "test.py",
    "config.txt",
    "deploy.toml",
)

_GENERATED_DOCKERIGNORE_VARIANTS = (
    (
        "# We don't want to copy virtual environments into the Docker image",
        ".venv",
        ".env",
    ),
    (
        "# We don't want to copy virtual environments into the Docker image",
        ".venv",
        ".env",
        "",
        "# Agent Skills are for local editors, not the running experiment image",
        ".cursor/skills/psynet/",
    ),
)

# Previously scaffolded experiment-local Docker CLI helpers. These called
# ``docker build`` directly and cannot honor ``deploy.toml``.
_OBSOLETE_DOCKER_SCRIPT_PATHS = (
    "docker/build",
    "docker/check-dev-installations",
    "docker/docs/INSTALL.md",
    "docker/docs/RUN.md",
    "docker/docs/UPDATE.md",
    "docker/local-ssh",
    "docker/params",
    "docker/psynet",
    "docker/psynet-dev",
    "docker/README.md",
    "docker/run",
    "docker/run-dev",
    "docker/services",
)

# Hashes of the final experiment-local Docker helper templates shipped by
# PsyNet. Divergent files are author-owned and must not be deleted.
_OBSOLETE_DOCKER_SCRIPT_HASHES = {
    "docker/build": "6fa98c5faa398675de5aa6cb82481b4a",
    "docker/check-dev-installations": "8d699b652b6381a3b38a0ea60281050a",
    "docker/docs/INSTALL.md": "4a0b5f238227ecb39f9af16368265b35",
    "docker/docs/RUN.md": "ef8ea770256bc4280d347f33e5c34ee1",
    "docker/docs/UPDATE.md": "e990837fbe40d4113a2160cb3998b8bb",
    "docker/local-ssh": "65ddab944cecf4de0e7f942268f4c164",
    "docker/params": "24e5784cfed1584aff8c76804a7d72a2",
    "docker/psynet": "2e689f85e226e41da343609ccc412bad",
    "docker/psynet-dev": "facd3771875eac8a2453dca5bd39bd90",
    "docker/README.md": "8a17a4cea31b7ea438993be74c9deec1",
    "docker/run": "d2130575f9bf70b8552abad173ad7caa",
    "docker/run-dev": "5eb60b21412b9fece4fa7e1959fa7247",
    "docker/services": "acd66129fe59699302ab998b4b1eeca3",
}

_GENERATED_FILES = {
    "Dockertag": lambda: dockertag_contents(),
    ".python-version": lambda: f"{_current_python_major_minor()}\n",
}

_REMOVABLE_DIRECTORIES = (("docs", "abfc54bbbc3ef9d5948957841727a18b"),)

_EMPTY_RESOURCE_DIRECTORIES = ("static", "templates")

_BOOTSTRAP_FILES = ("experiment.py", "requirements.txt")

_EXPERIMENT_PY_TEMPLATE = """\
import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = {label!r}

    timeline = Timeline(
        InfoPage("Welcome!", time_estimate=5),
    )
"""

_REQUIREMENTS_TXT_COMMENTS = """\

# Alternatively, you can use one of the following syntaxes to specify a custom PsyNet version
# psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.4.0#egg=psynet
# psynet@git+https://gitlab.com/PsyNetDev/PsyNet@45f317688af59350f9a6f3052fd73076318f2775#egg=psynet
# psynet@git+https://gitlab.com/PsyNetDev/PsyNet@45f31768#egg=psynet
"""


def _current_python_major_minor() -> str:
    """Return the running interpreter's major and minor version."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def dockertag_contents() -> str:
    """Return Dockertag file contents for the current experiment directory."""
    return f"{Path.cwd().name}\n"


def _experiment_script_resource(relative_path: str):
    """Return a Traversable for a packaged experiment-script template path."""
    return resources.files("psynet") / f"resources/experiment_scripts/{relative_path}"


def scaffold_managed_paths() -> frozenset[str]:
    """Return paths managed by the experiment scaffold.

    Returns
    -------
    frozenset[str]
        Relative paths to scaffold-managed files and directories.
    """
    paths = set(_TEMPLATE_FILES)
    paths.update(_MANAGED_DIRECTORIES)
    paths.update(_GENERATED_FILES)
    return frozenset(paths)


def scaffold_paths_required_for_local_run() -> frozenset[str]:
    """Return scaffold paths required before running an experiment locally.

    This is a deliberate subset of :func:`scaffold_managed_paths`, covering the
    files needed for local runs rather than optional IDE/CI templates.
    """
    required = set(_TEMPLATE_FILES_REQUIRED_FOR_LOCAL_RUN)
    managed = scaffold_managed_paths()
    unexpected = required - managed
    if unexpected:
        raise RuntimeError(
            "Required local-run scaffold paths must be scaffold-managed: "
            + ", ".join(sorted(unexpected))
        )
    return frozenset(required)


def missing_scaffold_paths_required_for_local_run(
    root: Path | str | None = None,
) -> list[str]:
    """Return required local-run scaffold paths missing from ``root``."""
    base = Path(".") if root is None else Path(root)
    missing = []
    for relative_path in sorted(scaffold_paths_required_for_local_run()):
        if not (base / relative_path).exists():
            missing.append(relative_path)
    return missing


def _default_experiment_label() -> str:
    """Build a readable experiment label from the current directory name."""
    return Path.cwd().name.replace("_", " ").replace("-", " ").strip() or "Experiment"


def _default_experiment_py() -> str:
    """Return a minimal starter ``experiment.py``."""
    return _EXPERIMENT_PY_TEMPLATE.format(label=_default_experiment_label())


def _default_requirements_txt() -> str:
    """Return a starter ``requirements.txt`` for the current PsyNet version."""
    requirement = _default_psynet_requirement()
    return f"{requirement}\n{_REQUIREMENTS_TXT_COMMENTS}"


_PUBLIC_HTTPS_GIT_HOSTS = frozenset({"gitlab.com", "github.com", "www.github.com"})


def _normalize_git_repo_path(path: str) -> str:
    """Strip trailing slashes and an optional ``.git`` suffix from a repo path."""
    return path.rstrip("/").removesuffix(".git")


def _normalize_git_remote_to_pip_base(remote_url: str) -> str:
    """Convert a git remote URL into a pip ``git+…`` base without a ref.

    SSH remotes on public hosts (GitLab/GitHub) are normalized to HTTPS for
    more portable requirement pins. Other SSH remotes keep ``git+ssh``.
    """
    remote_url = remote_url.strip()
    scp_match = re.match(r"^git@([^:]+):(.+)$", remote_url)
    if scp_match:
        host, path = scp_match.groups()
        path = _normalize_git_repo_path(path).lstrip("/")
        if host in _PUBLIC_HTTPS_GIT_HOSTS:
            return f"git+https://{host}/{path}"
        return f"git+ssh://git@{host}/{path}"

    if remote_url.startswith("git+"):
        remote_url = remote_url[4:]

    parsed = urlparse(remote_url)
    if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.path:
        path = _normalize_git_repo_path(parsed.path)
        return f"git+{parsed.scheme}://{parsed.hostname}{path}"

    if parsed.scheme == "ssh" and parsed.hostname and parsed.path:
        path = _normalize_git_repo_path(parsed.path).lstrip("/")
        if parsed.hostname in _PUBLIC_HTTPS_GIT_HOSTS:
            return f"git+https://{parsed.hostname}/{path}"
        return f"git+ssh://git@{parsed.hostname}/{path}"

    raise ValueError(f"Unrecognized git remote URL: {remote_url}")


def _git_remote_url(source: Path, remote: str = "origin") -> str | None:
    """Return the configured URL for a git remote, if present."""
    try:
        url = subprocess.check_output(
            ["git", "-C", str(source), "remote", "get-url", remote],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return url or None


def _remote_advertises_commit(
    source: Path, commit: str, remote: str = "origin"
) -> bool:
    """Return whether ``remote`` can serve ``commit``.

    Lists advertised heads/tags with ``git ls-remote`` and checks whether
    ``commit`` equals an advertised tip or is an ancestor of one whose object
    exists locally. Avoids ``git fetch --dry-run``, which exits successfully for
    any SHA already in the local object store even when the remote does not
    have it.

    Passing a SHA as a ``git ls-remote`` ref pattern is not reliable on GitLab
    (SHAs are not advertised as refs), which is why this lists refs and
    compares locally. Ancestry against many tips is done in one ``rev-list``
    call so unpushed commits fail quickly instead of spawning two subprocesses
    per advertised tip.
    """
    try:
        # Ask the remote which commits its heads/tags currently point at.
        # Output lines look like "<sha>\t<ref>". Limiting to heads/tags skips
        # GitLab merge-request refs and other advertisement noise.
        output = subprocess.check_output(
            ["git", "-C", str(source), "ls-remote", "--heads", "--tags", remote],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False

    advertised = []
    seen = set()
    for line in output.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        sha = line.split("\t", 1)[0].strip()
        if not sha or sha in seen:
            continue
        seen.add(sha)
        advertised.append(sha)

    # Fast path: the commit is itself a remote tip (e.g. current HEAD after push).
    if commit in advertised:
        return True

    local_tips = _locally_present_commit_tips(source, advertised)
    if not local_tips:
        return False

    # Empty rev-list means ``commit`` is reachable from at least one tip
    # (i.e. it is an ancestor of a tip the remote advertises).
    try:
        reachable_only_from_commit = subprocess.check_output(
            [
                "git",
                "-C",
                str(source),
                "rev-list",
                "-n1",
                commit,
                "--not",
                *local_tips,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    return reachable_only_from_commit == ""


def _locally_present_commit_tips(source: Path, tips: list[str]) -> list[str]:
    """Return advertised tip SHAs whose commit objects exist in ``source``."""
    if not tips:
        return []

    try:
        # Batch existence checks: one process for all tips instead of cat-file
        # per tip. Input lines are object names; output is "<sha> <type> <size>"
        # or "<sha> missing".
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "cat-file",
                "--batch-check=%(objectname) %(objecttype)",
            ],
            input="".join(f"{tip}^{{commit}}\n" for tip in tips),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []

    present = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "commit":
            present.append(parts[0])
    return present


def _remote_contains_commit(source: Path, commit: str, remote: str = "origin") -> bool:
    """Return whether ``commit`` is available on ``remote``.

    Current remote heads and tags are authoritative. Local remote-tracking refs
    can be stale after a branch deletion or force-push, so they must not prove
    deployability by themselves.
    """
    return _remote_advertises_commit(source, commit, remote=remote)


def _psynet_direct_url_info() -> dict | None:
    """Return PEP 610 ``direct_url.json`` metadata for the installed PsyNet.

    Present only for direct installs (path, editable, or VCS); ``None`` when
    PsyNet came from an index or is not installed.
    """
    try:
        direct_url = metadata.distribution("psynet").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if direct_url is None:
        return None
    return json.loads(direct_url)


def _installed_psynet_file_path() -> Path | None:
    """Return the local path when PsyNet was installed from a ``file://`` URL.

    Covers both editable and non-editable path installs (for example
    ``uv pip install /path/to/PsyNet`` or ``uv pip install -e /path/to/PsyNet``).
    """
    installation = _psynet_direct_url_info()
    if installation is None:
        return None
    parsed_url = urlparse(installation["url"])
    if parsed_url.scheme != "file":
        return None
    return Path(unquote(parsed_url.path)).resolve()


def installed_psynet_direct_requirement() -> str | None:
    """Return a requirement reproducing a direct (non-index) PsyNet install.

    Handles VCS installs such as ``pip install git+<url>@<commit>``, whose
    provenance pip records under ``vcs_info``, and non-editable path installs.
    Returns ``None`` for index installs and for editable checkouts, which
    callers represent with :func:`editable_psynet_requirement` instead.
    """
    installation = _psynet_direct_url_info()
    if installation is None:
        return None
    if installation.get("dir_info", {}).get("editable", False):
        return None

    url = installation.get("url")
    vcs_info = installation.get("vcs_info") or {}
    vcs = vcs_info.get("vcs")
    commit = vcs_info.get("commit_id")
    if url and vcs and commit:
        return f"psynet @ {vcs}+{url}@{commit}"

    local_path = _installed_psynet_file_path()
    if local_path is not None:
        return f"psynet @ {local_path.as_uri()}"
    return None


def _with_experiment_extra(requirement: str) -> str:
    """Ensure a PsyNet requirement includes the ``[experiment]`` extra."""
    text = requirement.strip()
    if re.match(r"(?i)^psynet\[experiment\]\b", text):
        return text
    return re.sub(r"(?i)^psynet\b", "psynet[experiment]", text, count=1)


def _default_psynet_requirement() -> str:
    """Return a resolvable PsyNet requirement for a new experiment.

    Always includes the ``[experiment]`` extra so that ``psynet setup`` installs
    the full runtime.

    Resolution order:

    1. Editable checkout → commit pin (alphas, when the commit is servable) or
       editable path.
    2. Non-editable VCS or local-path install → the same source, with the
       ``[experiment]`` extra. A git checkout of an unpublished alpha must not
       become ``psynet[experiment]==<version>``, which is unsatisfiable on PyPI.
    3. Otherwise → version pin ``psynet[experiment]==<version>``.
    """
    editable_source = get_editable_psynet_source()
    if editable_source is not None:
        if re.search(r"a\d+$", psynet_version):
            commit_requirement = _optional_commit_psynet_requirement(editable_source)
            if commit_requirement is not None:
                return commit_requirement
        return editable_psynet_requirement(editable_source)

    direct = installed_psynet_direct_requirement()
    if direct is not None:
        return _with_experiment_extra(direct)

    local_path = _installed_psynet_file_path()
    if local_path is not None:
        return f"psynet[experiment] @ {local_path.as_uri()}"

    return f"psynet[experiment]=={psynet_version}"


def _optional_commit_psynet_requirement(source: Path) -> str | None:
    """Return a commit pin for ``source``, or ``None`` when one is impossible.

    Alpha scaffolds prefer a deployable commit pin, but this automatic path must
    still produce a working experiment when the checkout's commit cannot be
    served by ``origin``. That happens for unpushed work and, unavoidably, in CI
    merged-result pipelines whose HEAD exists only under
    ``refs/merge-requests/*``. Falling back to the editable requirement matches
    what a checkout without any commit already does, and is announced rather
    than silent because the result is machine-local.

    Callers that explicitly request a commit pin (``psynet setup
    --psynet-source commit``) use :func:`commit_psynet_requirement` directly so
    an impossible pin stays a hard error there.
    """
    if _current_source_commit(source) is None:
        return None
    try:
        return commit_psynet_requirement(source)
    except ValueError as exc:
        click.echo(
            f"Warning: {exc}\nRecording an editable PsyNet requirement instead, "
            "which only resolves on this machine. Use 'psynet setup "
            "--psynet-source commit' to require a deployable commit pin.",
            err=True,
        )
        return None


def get_editable_psynet_source() -> Path | None:
    """Return the source path when PsyNet is installed in editable mode."""
    installation = _psynet_direct_url_info()
    if installation is None:
        return None
    if not installation.get("dir_info", {}).get("editable", False):
        return None
    parsed_url = urlparse(installation["url"])
    if parsed_url.scheme != "file":
        return None
    return Path(unquote(parsed_url.path)).resolve()


def editable_psynet_requirement(source: Path) -> str:
    """Return a named editable requirement for a local PsyNet checkout.

    The ``[experiment]`` extra is included so that a standalone experiment's
    environment gets the full runtime even when PsyNet is installed editable.
    """
    return f"-e {source.resolve().as_uri()}#egg=psynet[experiment]"


def commit_psynet_requirement(source: Path) -> str:
    """Return a portable requirement for a PsyNet checkout's current commit.

    The pin uses the checkout's ``origin`` remote so forks work. The commit must
    already be reachable from a remote-tracking ref (typically after
    ``git push``).
    """
    source = Path(source)
    commit = _current_source_commit(source)
    if commit is None:
        raise ValueError(f"Could not determine a Git commit for {source}.")

    remote_url = _git_remote_url(source, remote="origin")
    if remote_url is None:
        raise ValueError(
            f"Could not determine git remote 'origin' for {source}. "
            "Add an origin remote, or use --psynet-source editable."
        )

    try:
        pip_base = _normalize_git_remote_to_pip_base(remote_url)
    except ValueError as exc:
        raise ValueError(
            f"Could not convert git remote 'origin' ({remote_url}) into a pip "
            "requirement. Use --psynet-source editable, or set origin to an "
            "https/ssh git URL."
        ) from exc

    if not _remote_contains_commit(source, commit, remote="origin"):
        raise ValueError(
            f"Commit {commit[:12]} is not available on git remote 'origin' "
            f"({remote_url}). Push your PsyNet commits first "
            "(`git push origin HEAD`), or fetch the remote tip "
            "(`git fetch origin`) if this commit was already pushed from "
            "another clone, then retry. Or use --psynet-source editable."
        )

    return f"psynet[experiment]@{pip_base}@{commit}#egg=psynet"


def _is_psynet_requirement_line(line: str) -> bool:
    """Return whether a requirements.txt line is a PsyNet dependency entry.

    Matches bare ``psynet``, ``psynet[experiment]``, and git-URL forms with
    ``#egg=psynet`` or ``#egg=psynet[experiment]``.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return bool(
        re.match(r"(?i)^psynet(?:\s*$|\s*[@<>=!~\[])", stripped)
        or re.search(r"(?i)#egg=psynet(?:\[[\w,]+\])?(?:\s|$)", stripped)
    )


def is_unambiguous_psynet_requirement(requirement: str) -> bool:
    """Return whether a PsyNet requirement pins a version or commit.

    Accepted formats are (with or without the ``[experiment]`` extra):

    - ``psynet[experiment]==<version>`` / ``psynet==<version>``
    - ``psynet[experiment]@git+https://<host>/<path>@v<version>#egg=psynet``
    - ``psynet[experiment]@git+https://<host>/<path>@<commit-hash>#egg=psynet``
    - ``psynet[experiment]@git+ssh://git@<host>/<path>@<commit-hash>#egg=psynet``
    """
    commit_or_tag = (
        r"(?:[a-fA-F0-9]{8,40}|v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
        r"(?:(?:rc|a)\d+)?)"
    )
    git_path = r"[\w.+\-]+(?:/[\w.+\-]+)+"
    extras = r"(?:\[[\w,\s]+\])?"
    egg = r"(?:#egg=psynet(?:\[[\w,]+\])?)?"
    patterns = [
        rf"^psynet{extras}(\s?)@(\s?)git\+https://[\w.-]+/{git_path}(\.git)?@"
        rf"{commit_or_tag}{egg}$",
        rf"^psynet{extras}(\s?)@(\s?)git\+ssh://git@[\w.-]+/{git_path}(\.git)?@"
        rf"{commit_or_tag}{egg}$",
        rf"^psynet{extras}(\s?)==(\s?)\d+\.\d+\.\d+((rc|a)\d+)?$",
    ]
    return any(re.fullmatch(pattern, requirement.strip()) for pattern in patterns)


def get_psynet_requirement() -> str | None:
    """Return the active PsyNet entry from requirements.txt."""
    matches = [
        line.strip()
        for line in Path("requirements.txt").read_text().splitlines()
        if _is_psynet_requirement_line(line)
    ]
    if len(matches) > 1:
        raise ValueError("requirements.txt contains multiple PsyNet requirements.")
    return matches[0] if matches else None


def set_psynet_requirement(requirement: str) -> bool:
    """Replace or add the active PsyNet entry in requirements.txt."""
    path = Path("requirements.txt")
    lines = path.read_text().splitlines(keepends=True)
    existing = get_psynet_requirement()
    if existing == requirement:
        return False

    replaced = False
    updated_lines = []
    for line in lines:
        if line.strip() == existing:
            newline = "\n" if line.endswith("\n") else ""
            updated_lines.append(f"{requirement}{newline}")
            replaced = True
        else:
            updated_lines.append(line)
    if not replaced:
        updated_lines.insert(0, f"{requirement}\n")
    path.write_text("".join(updated_lines))
    return True


def pin_unpinned_psynet_requirement() -> bool:
    """Pin a bare PsyNet requirement to the active version or source commit.

    Both ``psynet`` and ``psynet[experiment]`` (case-insensitive) are treated
    as unpinned and will be replaced with the result of
    :func:`_default_psynet_requirement`.
    """
    requirement = get_psynet_requirement()
    if requirement is None:
        return False
    bare = re.sub(r"\[.*\]", "", requirement).strip().lower()
    if bare != "psynet":
        return False
    return set_psynet_requirement(_default_psynet_requirement())


def _current_source_commit(source=None) -> str | None:
    """Return the source checkout commit when PsyNet is installed from Git."""
    source = Path(__file__).parent.parent if source is None else Path(source)
    try:
        commit = subprocess.check_output(
            [
                "git",
                "-C",
                str(source),
                "rev-parse",
                "HEAD",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None


def _bootstrap_authored_files(skip_files):
    """Create missing starter experiment files without overwriting existing ones.

    Contents are computed before any writes so a failed PsyNet pin (for example
    an unpushed alpha commit) does not leave a partial authored bootstrap.
    """
    written = []
    skipped = []
    bootstrap_files = {
        "experiment.py": _default_experiment_py,
        "requirements.txt": _default_requirements_txt,
    }

    pending = []
    for relative_path, contents_factory in bootstrap_files.items():
        if relative_path in skip_files:
            skipped.append(relative_path)
            continue

        # Authored starter files are never overwritten, even during scripts update.
        if Path(relative_path).exists():
            skipped.append(relative_path)
            continue

        pending.append((relative_path, contents_factory()))

    for relative_path, contents in pending:
        if _write_generated_file(relative_path, contents, overwrite=False):
            written.append(relative_path)
        else:
            skipped.append(relative_path)

    return written, skipped


def _summarize_written_paths(written):
    """Build a short human summary of created or updated paths."""
    authored = [path for path in written if path in _BOOTSTRAP_FILES]
    boilerplate_count = sum(1 for path in written if path not in _BOOTSTRAP_FILES)

    if authored and boilerplate_count:
        authored_text = ", ".join(authored)
        noun = "boilerplate file" if boilerplate_count == 1 else "boilerplate files"
        return f"{authored_text}, and {boilerplate_count} {noun}"
    if authored:
        return ", ".join(authored)
    if boilerplate_count:
        noun = "boilerplate file" if boilerplate_count == 1 else "boilerplate files"
        return f"{boilerplate_count} {noun}"
    return None


def _report_scaffold_result(written, *, overwrite):
    """Print a concise summary of a scaffold or update run."""
    directory_name = Path.cwd().name
    summary = _summarize_written_paths(written)

    if overwrite:
        if summary:
            click.echo(f"Updated experiment scripts in {directory_name}")
            click.echo(f"  updated: {summary}")
        else:
            click.echo(
                f"Experiment scripts in {directory_name} are already up to date."
            )
        return

    if summary:
        click.echo(f"Scaffolded experiment in {directory_name}")
        click.echo(f"  created: {summary}")
        return

    click.echo("Nothing to scaffold; experiment boilerplate is already present.")


def _copy_template_file(relative_path, overwrite):
    """Copy one scaffold-managed template file into the experiment directory."""
    destination = Path(relative_path)
    if relative_path in _PRESERVE_EXISTING_TEMPLATE_FILES:
        overwrite = False
    if destination.exists() and not overwrite:
        return False
    if overwrite and _template_file_matches(relative_path):
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(_experiment_script_resource(relative_path)) as path:
        shutil.copyfile(path, destination)
    if relative_path == "deploy.toml" and not _suppress_policy_review_marker.get():
        _mark_deployment_policy_for_review()
    return True


_DEPLOYMENT_POLICY_REVIEW_MARKER = Path(".deploy/deploy.toml.needs_review")
_suppress_policy_review_marker: ContextVar[bool] = ContextVar(
    "psynet_suppress_policy_review_marker", default=False
)


def _mark_deployment_policy_for_review() -> None:
    """Record that a newly created ``deploy.toml`` still needs a launch-time review."""
    marker = _DEPLOYMENT_POLICY_REVIEW_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "PsyNet created deploy.toml for this experiment. The next debug, test, "
        "or deploy command stops once so you can inspect the deployment plan "
        "with 'dallinger deployment-files list'. This file is local-only; "
        "you can delete it after that review.\n"
    )


def _deployment_policy_needs_review() -> bool:
    """Return whether the current ``deploy.toml`` still has a one-shot review marker."""
    return _DEPLOYMENT_POLICY_REVIEW_MARKER.is_file()


def _clear_deployment_policy_review_marker() -> None:
    """Remove the one-shot review marker if it is present."""
    marker = _DEPLOYMENT_POLICY_REVIEW_MARKER
    if marker.is_file():
        marker.unlink()
    parent = marker.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


@contextmanager
def _without_deployment_policy_review():
    """Skip the one-shot deploy.toml review for temporary or in-repo scaffolds."""
    token = _suppress_policy_review_marker.set(True)
    try:
        yield
    finally:
        _suppress_policy_review_marker.reset(token)
        _clear_deployment_policy_review_marker()


def ensure_deployment_policy() -> None:
    """Create ``deploy.toml`` from the PsyNet template when it is missing.

    Existing files are never overwritten. A newly written file also gets a
    local review marker so the next debug, test, or deploy command pauses
    once before copying files, unless the copy happens inside a temporary
    pytest scaffold or in-repo auto-prepare.
    """
    _assert_managed_path_is_safe("deploy.toml")
    _copy_template_file("deploy.toml", overwrite=False)


def _remove_obsolete_generated_dockerignore() -> bool:
    """Remove the obsolete generated Docker ignore file, preserving custom files.

    Returns
    -------
    bool
        True when the generated file was removed.
    """
    path = Path(".dockerignore")
    if not path.is_symlink() and not path.exists():
        return False
    try:
        generated = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        generated = None
    if generated is not None and tuple(generated) in _GENERATED_DOCKERIGNORE_VARIANTS:
        path.unlink()
        click.echo("Removed obsolete generated .dockerignore.")
        return True
    click.echo(
        "WARNING: Preserving custom .dockerignore. Its rules must be moved "
        "to deploy.toml and the file removed before debug or deployment.",
        err=True,
    )
    return False


def _remove_obsolete_generated_docker_scripts() -> bool:
    """Remove generated experiment-local Docker helper scripts.

    Known generated helper files are identified by content hash and deleted.
    Customized files and symlinks are preserved with a warning.

    Returns
    -------
    bool
        True when at least one generated helper path was removed.
    """
    docker_dir = Path("docker")
    if docker_dir.is_symlink():
        _warn_preserved_docker_symlink(docker_dir)
        return False
    if not docker_dir.exists():
        return False

    removed_any = False
    warned_symlinks: set[Path] = set()
    for relative_path in _OBSOLETE_DOCKER_SCRIPT_PATHS:
        path = Path(relative_path)
        symlink_parent = _first_symlink_parent(path)
        if symlink_parent is not None:
            if symlink_parent not in warned_symlinks:
                _warn_preserved_docker_symlink(symlink_parent)
                warned_symlinks.add(symlink_parent)
            continue
        if (
            path.is_file()
            and not path.is_symlink()
            and _is_obsolete_docker_script(path)
        ):
            path.unlink()
            removed_any = True

    for directory in (Path("docker/docs"), docker_dir):
        if directory.is_symlink():
            continue
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()

    if docker_dir.is_dir():
        click.echo(
            "WARNING: Preserving custom files in docker/. "
            "Recognized generated Docker helper scripts were removed when present; "
            "use 'psynet debug local' or 'psynet debug local --docker'.",
            err=True,
        )
    elif removed_any:
        click.echo("Removed obsolete generated docker/ helper scripts.")
    return removed_any


def _is_obsolete_docker_script(path: Path) -> bool:
    """Return whether ``path`` matches its final PsyNet-generated template."""
    expected_hash = _OBSOLETE_DOCKER_SCRIPT_HASHES.get(path.as_posix())
    if expected_hash is None:
        return False
    try:
        digest = hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == expected_hash


def _first_symlink_parent(relative_path: Path) -> Path | None:
    """Return the first symlink among parent components of ``relative_path``."""
    current = Path()
    for part in Path(relative_path).parts[:-1]:
        current /= part
        if current.is_symlink():
            return current
    return None


def _warn_preserved_docker_symlink(path: Path) -> None:
    """Warn that a docker/ path was left untouched because it is a symlink."""
    display = path.as_posix()
    if not display.endswith("/"):
        display = f"{display}/"
    click.echo(
        f"WARNING: Preserving {display} because it is a symlink. "
        "Generated Docker helper scripts are no longer used; "
        "use 'psynet debug local' or 'psynet debug local --docker'.",
        err=True,
    )


def _assert_managed_path_is_safe(relative_path):
    """Reject managed paths containing symlink components."""
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise click.UsageError(
            f"Refusing to manage unsafe scaffold path '{relative_path}'."
        )

    current = Path()
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise click.UsageError(
                f"Refusing to manage '{relative_path}' because '{current}' "
                "is a symlink."
            )


def _assert_scaffold_paths_are_safe(paths):
    """Validate scaffold destinations before making any changes."""
    paths = set(paths)
    for relative_path in paths:
        _assert_managed_path_is_safe(relative_path)

    for relative_path in _MANAGED_DIRECTORIES:
        if relative_path not in paths:
            continue
        directory = Path(relative_path)
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise click.UsageError(
                        f"Refusing to manage '{relative_path}' because '{path}' "
                        "is a symlink."
                    )


def _template_file_matches(relative_path):
    """Return whether an existing file matches its scaffold template."""
    destination = Path(relative_path)
    if not destination.is_file():
        return False

    with resources.as_file(_experiment_script_resource(relative_path)) as template:
        return destination.read_bytes() == template.read_bytes()


def _generated_file_matches(relative_path):
    """Return whether an existing generated file has its expected contents."""
    destination = Path(relative_path)
    return (
        destination.is_file()
        and destination.read_text() == _GENERATED_FILES[relative_path]()
    )


def _managed_path_matches_scaffold(relative_path):
    """Return whether a managed path still has its generated contents."""
    if relative_path in _TEMPLATE_FILES:
        return _template_file_matches(relative_path)
    if relative_path in _GENERATED_FILES:
        return _generated_file_matches(relative_path)
    if relative_path == _EXPERIMENT_SKILLS_DIRECTORY:
        return _experiment_skills_directory_matches()
    raise ValueError(f"Unknown scaffold-managed path: {relative_path}")


def _write_generated_file(relative_path, contents, overwrite):
    """Write one generated scaffold-managed file into the experiment directory."""
    destination = Path(relative_path)
    if destination.exists():
        if not overwrite:
            return False
        if destination.is_file() and destination.read_bytes() == contents.encode():
            return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contents)
    return True


def _remove_empty_parent_dirs(path):
    """Remove now-empty parent directories after deleting scaffold files."""
    workspace_root = Path.cwd().resolve()
    path = path.resolve()
    while path != workspace_root and path.exists():
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def _remove_empty_resource_directories():
    """Remove resource directories that contain no authored files."""
    for relative_path in _EMPTY_RESOURCE_DIRECTORIES:
        path = Path(relative_path)
        if not path.is_dir() or path.is_symlink():
            continue

        entries = list(path.iterdir())
        if relative_path == "static":
            disposable = all(
                entry.name == "assets" and entry.is_symlink() for entry in entries
            )
        else:
            disposable = all(
                entry.name == ".keep" and entry.is_file() and not entry.is_symlink()
                for entry in entries
            )
        if not disposable:
            continue

        for entry in entries:
            entry.unlink()
        path.rmdir()


def scaffold_experiment_directory(
    *,
    overwrite=False,
    skip_files=None,
):
    """Create or refresh the standard scaffold-managed experiment files.

    ``config.txt`` is part of the default scaffold and is created when missing,
    but existing copies are never overwritten (authors commonly customize them).
    """
    skip_files = set(skip_files or [])
    _assert_scaffold_paths_are_safe(
        (scaffold_managed_paths() | set(_BOOTSTRAP_FILES)) - skip_files
    )
    _remove_obsolete_generated_dockerignore()
    _remove_obsolete_generated_docker_scripts()

    written = []
    skipped = []

    try:
        bootstrap_written, bootstrap_skipped = _bootstrap_authored_files(skip_files)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    written.extend(bootstrap_written)
    skipped.extend(bootstrap_skipped)

    for relative_path in _TEMPLATE_FILES:
        if relative_path in skip_files:
            skipped.append(relative_path)
            continue

        if _copy_template_file(relative_path, overwrite):
            written.append(relative_path)
        else:
            skipped.append(relative_path)

    for relative_path, contents_factory in _GENERATED_FILES.items():
        if relative_path in skip_files:
            skipped.append(relative_path)
            continue

        if _write_generated_file(relative_path, contents_factory(), overwrite):
            written.append(relative_path)
        else:
            skipped.append(relative_path)

    if overwrite:
        # Remove obsolete directories only when they still match the old template.
        for directory, hash_ in _REMOVABLE_DIRECTORIES:
            if Path(directory).exists() and md5_directory(directory) == hash_:
                shutil.rmtree(directory)
                written.append(directory)

    skills_relative = _EXPERIMENT_SKILLS_DIRECTORY
    if skills_relative not in skip_files:
        if _update_experiment_skills(overwrite=overwrite):
            written.append(skills_relative)
        else:
            skipped.append(skills_relative)

    _report_scaffold_result(written, overwrite=overwrite)

    return {"written": written, "skipped": skipped}


def _update_experiment_skills(*, overwrite: bool = False) -> bool:
    """Install PsyNet-managed Agent Skills without touching user skills.

    The managed tree lives at ``.cursor/skills/psynet``. Other skill directories
    under ``.cursor/skills/`` are experiment-owned and are never modified.
    """
    target = Path(_EXPERIMENT_SKILLS_DIRECTORY)
    if target.exists() and not overwrite:
        return False

    source = _experiment_skills_source()
    if source is None:
        return False

    def _install_from(source_path: Path) -> bool:
        if (
            overwrite
            and target.is_dir()
            and md5_directory(target) == md5_directory(source_path)
        ):
            return False

        click.echo(f"...updating {target} directory.")
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, target)
        return True

    if isinstance(source, Path):
        return _install_from(source)

    with resources.as_file(source) as path:
        return _install_from(Path(path))


def _experiment_skills_source():
    """Return the Path or package resource for PsyNet-managed experiment skills."""
    # Editable PsyNet checkouts keep the canonical skills at the repository
    # root, where IDEs discover them for PsyNet development. Built wheels
    # force-include the same tree as a package resource for installed PsyNet.
    checkout_source = Path(__file__).resolve().parents[1] / ".cursor/skills/experiment"
    if checkout_source.is_dir():
        return checkout_source

    packaged_source = (
        resources.files("psynet")
        / "resources"
        / "experiment_scripts"
        / ".cursor"
        / "skills"
        / "psynet"
    )
    if packaged_source.is_dir():
        return packaged_source
    return None


def _experiment_skills_directory_matches() -> bool:
    """Return whether the copied experiment skills match the PsyNet source tree."""
    destination = Path(_EXPERIMENT_SKILLS_DIRECTORY)
    source = _experiment_skills_source()
    if not destination.is_dir() or source is None:
        return False
    if isinstance(source, Path):
        return md5_directory(destination) == md5_directory(source)
    with resources.as_file(source) as path:
        return md5_directory(destination) == md5_directory(Path(path))


def _scaffold_context_paths():
    """Return paths whose temporary additions should be removed after tests."""
    return (
        scaffold_managed_paths()
        | set(_BOOTSTRAP_FILES)
        | {
            "constraints.txt",
            "static/assets",
            _DEPLOYMENT_POLICY_REVIEW_MARKER.as_posix(),
        }
    )


def _snapshot_scaffold_context_paths():
    """Snapshot existing scaffold-context paths and their permission modes."""
    paths = set()
    modes = {}
    for relative_path in _scaffold_context_paths():
        path = Path(relative_path)
        if not path.exists() and not path.is_symlink():
            continue
        candidates = [path]
        if path.is_dir() and not path.is_symlink():
            candidates.extend(path.rglob("*"))
        for candidate in candidates:
            relative_candidate = candidate.as_posix()
            paths.add(relative_candidate)
            if not candidate.is_symlink():
                modes[relative_candidate] = stat.S_IMODE(candidate.stat().st_mode)
    return paths, modes


def _remove_new_scaffold_context_paths(original_paths):
    """Remove paths introduced within a scaffold context."""
    current_paths, _ = _snapshot_scaffold_context_paths()
    new_paths = current_paths - original_paths
    removal_roots = {
        relative_path
        for relative_path in new_paths
        if not any(
            parent.as_posix() in new_paths
            for parent in Path(relative_path).parents
            if parent != Path(".")
        )
    }
    for relative_path in sorted(
        removal_roots, key=lambda value: len(Path(value).parts), reverse=True
    ):
        path = Path(relative_path)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        _remove_empty_parent_dirs(path.parent)


def _restore_scaffold_context_modes(original_modes):
    """Restore permission modes changed while scaffolding."""
    for relative_path, mode in original_modes.items():
        path = Path(relative_path)
        if path.exists() and not path.is_symlink():
            path.chmod(mode)


@contextmanager
def scaffold_missing_files():
    """Temporarily scaffold missing files and restore the original tree on exit.

    Existing scaffold files and generated leftovers are left untouched. Files
    added by scaffolding or by the code running inside the context are removed
    only when they occupy scaffold-managed or generated-leftover paths.

    Yields
    ------
    dict
        The result returned by :func:`scaffold_experiment_directory`.
    """
    original_paths, original_modes = _snapshot_scaffold_context_paths()
    try:
        with _without_deployment_policy_review():
            yield scaffold_experiment_directory()
    finally:
        _remove_new_scaffold_context_paths(original_paths)
        _restore_scaffold_context_modes(original_modes)


# Shared Click help for the prune command (bootstrap + full CLI).
PRUNE_INCLUDE_MODIFIED_OPTION_HELP = (
    "Also delete scaffold paths that differ from current PsyNet templates."
)
PRUNE_INCLUDE_TRACKED_OPTION_HELP = (
    "Also delete git-tracked managed paths. By default, tracked paths are kept."
)
PRUNE_COMMAND_HELP = (
    "Remove scaffold-managed boilerplate and generated leftovers "
    "(static/assets, untracked constraints.txt).\n\n"
    "By default only unmodified, untracked scaffold paths are removed. "
    "--include-modified also removes divergent untracked scaffold paths. "
    "--include-tracked also removes git-tracked managed paths. "
    "Recognized generated docker/ helper scripts are deleted; customized "
    "copies are preserved."
)


def prune_experiment_scaffold(
    *, preserve_files=None, include_modified=False, include_tracked=False
):
    """Remove scaffold files and generated leftovers from an experiment directory.

    Parameters
    ----------
    preserve_files :
        Extra relative paths to leave untouched.
    include_modified :
        When true, also delete scaffold paths that differ from current templates.
        When false, divergent paths are preserved and reported.
    include_tracked :
        When true, also delete git-tracked managed paths. When false (default),
        tracked paths are preserved. Raises ``click.UsageError`` if this
        directory is a git work tree but tracked paths cannot be listed.

    Any pending ``deploy.toml`` review marker is dropped, because the policy it
    refers to is itself scaffold-managed.
    """
    root = Path(".")
    tracked = _git_tracked_paths(
        root, required=_is_git_work_tree(root) and not include_tracked
    )
    protected = set() if include_tracked else tracked
    preserve_files = set(preserve_files or []) | protected
    managed_paths = scaffold_managed_paths()
    _assert_scaffold_paths_are_safe(
        {
            relative_path
            for relative_path in managed_paths
            if not _path_is_tracked_or_has_tracked_contents(
                relative_path, preserve_files
            )
        }
    )
    preserved_unrecognized = []
    removed = []
    _clear_deployment_policy_review_marker()
    _remove_obsolete_generated_dockerignore()
    _remove_obsolete_generated_docker_scripts()

    for relative_path in sorted(
        managed_paths - set(_MANAGED_DIRECTORIES) - preserve_files
    ):
        path = Path(relative_path)
        if path.exists():
            matches_scaffold = _managed_path_matches_scaffold(relative_path)
            if not include_modified and not matches_scaffold:
                preserved_unrecognized.append(relative_path)
                continue
            path.unlink()
            removed.append(relative_path)
            _remove_empty_parent_dirs(path.parent)

    for relative_path in _MANAGED_DIRECTORIES:
        if _path_is_tracked_or_has_tracked_contents(relative_path, preserve_files):
            continue
        path = Path(relative_path)
        if path.exists():
            if not include_modified and not _managed_path_matches_scaffold(
                relative_path
            ):
                preserved_unrecognized.append(relative_path)
                continue
            shutil.rmtree(path)
            removed.append(relative_path)
            if relative_path == _EXPERIMENT_SKILLS_DIRECTORY:
                _remove_empty_parent_dirs(path.parent)

    preserved_tracked = sorted(
        relative_path
        for relative_path in managed_paths
        if _path_is_tracked_or_has_tracked_contents(relative_path, protected)
        and Path(relative_path).exists()
    )

    if removed:
        click.echo(
            "Removed scaffold-managed boilerplate: " + ", ".join(sorted(removed))
        )
    elif not preserved_unrecognized and not preserved_tracked:
        click.echo("Nothing to prune; no matching scaffold-managed files found.")

    if preserved_unrecognized:
        click.echo(
            "Preserved scaffold paths that differ from current PsyNet templates:"
        )
        for relative_path in sorted(preserved_unrecognized):
            click.echo(f"  - {relative_path}")
        click.echo(
            "These paths may be customized or generated by another PsyNet version."
        )
        click.echo(
            "If you are sure you want to delete them, run "
            "'psynet scripts prune --include-modified'."
        )

    # Generated leftovers: always safe to drop from authored-only / local trees.
    removed_assets = _remove_generated_static_assets(root)
    removed_constraints = False
    constraints = root / "constraints.txt"
    if constraints.exists() and (include_tracked or "constraints.txt" not in tracked):
        constraints.unlink()
        removed_constraints = True

    _remove_empty_resource_directories()

    return {
        "preserved_unrecognized": preserved_unrecognized,
        "preserved_tracked": preserved_tracked,
        "removed": removed,
        "removed_assets": removed_assets,
        "removed_constraints": removed_constraints,
    }


def run_scripts_prune(*, include_modified=False, include_tracked=False):
    """Validate the experiment directory and prune scaffold-managed files.

    Shared by the bootstrap and full CLIs so prune options/behavior stay aligned.
    """
    _ensure_experiment_directory_for_scripts()
    return prune_experiment_scaffold(
        include_modified=include_modified, include_tracked=include_tracked
    )


def _ensure_experiment_directory_for_scripts():
    """Raise ``click.UsageError`` unless cwd is a valid experiment directory."""
    from psynet.light_utils import (
        ExperimentDirectoryNameError,
        ensure_experiment_directory_name_does_not_conflict,
    )

    try:
        ensure_experiment_directory_name_does_not_conflict()
    except ExperimentDirectoryNameError as e:
        raise click.UsageError(str(e)) from e
    if not Path("experiment.py").is_file():
        raise click.UsageError(
            "The current directory is not a valid PsyNet experiment "
            "(missing experiment.py)."
        )


def _path_is_tracked_or_has_tracked_contents(
    relative_path: str, tracked: set[str]
) -> bool:
    """Return whether ``relative_path`` or any nested path is in ``tracked``."""
    if relative_path in tracked:
        return True
    prefix = relative_path.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in tracked)


def _is_git_work_tree(root: Path) -> bool:
    """Return whether ``root`` is inside a git work tree."""
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return output.decode().strip() == "true"


def _git_tracked_paths(root: Path, *, required: bool = False) -> set[str]:
    """Return git-tracked paths under ``root``, relative to ``root``.

    Parameters
    ----------
    required :
        When true, raise ``click.UsageError`` if tracked paths cannot be listed
        (for example when git is missing or the directory is not a repository).
    """
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z", "."],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if required:
            raise click.UsageError(
                "Prune needs to list git-tracked files so it does not delete "
                "authored paths. Listing tracked files failed; fix git or pass "
                "--include-tracked if you intentionally want tracked managed "
                "paths removed."
            ) from exc
        return set()
    return {path.decode() for path in output.split(b"\0") if path}


def _remove_generated_static_assets(root: Path) -> bool:
    """Remove generated ``static/assets`` and an empty ``static/`` directory."""
    assets = root / "static" / "assets"
    removed = False
    if assets.is_symlink() or assets.is_file():
        assets.unlink()
        removed = True
    elif assets.is_dir():
        shutil.rmtree(assets)
        removed = True

    static_directory = root / "static"
    if static_directory.is_dir() and not any(static_directory.iterdir()):
        static_directory.rmdir()
        removed = True
    return removed
