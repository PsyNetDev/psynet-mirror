import re
from pathlib import Path

from psynet.dallinger_dependency import dallinger_constraints_github_ref
from psynet.dev import ci as ci_module

ROOT = Path(__file__).resolve().parents[2]
DALLINGER_CONSTRAINTS = ROOT / "ci" / "dallinger-dev-requirements.txt"


def test_vendored_dallinger_constraints_match_pyproject_dependency():
    ref = dallinger_constraints_github_ref()
    constraints = DALLINGER_CONSTRAINTS.read_text(encoding="utf-8")
    snapshot_ref = re.search(
        r"^# PsyNet CI snapshot for Dallinger ref: (\S+)$",
        constraints,
        flags=re.MULTILINE,
    ).group(1)
    source_ref = re.search(
        r"^# Source: https://raw\.githubusercontent\.com/Dallinger/Dallinger/"
        r"(\S+)/dev-requirements\.txt$",
        constraints,
        flags=re.MULTILINE,
    ).group(1)

    assert snapshot_ref == ref
    assert source_ref == ref
    assert (
        re.search(r"^dallinger(?:\[.*\])?\s*[=@<]", constraints, re.MULTILINE) is None
    )


def _run_update_command(tmp_path, monkeypatch, pyproject_text):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(pyproject_text, encoding="utf-8")
    constraints = tmp_path / "ci" / "dallinger-dev-requirements.txt"
    constraints.parent.mkdir()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG PYTHON_VERSION=3.13\n", encoding="utf-8")
    compile_checks = []
    downloaded_urls = []

    def fake_download(url):
        downloaded_urls.append(url)
        return "# Dallinger generated header\nrequests==2.33.1\n"

    monkeypatch.setattr(ci_module, "PYPROJECT_PATH", pyproject)
    monkeypatch.setattr(ci_module, "DOCKERFILE_PATH", dockerfile)
    monkeypatch.setattr(ci_module, "DALLINGER_CONSTRAINTS_PATH", constraints)
    monkeypatch.setattr(ci_module, "_download_text", fake_download)
    monkeypatch.setattr(
        ci_module,
        "_check_docker_constraints_compile",
        lambda pyproject_path, constraints_path, dockerfile_path: compile_checks.append(
            (pyproject_path, constraints_path, dockerfile_path)
        ),
    )

    assert ci_module.update_dallinger_constraints_command() == 0
    return (
        constraints.read_text(encoding="utf-8"),
        compile_checks,
        downloaded_urls,
        pyproject,
        dockerfile,
    )


def test_update_dallinger_constraints_command_writes_header_and_validates(
    tmp_path, monkeypatch
):
    text, compile_checks, downloaded_urls, pyproject, dockerfile = _run_update_command(
        tmp_path,
        monkeypatch,
        """
[project]
dependencies = [
    "dallinger[docker]>=12.2.0,<13",
]
""",
    )

    assert downloaded_urls == [
        "https://raw.githubusercontent.com/Dallinger/Dallinger/v12.2.0/dev-requirements.txt"
    ]
    assert text.startswith(
        "# PsyNet CI snapshot for Dallinger ref: v12.2.0\n"
        "# Source: https://raw.githubusercontent.com/Dallinger/Dallinger/v12.2.0/dev-requirements.txt\n"
    )
    assert text.endswith("# Dallinger generated header\nrequests==2.33.1\n")
    constraints = tmp_path / "ci" / "dallinger-dev-requirements.txt"
    assert compile_checks == [(pyproject, constraints, dockerfile)]


def test_update_dallinger_constraints_command_uses_git_sha_pin(tmp_path, monkeypatch):
    sha = "0123456789abcdef0123456789abcdef01234567"
    text, compile_checks, downloaded_urls, pyproject, dockerfile = _run_update_command(
        tmp_path,
        monkeypatch,
        f"""
[project]
dependencies = []
[project.optional-dependencies]
experiment = ["dallinger[docker] @ git+https://github.com/Dallinger/Dallinger.git@{sha}"]
""",
    )

    url = (
        f"https://raw.githubusercontent.com/Dallinger/Dallinger/{sha}/"
        "dev-requirements.txt"
    )
    assert downloaded_urls == [url]
    assert text.startswith(
        f"# PsyNet CI snapshot for Dallinger ref: {sha}\n# Source: {url}\n"
    )
    constraints = tmp_path / "ci" / "dallinger-dev-requirements.txt"
    assert compile_checks == [(pyproject, constraints, dockerfile)]


def test_render_strips_legacy_and_current_snapshot_headers():
    legacy = (
        "# PsyNet CI snapshot for Dallinger release: v12.2.0\n"
        "# Source: https://raw.githubusercontent.com/Dallinger/Dallinger/v12.2.0/dev-requirements.txt\n"
        "# Keep this version aligned with PsyNet's Dallinger dependency in pyproject.toml.\n"
        "#\n"
        "requests==2.33.1\n"
    )
    current = ci_module._render_dallinger_constraints_snapshot("v12.3.0", legacy)
    assert current.startswith(
        "# PsyNet CI snapshot for Dallinger ref: v12.3.0\n"
        "# Source: https://raw.githubusercontent.com/Dallinger/Dallinger/v12.3.0/dev-requirements.txt\n"
    )
    assert current.count("requests==2.33.1") == 1
    assert "v12.2.0" not in current

    rerendered = ci_module._render_dallinger_constraints_snapshot("v12.4.0", current)
    assert "v12.3.0" not in rerendered
    assert rerendered.startswith("# PsyNet CI snapshot for Dallinger ref: v12.4.0\n")


def test_get_docker_python_version(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG DOCKER_PLATFORM=linux/amd64\nARG PYTHON_VERSION=3.13\n",
        encoding="utf-8",
    )

    assert ci_module._get_docker_python_version(dockerfile) == "3.13"


def test_docker_constraints_compile_checks_all_supported_versions(
    tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\ndependencies = []\n", encoding="utf-8")
    constraints = tmp_path / "dallinger-dev-requirements.txt"
    constraints.write_text("requests==2.33.1\n", encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("ARG PYTHON_VERSION=3.13\n", encoding="utf-8")

    compiled_versions = []

    def fake_run(command, cwd, check):
        compiled_versions.append(command[command.index("--python-version") + 1])

    monkeypatch.setattr(ci_module.subprocess, "run", fake_run)

    ci_module._check_docker_constraints_compile(
        pyproject, constraints, dockerfile, python_versions=("3.11", "3.12", "3.13")
    )

    assert compiled_versions == ["3.11", "3.12", "3.13"]
