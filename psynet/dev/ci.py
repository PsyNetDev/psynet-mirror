"""Maintain vendored inputs used by CI.

PsyNet's Docker image needs a ``constraints.txt`` file before the package itself
is installed. The image builds this file from PsyNet's ``pyproject.toml`` plus
Dallinger's tested dependency pins. Dallinger publishes these pins as
``dev-requirements.txt`` in the Dallinger repository.

Originally the Docker build fetched Dallinger's constraints helper directly from
GitHub. That made parallel CI builds depend on several live network calls to
``raw.githubusercontent.com``.

To keep Docker builds reproducible and less sensitive to transient GitHub
timeouts, PsyNet vendors the relevant Dallinger ``dev-requirements.txt`` snapshot
in ``ci/dallinger-dev-requirements.txt``. Docker copies this local file and runs
``uv pip compile`` against it. The file has a PsyNet-specific provenance header
recording the Dallinger git ref it came from (a release tag or commit SHA).

When PsyNet upgrades its Dallinger dependency, maintainers should run
``psynet dev ci update-dallinger-constraints`` from the repository root. This
module downloads the matching Dallinger snapshot, rewrites the provenance header,
and validates that Docker's constraints compile command still succeeds.

Dallinger's pins don't cover every package that ``psynet[experiment]`` installs.
``psynet/resources/experiment_constraints.txt`` pins the rest, at the versions
PsyNet was tested with. Experiments compile their ``constraints.txt`` against it
as well as Dallinger's pins (see :mod:`psynet.constraints_compile`), and the
Docker image does the same, so CI tests those versions. The file is derived from
the Dallinger snapshot, so ``update-dallinger-constraints`` refreshes it too.
Maintainers upgrade its versions with
``psynet dev ci update-experiment-constraints --upgrade`` when releasing.
"""

import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from psynet.constraints_compile import PSYNET_CONSTRAINTS_PATH
from psynet.dallinger_dependency import dallinger_constraints_github_ref
from psynet.version import supported_python_major_minor_versions

PYPROJECT_PATH = Path("pyproject.toml")
DOCKERFILE_PATH = Path("Dockerfile")
DALLINGER_CONSTRAINTS_PATH = Path("ci/dallinger-dev-requirements.txt")
DALLINGER_CONSTRAINTS_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Dallinger/Dallinger/{ref}/dev-requirements.txt"
)
EXPERIMENT_CONSTRAINTS_PATH = Path(PSYNET_CONSTRAINTS_PATH)


def update_dallinger_constraints_command(check_compile: bool = True) -> int:
    """Refresh the vendored Dallinger constraints snapshot and PsyNet's lockfile."""
    ref = dallinger_constraints_github_ref(PYPROJECT_PATH)
    url = DALLINGER_CONSTRAINTS_URL_TEMPLATE.format(ref=ref)
    content = _download_text(url)
    rendered = _render_dallinger_constraints_snapshot(ref, content)
    DALLINGER_CONSTRAINTS_PATH.write_text(rendered, encoding="utf-8")
    write_experiment_constraints(
        PYPROJECT_PATH, DALLINGER_CONSTRAINTS_PATH, EXPERIMENT_CONSTRAINTS_PATH
    )

    if check_compile:
        _check_docker_constraints_compile(
            PYPROJECT_PATH,
            DALLINGER_CONSTRAINTS_PATH,
            EXPERIMENT_CONSTRAINTS_PATH,
            DOCKERFILE_PATH,
        )

    print(
        f"Updated {DALLINGER_CONSTRAINTS_PATH} from {url} "
        f"and {EXPERIMENT_CONSTRAINTS_PATH}"
    )
    return 0


def update_experiment_constraints_command(
    upgrade: bool = False, check_compile: bool = True
) -> int:
    """Refresh the pins for experiment packages that Dallinger doesn't pin."""
    write_experiment_constraints(
        PYPROJECT_PATH,
        DALLINGER_CONSTRAINTS_PATH,
        EXPERIMENT_CONSTRAINTS_PATH,
        upgrade=upgrade,
    )
    if check_compile:
        _check_docker_constraints_compile(
            PYPROJECT_PATH,
            DALLINGER_CONSTRAINTS_PATH,
            EXPERIMENT_CONSTRAINTS_PATH,
            DOCKERFILE_PATH,
        )
    print(f"Updated {EXPERIMENT_CONSTRAINTS_PATH}")
    return 0


