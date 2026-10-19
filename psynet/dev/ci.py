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
"""

import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from psynet.dallinger_dependency import dallinger_constraints_github_ref
from psynet.version import supported_python_major_minor_versions

PYPROJECT_PATH = Path("pyproject.toml")
DOCKERFILE_PATH = Path("Dockerfile")
DALLINGER_CONSTRAINTS_PATH = Path("ci/dallinger-dev-requirements.txt")
DALLINGER_CONSTRAINTS_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Dallinger/Dallinger/{ref}/dev-requirements.txt"
)


def update_dallinger_constraints_command(check_compile: bool = True) -> int:
    """Refresh the vendored Dallinger constraints snapshot."""
    ref = dallinger_constraints_github_ref(PYPROJECT_PATH)
    url = DALLINGER_CONSTRAINTS_URL_TEMPLATE.format(ref=ref)
    content = _download_text(url)
    rendered = _render_dallinger_constraints_snapshot(ref, content)
    DALLINGER_CONSTRAINTS_PATH.write_text(rendered, encoding="utf-8")

    if check_compile:
        _check_docker_constraints_compile(
            PYPROJECT_PATH, DALLINGER_CONSTRAINTS_PATH, DOCKERFILE_PATH
        )

    print(f"Updated {DALLINGER_CONSTRAINTS_PATH} from {url}")
    return 0


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


def _check_docker_constraints_compile(
    pyproject_path: Path,
    dallinger_constraints_path: Path,
    dockerfile_path: Path,
    python_versions=supported_python_major_minor_versions,
) -> None:
    """Validate the vendored constraints for every supported Python version."""
    default_python_version = _get_docker_python_version(dockerfile_path)
    if default_python_version not in python_versions:
        raise ValueError(
            f"Docker's default Python {default_python_version} is not supported."
        )

    for python_version in python_versions:
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
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "compile",
                    "--python-version",
                    python_version,
                    "pyproject.toml",
                    "--extra",
                    "experiment",
                    "--extra",
                    "demos",
                    "--constraint",
                    "dallinger-dev-requirements.txt",
                    "--output-file",
                    "constraints.txt",
                ],
                cwd=tmp_path,
                check=True,
            )
