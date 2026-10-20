import contextlib
import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import click

psynet_version = "14.0.0rc3"

# Specify Dallinger MAJOR.MINOR version to allow any patch in that series
recommended_dallinger_major_minor = "12.4"

recommended_python_major_minor = "3.14"
supported_python_major_minor_versions = ("3.11", "3.12", "3.13", "3.14")


def _get_dallinger_version() -> str:
    """Return the installed Dallinger version (lazy-imported)."""
    from dallinger.version import __version__ as dallinger_version

    return dallinger_version


def check_core_dependency_versions_match_requirements(skip=()):
    """
    Check that the installed PsyNet and Dallinger match the versions the deployment installs.

    Each package is compared with its exact pin in ``requirements.txt`` or,
    failing that, ``constraints.txt`` (where ``psynet setup`` pins Dallinger).
    One line per package reports what was compared.

    Parameters
    ----------
    skip : collection of str
        Lowercase names of packages (``"psynet"``, ``"dallinger"``) not to check.

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

    with spinner("Comparing installed PsyNet and Dallinger with their pins..."):
        with open("requirements.txt", "r") as file:
            requirements = file.read()
        constraints_path = Path("constraints.txt")
        constraints = (
            constraints_path.read_text() if constraints_path.is_file() else None
        )
        versions = collect_core_dependency_version_info_from_requirements(
            requirements, skip=skip, constraints_content=constraints
        )

    for package_name, info in versions.items():
        source = info.get("source", "requirements.txt")
        if info["status"] == "inconsistent":
            click.echo(
                f"✗ {package_name}: installed {_short(info['installed'])} does not "
                f"match {source} ({_short(info['specified'])})"
            )
            raise ValueError(
                f"The {package_name} versions installed on your local computer and specified in {source} do not match.\n"
                f"\nVersion installed locally: {info['installed']}"
                f"\nVersion specified in {source}: {info['specified']}"
                f"{_mismatch_hint(package_name, info)}"
                "\n\nYou can skip this check by writing `export SKIP_VERSION_CHECK=1` (without quotes) in your terminal."
            )
        if info["status"] == "skipped":
            click.echo(
                f"Skipped version check for {package_name}: {info['skip_reason']}"
            )
        elif info["specified"] is None:
            click.echo(
                f"✔ {package_name}: no exact pin in requirements.txt or "
                "constraints.txt, so not compared"
            )
        else:
            click.echo(
                f"✔ {package_name}: installed {_short(info['installed'])} matches "
                f"{source} ({_short(info['specified'])})"
            )
    for info in versions.values():
        if info.get("warning"):
            click.secho(f"Warning: {info['warning']}", fg="yellow", err=True)


def spinner(text):
    """Return a green yaspin spinner on a terminal, or a no-op context manager otherwise.

    Off a terminal the context manager yields ``None``, so callers must check
    before calling ``ok`` or ``fail``.
    """
    if not sys.stdout.isatty():
        return contextlib.nullcontext()
    # yaspin lives in psynet[experiment]; keep this import lazy so thin
    # bootstrap can import ``psynet_version`` without the spinner package.
    from yaspin import yaspin

    return yaspin(text=text, color="green")


def _short(version):
    """Abbreviate a full commit hash for display; leave versions unchanged."""
    if version and re.fullmatch(r"[0-9a-fA-F]{40}", version):
        return f"commit {version[:12]}"
    return version


def _mismatch_hint(package_name, info):
    """Explain how to resolve a version mismatch."""
    from psynet.experiment_scaffold import get_editable_source

    source = get_editable_source(package_name)
    if source is None:
        return (
            f"\n\nInstall the {package_name} version pinned in {info['source']} "
            "with `psynet setup`."
        )
    return (
        f"\n\nThe deployment will run {package_name} {_short(info['specified'])} "
        f"(pinned in {info['source']}), but you have editable {package_name} at "
        f"{_short(info['installed'])} ({source}). For a debug deployment, use "
        f"'psynet debug ssh --use-local-{package_name.lower()}' to build your "
        f"checkout into the image; otherwise update the {package_name} pin or "
        f"install the pinned version."
    )


def _exact_pin(content, package_name):
    """Return ``(specified, kind)`` for the first exact pin of ``package_name`` in ``content``.

    ``kind`` is ``"version"`` for ``==`` pins and Git release tags, and
    ``"commit"`` for Git commit hashes. Bare names, ranges such as
    ``dallinger~=12.4`` and Git branches are not exact, so they return
    ``None`` and leave the choice to another file.
    """
    from psynet.experiment_scaffold import is_requirement_line_for

    for line in (content or "").splitlines():
        line = re.sub(r"\s+#.*$", "", line.split(";")[0]).rstrip(" \\")
        if not is_requirement_line_for(line, package_name.lower()):
            continue
        specified = specified_version(line)
        if re.search(r"git\+\S+@", line) and specified != line.strip():
            if re.fullmatch(r"[0-9a-fA-F]{7,40}", specified):
                return specified, "commit"
            if is_release_version_specifier(specified):
                return specified.removeprefix("v"), "version"
        elif "==" in line:
            return specified, "version"
    return None


def _same_version(specified, installed):
    """Return whether two version strings name the same version (``12.4`` == ``12.4.0``)."""
    from packaging.version import InvalidVersion, Version

    try:
        return Version(specified) == Version(installed)
    except InvalidVersion:
        return specified == installed


def collect_core_dependency_version_info_from_requirements(
    file_content, skip=(), constraints_content=None
):
    """
    Compare the PsyNet and Dallinger pins with the installed versions.

    Parameters
    ----------
    file_content : str
        Contents of a requirements.txt file.
    skip : collection of str
        Lowercase names of packages not to check; they are omitted from the
        result without their installed version being looked up.
    constraints_content : str, optional
        Contents of constraints.txt, consulted for packages that
        requirements.txt does not pin exactly.

    Returns
    -------
    dict
        Mapping of package name to a dict containing ``specified``, ``installed``,
        ``source`` (the file the pin came from), ``status`` (``consistent``,
        ``inconsistent``, or ``skipped``), and optional ``skip_reason`` and
        ``warning`` messages.

    Raises
    ------
    ValueError
        If a commit pin is checked against an editable install whose
        Git commit cannot be determined.
    """
    versions = {}
    for package_name in ["Dallinger", "PsyNet"]:
        if package_name.lower() in skip:
            continue
        versions[package_name] = {
            "specified": None,
            "installed": None,
            "source": None,
            "status": "consistent",
            "skip_reason": None,
            "warning": None,
        }

        source = "requirements.txt"
        pin = _exact_pin(file_content, package_name)
        if pin is None:
            source = "constraints.txt"
            pin = _exact_pin(constraints_content, package_name)
        if pin is None:
            continue
        specified, kind = pin

        skip_reason = None
        warning = None
        if kind == "version":
            # A version pin must match exactly even for a development install:
            # the deployment copies templates and static files from the local
            # package, while the image installs the pinned one.
            installed = get_installed_version_for_package(package_name)
            matches = _same_version(specified, installed)
            status = "consistent" if matches else "inconsistent"
        else:
            installed = get_installed_commit_or_version(package_name)
            if is_development_version(installed):
                # Only index or non-editable path installs report a version
                # here, and a development version could correspond to many
                # commits, so it cannot be compared with a commit pin.
                status = "skipped"
                skip_reason = "installed version is a development version"
            elif _commit_pin_matches(specified, installed):
                status = "consistent"
                warning = _uncommitted_changes_warning(package_name, source)
            else:
                status = "inconsistent"
        versions[package_name] = {
            "specified": specified,
            "installed": installed,
            "source": source,
            "status": status,
            "skip_reason": skip_reason,
            "warning": warning,
        }
    return versions


def specified_version(requirement):
    """Return the version, tag or commit that a requirement line pins.

    Handles Git requirements (``...@git+https://host/repo@<ref>#egg=psynet``,
    whatever the repository is called) and standard ones (``psynet==10.0.0``).
    A bare package name is returned unchanged.
    """
    url = re.search(r"git\+\S+", requirement)
    if url is not None:
        path = url.group(0).split("#")[0].split("://", 1)[-1]
        if "@" in path.split("/", 1)[-1]:
            return path.rsplit("@", 1)[-1].strip()
    return re.split("==", requirement)[-1].strip()


def _commit_pin_matches(specified, installed):
    """Return whether a pinned commit hash, possibly abbreviated, names the installed commit."""
    return (
        re.fullmatch(r"[0-9a-fA-F]{7,40}", specified) is not None
        and re.fullmatch(r"[0-9a-fA-F]{40}", installed) is not None
        and installed.lower().startswith(specified.lower())
    )


def is_release_version_specifier(specified):
    """Return whether a requirement pins a release version rather than a branch or commit.

    Release pins are stable or release-candidate versions, with or without a
    leading ``v`` (``v14.0.0``, ``14.0.0rc2``). Alpha versions are never
    tagged, and branch names that merely start with ``v`` (e.g.
    ``vocal-fixes``) are not release pins.
    """
    return re.search(r"^v?\d+\.\d+\.\d+(?:rc\d+)?$", specified) is not None


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


def get_installed_commit_or_version(package_name):
    """Return the installed Git commit of a package, or its version.

    Inspects the running interpreter's distribution metadata rather than
    whatever ``pip`` is on ``PATH``. VCS installs report the commit recorded
    in PEP 610 ``direct_url.json``; editable installs report the current
    ``HEAD`` of the Git checkout they point at (uncommitted changes are not
    reflected). Other installs report the version string.

    Parameters
    ----------
    package_name : str
        Distribution name, e.g. ``"PsyNet"`` or ``"Dallinger"``.

    Returns
    -------
    str
        A 40-character commit hash or a version string.

    Raises
    ------
    ValueError
        If the package is not installed, or is installed editable from a
        directory that is not the root of a readable Git checkout.
    """
    from psynet.experiment_scaffold import _direct_url_info, _editable_source

    installation = _direct_url_info(package_name)
    commit = ((installation or {}).get("vcs_info") or {}).get("commit_id")
    if commit is not None:
        return commit
    source = _editable_source(installation)
    if source is not None:
        return _editable_checkout_commit(package_name, source)
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        raise ValueError(
            f"Package '{package_name}' is not installed in the active Python "
            f"environment ({sys.executable})."
        ) from None


def _editable_checkout_commit(package_name, source):
    """Return the ``HEAD`` commit of the Git checkout rooted at ``source``.

    ``git -C`` searches parent directories, so the checkout's top level must be
    ``source`` itself; otherwise an enclosing repository's commit would be
    reported.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--show-toplevel", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        toplevel, commit = result.stdout.splitlines()
        if not (Path(toplevel).exists() and os.path.samefile(toplevel, source)):
            problem = f"it is not the root of a Git checkout (found {toplevel})"
        else:
            return commit
    except OSError as exc:
        problem = f"git could not be run: {exc}"
    except subprocess.CalledProcessError as exc:
        problem = f"git failed: {exc.stderr.strip()}"
    raise ValueError(
        f"{package_name} is installed in editable mode from {source}, but its "
        f"Git commit cannot be determined because {problem}. A branch or commit "
        "pin cannot be checked against it."
    )


def _uncommitted_changes_warning(package_name, pin_file):
    """Return a warning if the editable checkout of a commit-pinned package has local edits.

    Only modified tracked files count; untracked files are often scratch files
    and would make this warning fire on most deployments. Changes inside the
    experiment directory (the current directory) are ignored, because those
    files are uploaded with the deployment.
    """
    from psynet.experiment_scaffold import get_editable_source
    from psynet.experiment_setup import _editable_checkout_is_dirty

    source = get_editable_source(package_name)
    if source is None or not _editable_checkout_is_dirty(
        source, include_untracked=False, exclude=Path.cwd()
    ):
        return None
    return (
        f"The editable {package_name} checkout at {source} has uncommitted "
        f"changes to tracked files. The server will install the commit pinned in {pin_file}, "
        "not your local edits. Commit and push them and update the pin, or, "
        f"for 'psynet debug ssh', use '--use-local-{package_name.lower()}' to "
        "build the local checkout into the image."
    )


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