def write_experiment_constraints(
    pyproject_path: Path,
    dallinger_constraints_path: Path,
    output_path: Path,
    upgrade: bool = False,
) -> None:
    """Pin the ``experiment`` extra's packages that Dallinger's snapshot doesn't.

    Without ``upgrade``, versions already in ``output_path`` are kept where
    they still resolve, so only added or removed packages change.
    """
    excluded = _package_names(dallinger_constraints_path.read_text(encoding="utf-8"))
    excluded |= {"dallinger", "psynet"}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shutil.copy(pyproject_path, tmp_path / "pyproject.toml")
        compiled = tmp_path / "compiled.txt"
        if output_path.is_file() and not upgrade:
            shutil.copy(output_path, compiled)
        subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--quiet",
                "--no-python-downloads",
                "--universal",
                "--python-version",
                _latest_cpython_patch(supported_python_major_minor_versions[0]),
                "pyproject.toml",
                "--extra",
                "experiment",
                "--constraint",
                str(dallinger_constraints_path.resolve()),
                "--no-header",
                "--no-annotate",
                *(["--upgrade"] if upgrade else []),
                "--output-file",
                "compiled.txt",
            ],
            cwd=tmp_path,
            check=True,
        )
        pins = [
            line
            for line in compiled.read_text(encoding="utf-8").splitlines()
            if _package_name(line) not in excluded | {None}
        ]

    ref = dallinger_constraints_github_ref(pyproject_path)
    header = (
        "# Tested versions of the psynet[experiment] packages that Dallinger's\n"
        "# dev-requirements.txt doesn't pin. Experiments compile constraints.txt\n"
        "# against this file as well as Dallinger's pins.\n"
        f"# Dallinger ref: {ref}\n"
        "# Regenerate with `psynet dev ci update-experiment-constraints`.\n"
    )
    output_path.write_text(header + "".join(f"{pin}\n" for pin in pins), "utf-8")


def _package_name(line: str) -> str | None:
    """Return the normalized package name of a requirements line, if any."""
    match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line.strip())
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


def _package_names(requirements: str) -> set[str]:
    """Return the normalized package names in a requirements file's text."""
    return {_package_name(line) for line in requirements.splitlines()} - {None}


def _download_text(url: str) -> str:
    """Download a UTF-8 text file."""
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read().decode("utf-8")


def _get_docker_python_version(dockerfile_path: Path) -> str:
    """Return the Python version used by the Docker image."""
    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    match = re.search(r"^ARG PYTHON_VERSION=([^\s]+)$", dockerfile, flags=re.MULTILINE)
    if match is None:
        raise ValueError("Could not find ARG PYTHON_VERSION in Dockerfile.")
    return match.group(1)


def _render_dallinger_constraints_snapshot(ref: str, content: str) -> str:
    """Prepend PsyNet provenance metadata to Dallinger's constraints content."""
    content = _strip_psynet_snapshot_header(content)
    url = DALLINGER_CONSTRAINTS_URL_TEMPLATE.format(ref=ref)
    header = (
        f"# PsyNet CI snapshot for Dallinger ref: {ref}\n"
        f"# Source: {url}\n"
        "# Keep this aligned with PsyNet's Dallinger dependency in pyproject.toml.\n"
        "#\n"
    )
    return header + content.lstrip()


def _strip_psynet_snapshot_header(content: str) -> str:
    """Remove an existing PsyNet snapshot header if present."""
    pattern = re.compile(
        r"\A"
        r"# PsyNet CI snapshot for Dallinger (?:release: v\d+\.\d+\.\d+|ref: \S+)\n"
        r"# Source: https://raw\.githubusercontent\.com/Dallinger/Dallinger/"
        r"\S+/dev-requirements\.txt\n"
        r"# Keep this (?:version )?aligned with PsyNet's Dallinger dependency in "
        r"pyproject\.toml\.\n"
        r"#\n"
    )
    return pattern.sub("", content, count=1)


def _latest_cpython_patch(series: str) -> str:
    """Return the newest CPython patch release in *series* that uv knows about.

    ``uv pip compile --python-version 3.11`` resolves for Python 3.11.0, but the
    ``python:3.11`` Docker image ships the latest 3.11 patch.
    """
    raw = subprocess.check_output(
        ["uv", "python", "list", series, "--all-versions", "--output-format", "json"],
        text=True,
    )
    release = re.compile(rf"{re.escape(series)}\.\d+")
    versions = [
        tuple(int(part) for part in row["version"].split("."))
        for row in json.loads(raw)
        if row.get("implementation") == "cpython"
        and row.get("variant") in (None, "default")
        and release.fullmatch(row.get("version") or "")
    ]
    if not versions:
        raise ValueError(f"uv did not report a CPython {series} patch release.")
    return ".".join(str(part) for part in max(versions))


def _check_docker_constraints_compile(
    pyproject_path: Path,
    dallinger_constraints_path: Path,
    experiment_constraints_path: Path,
    dockerfile_path: Path,
    python_versions=supported_python_major_minor_versions,
) -> None:
    """Validate the vendored constraints for every supported Python version.

    Each version is checked at its latest patch release, as the Docker image
    for that version ships it.
    """
    default_python_version = _get_docker_python_version(dockerfile_path)
    if default_python_version not in python_versions:
        raise ValueError(
            f"Docker's default Python {default_python_version} is not supported."
        )

    for python_version in python_versions:
        patch_version = _latest_cpython_patch(python_version)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "pyproject.toml").write_text(
                pyproject_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (tmp_path / "dallinger-dev-requirements.txt").write_text(
                dallinger_constraints_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            shutil.copy(
                experiment_constraints_path, tmp_path / "experiment_constraints.txt"
            )
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "compile",
                    "--no-python-downloads",
                    "--python-version",
                    patch_version,
                    "pyproject.toml",
                    "--extra",
                    "experiment",
                    "--extra",
                    "test",
                    "--extra",
                    "demos",
                    "--constraint",
                    "dallinger-dev-requirements.txt",
                    "--constraint",
                    "experiment_constraints.txt",
                    "--output-file",
                    "constraints.txt",
                ],
                cwd=tmp_path,
                check=True,
            )
