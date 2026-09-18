import os
import re
import subprocess

import click

psynet_version = "13.4.0a0"

# Specify Dallinger MAJOR.MINOR version to allow any patch in that series
recommended_dallinger_major_minor = "12.3"

recommended_python_major_minor = "3.13"
supported_python_major_minor_versions = ("3.11", "3.12", "3.13", "3.14")


def _get_dallinger_version() -> str:
    """Return the installed Dallinger version (lazy-imported)."""
    from dallinger.version import __version__ as dallinger_version

    return dallinger_version


def check_core_dependency_versions_match_requirements():
    """
    Check whether PsyNet and Dallinger versions match requirements.txt.

    Raises
    ------
    ValueError
        If any specified package version does not match the installed version.
    """
    if os.environ.get("SKIP_VERSION_CHECK"):
        print(
            "SKIP_VERSION_CHECK is set so we will skip checking PsyNet versions specified vs. installed."
        )
        return

    # yaspin lives in psynet[experiment]; keep this import lazy so thin
    # bootstrap can import ``psynet_version`` without the spinner package.
    from yaspin import yaspin

    skip_messages = []
    with yaspin(
        text="Checking whether PsyNet and Dallinger versions specified and installed are the same...",
        color="green",
    ) as spinner:
        with open("requirements.txt", "r") as file:
            versions = collect_core_dependency_version_info_from_requirements(
                file.read()
            )

            for package_name, version_infos in versions.items():
                status = version_infos["status"]

                if status == "consistent":
                    spinner.ok("✔")
                elif status == "skipped":
                    spinner.ok("✔")
                    skip_reason = version_infos.get("skip_reason")
                    if skip_reason:
                        skip_messages.append(
                            f"Skipped version check for {package_name}: {skip_reason}"
                        )
                else:
                    spinner.color = "red"
                    spinner.fail("✗")

                    raise ValueError(
                        f"The {package_name} versions installed on your local computer and specified in requirements.txt do not match.\n"
                        f"\nVersion installed locally: {version_infos['installed']}"
                        f"\nVersion specified in requirements.txt: {version_infos['specified']}"
                        "\n\nYou can skip this check by writing `export SKIP_VERSION_CHECK=1` (without quotes) in your terminal."
                    )

    for message in skip_messages:
        click.echo(message)


def collect_core_dependency_version_info_from_requirements(file_content):
    """
    Parse requirements.txt content and compare to installed versions.

    Parameters
    ----------
    file_content : str
        Contents of a requirements.txt file.
    Returns
    -------
    dict
        Mapping of package name to a dict containing ``specified``, ``installed``,
        ``status`` (``consistent``, ``inconsistent``, or ``skipped``), and an optional
        ``skip_reason``.
    """
    versions = {}
    for package_name in ["Dallinger", "PsyNet"]:
        versions[package_name] = {
            "specified": None,
            "installed": None,
            "status": "consistent",
            "skip_reason": None,
        }
        specified = None
        installed = None

        # Collect requirements omitting commented lines
        requirements = [
            line
            for line in file_content.splitlines()
            if package_name.lower() in line and not line.strip().startswith("#")
        ]

        if len(requirements) == 0:
            continue

        requirement = requirements[0]

        match = re.search(
            f"/{package_name}(?:\\.git)?@([^#]+)(?:#egg={package_name})?",
            requirement,
            re.IGNORECASE,
        )

        # We either assume PsyNet is specified in the correct requirement syntax
        # or as a standard requirement (e.g. 'psynet==10.0.0')
        specified = (
            match.group(1) if match is not None else re.split("==", requirement)[-1]
        )

        # In case just specified as the package name
        if specified == package_name.lower():
            continue

        if is_release_version_specifier(specified):
            if specified.startswith("v"):
                specified = specified[1:]
            # Get installed version via the Dallinger/PsyNet API
            installed = get_installed_version_for_package(package_name)
        else:
            # Get installed version from `pip freeze`
            installed = get_installed_commit_or_version_from_pip_freeze(package_name)

        if is_development_version(installed):
            # It's hard to check consistency when the installed version is a development version,
            # because a development version could correspond to many possible branches/commits.
            # We therefore skip the comparison and continue.
            status = "skipped"
            skip_reason = "installed version is a development version"
        else:
            status = (
                "consistent"
                if specified is None or specified == installed
                else "inconsistent"
            )
            skip_reason = None
        versions[package_name] = {
            "specified": specified,
            "installed": installed,
            "status": status,
            "skip_reason": skip_reason,
        }
    return versions


