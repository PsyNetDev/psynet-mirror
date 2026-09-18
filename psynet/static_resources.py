"""Discover and publish static resources owned by installed Python packages.

Packages register one static root through the ``psynet.static`` entry-point
group. PsyNet publishes each root under a namespaced URL so dynamically created
components can declare ordinary dependency and page-module URLs without asking
experiment authors to copy package files into their experiment.
"""

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata, resources
from pathlib import Path, PurePosixPath
from types import ModuleType
from urllib.parse import quote, urlsplit

STATIC_ENTRY_POINT_GROUP = "psynet.static"
_NAMESPACE_SEPARATOR = re.compile(r"[-_.]+")
_SAFE_NAMESPACE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MATERIALIZED_STATIC_ROOTS = []


@dataclass(frozen=True)
class StaticPackage:
    """A validated package-owned static resource root."""

    namespace: str
    root: object
    distribution: str

    @property
    def extra_file(self):
        """Return the Dallinger extra-files source and destination pair."""
        return self.root, f"/static/packages/{self.namespace}"


def _canonicalize_namespace(namespace):
    """Convert an entry-point name to its stable URL namespace."""
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("Static package namespace must be a non-empty string.")
    canonical = _NAMESPACE_SEPARATOR.sub("-", namespace).lower()
    if not _SAFE_NAMESPACE.fullmatch(canonical):
        raise ValueError(
            f"Invalid static package namespace {namespace!r}; use letters, "
            "numbers, dots, underscores, or hyphens."
        )
    return canonical


def package_static_url(namespace, path):
    """Build a safe URL for a resource in a registered static package."""
    canonical_namespace = _canonicalize_namespace(namespace)
    if not isinstance(path, str) or not path:
        raise ValueError("Static package resource path must be a non-empty string.")
    if "\\" in path or "%" in path:
        raise ValueError(
            "Static package resource paths must use unescaped forward-slash paths."
        )

    parsed = urlsplit(path)
    resource_path = PurePosixPath(path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or resource_path.is_absolute()
        or not resource_path.parts
        or ".." in resource_path.parts
    ):
        raise ValueError(f"Unsafe static package resource path: {path!r}.")

    encoded_path = quote(resource_path.as_posix(), safe="/-._~")
    return f"/static/packages/{canonical_namespace}/{encoded_path}"


def psynet_static_root():
    """Return PsyNet's bundled static resource root."""
    return resources.files("psynet").joinpath("static")


def _distribution_name(entry_point):
    distribution = getattr(entry_point, "dist", None)
    return getattr(distribution, "name", None) or "<unknown distribution>"


def _resolve_static_root(entry_point):
    loaded = entry_point.load()
    if isinstance(loaded, ModuleType):
        root = resources.files(loaded).joinpath("static")
    elif callable(loaded):
        root = loaded()
    else:
        raise ValueError(
            f"Entry point {entry_point.name!r} in {STATIC_ENTRY_POINT_GROUP!r} "
            "must load a package module or a callable returning a static root."
        )
    if not hasattr(root, "is_dir"):
        raise ValueError(
            f"Static root for entry point {entry_point.name!r} must be a "
            "path-like resource directory."
        )
    if hasattr(root, "exists") and not root.exists():
        raise ValueError(
            f"Static root for entry point {entry_point.name!r} does not exist: {root}."
        )
    if not root.is_dir():
        raise ValueError(
            f"Static root for entry point {entry_point.name!r} is not a "
            f"directory: {root}."
        )
    return _ensure_filesystem_root(root, entry_point.name)


def _copy_traversable(source, destination):
    """Copy an importlib Traversable tree to a filesystem directory."""
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        child_destination = destination / child.name
        if child.is_dir():
            _copy_traversable(child, child_destination)
        elif child.is_file():
            with (
                child.open("rb") as input_file,
                child_destination.open("wb") as output_file,
            ):
                shutil.copyfileobj(input_file, output_file)


def _ensure_filesystem_root(root, namespace):
    """Return a real directory path suitable for Dallinger staging."""
    try:
        filesystem_path = Path(os.fspath(root))
    except TypeError:
        temporary_root = tempfile.TemporaryDirectory(
            prefix=f"psynet-static-{_canonicalize_namespace(namespace)}-"
        )
        _MATERIALIZED_STATIC_ROOTS.append(temporary_root)
        filesystem_path = Path(temporary_root.name) / "static"
        _copy_traversable(root, filesystem_path)
    if not filesystem_path.is_dir():
        raise ValueError(f"Static root is not a filesystem directory: {root}.")
    return filesystem_path


def _discover_static_packages(entry_points):
    """Validate and return static packages from an entry-point collection."""
    packages = []
    owners = {}
    for entry_point in sorted(
        entry_points,
        key=lambda item: (
            _canonicalize_namespace(item.name),
            _distribution_name(item),
        ),
    ):
        namespace = _canonicalize_namespace(entry_point.name)
        distribution = _distribution_name(entry_point)
        if namespace in owners:
            raise ValueError(
                f"Found duplicate PsyNet static namespace {namespace!r} from "
                f"distributions {owners[namespace]!r} and {distribution!r}."
            )
        owners[namespace] = distribution
        packages.append(
            StaticPackage(
                namespace=namespace,
                root=_resolve_static_root(entry_point),
                distribution=distribution,
            )
        )
    return packages


def _registered_static_entry_points():
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return entry_points.select(group=STATIC_ENTRY_POINT_GROUP)
    return entry_points.get(STATIC_ENTRY_POINT_GROUP, [])


@lru_cache(maxsize=1)
def get_static_packages():
    """Discover installed packages that publish PsyNet static resources."""
    return tuple(_discover_static_packages(_registered_static_entry_points()))


def clear_static_package_cache():
    """Clear discovery results and materialized temporary resource roots."""
    get_static_packages.cache_clear()
    while _MATERIALIZED_STATIC_ROOTS:
        _MATERIALIZED_STATIC_ROOTS.pop().cleanup()


def get_static_package_extra_files():
    """Return Dallinger extra-files mappings for registered static packages."""
    return [package.extra_file for package in get_static_packages()]