def is_release_version_specifier(specified):
    return (
        specified.startswith("v")
        or re.search(r"^\d+\.\d+\.\d+(?:rc\d+)?$", specified) is not None
    )


def is_development_version(version):
    """
    Check whether a version string is a development version.

    A development version is defined as three numbers (major.minor.patch)
    followed by a letter and then numbers, e.g. "13.2.0a0a0".

    Parameters
    ----------
    version : str
        Version string to check

    Returns
    -------
    bool
        True if the version is a development version, False otherwise
    """
    return re.search(r"^\d+\.\d+\.\d+[a-zA-Z]\d+$", version) is not None


def get_installed_version_for_package(package_name):
    """Return the installed version string for PsyNet or Dallinger."""
    import psynet

    if package_name == "Dallinger":
        return _get_dallinger_version()
    if package_name == "PsyNet":
        return psynet.__version__
    raise ValueError(f"Unsupported package '{package_name}'")


def get_requirement_line_from_pip_freeze(name):
    # Use pip freeze because it shows git URLs with commit hashes,
    # unlike metadata.version().
    pip_freeze_stdout = subprocess.run(
        ["pip freeze"],
        shell=True,
        capture_output=True,
    ).stdout

    # Find line corresponding to this package in pip freeze output.
    # This line could have one of the following formats:
    #   "psynet==1.0.0"
    #   "psynet @ git+https://..."
    #   "psynet[extra]==1.0.0"
    #   "-e git+https://...#egg=psynet"
    #
    # Regex breakdown:
    #   ^(?:-e\s+)?           - Start of line, optionally prefixed with "-e " (editable)
    #   {name}                - The package name (escaped for regex safety)
    #   (?:\s*[@=\[]|$)       - Followed by " @", "=", "[", or end of line
    #   |                     - OR
    #   #egg={name}(?:\s|$)   - "#egg=<name>" followed by whitespace or end of line
    pattern = re.compile(
        rf"^(?:-e\s+)?{re.escape(name)}(?:\s*[@=\[]|$)|#egg={re.escape(name)}(?:\s|$)",
        re.IGNORECASE,
    )

    for line in pip_freeze_stdout.decode().splitlines():
        if pattern.search(line):
            return line

    raise ValueError(f"Package '{name}' not found in pip freeze")


def get_installed_commit_or_version_from_pip_freeze(package_name):
    """Return the installed commit hash or version from pip freeze output."""
    line = get_requirement_line_from_pip_freeze(package_name)
    match = re.search(f".*{package_name}(?:\\.git)?@([^#]*)", line, re.IGNORECASE)
    if match is not None:
        return match.group(1)
    return line.split("==")[-1]


def parse_version_triplet(x):
    """Parse a version string into a (major, minor, patch) integer tuple."""
    parts = x.split(".")
    assert len(parts) == 3, f"Invalid version specifier: {x}"

    major, minor, patch = parts

    # Strip anything that comes after a letter, so that e.g. 9.4.0a1 -> "9.4.0"
    patch = re.sub("[a-zA-Z].*", "", patch)

    return int(major), int(minor), int(patch)


def is_version_greater(x, y, strict: bool = True):
    """
    Returns True if version number x is (strictly) greater than version number y.
    """
    x_parsed = parse_version_triplet(x)
    y_parsed = parse_version_triplet(y)

    for x_i, y_i in zip(x_parsed, y_parsed):
        if x_i < y_i:
            return False
        elif x_i > y_i:
            return True
    if strict:
        return False
    else:
        return True


def check_installed_dallinger_version_is_recommended():
    """Warn or abort if the installed Dallinger version is not the recommended one."""
    import dallinger

    current_dallinger_version = dallinger.version.__version__
    # Accept any patch in the recommended MAJOR.MINOR version series
    if not current_dallinger_version.startswith(
        f"{recommended_dallinger_major_minor}."
    ):
        message = (
            f"The current installed version of Dallinger ({current_dallinger_version}) "
            f"is not the one recommended for this version of PsyNet. (PsyNet v{psynet_version} "
            f"recommends any patch in the {recommended_dallinger_major_minor}.x series). "
            "You can fix this problem by updating your requirements.txt file "
            f"to state dallinger~={recommended_dallinger_major_minor}, then running the following in your terminal:\n"
            "    psynet generate-constraints && pip uninstall dallinger && pip install -r constraints.txt\n"
        )
        if os.environ.get("PYTEST_CURRENT_TEST"):
            raise RuntimeError(message)
        message += "If you want to continue anyway, type 'y' and press enter."
        if click.confirm(message, default=False):
            return
        else:
            raise click.Abort
