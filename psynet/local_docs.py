"""Find the PsyNet documentation that matches the installed version.

Coding agents search the documentation far faster on disk than through the
website, and the website may describe a different PsyNet version. So
``psynet docs`` resolves a local copy:

- In a PsyNet source checkout, the RST sources in ``docs/``.
- In a release install, the plain-text build bundled in
  ``psynet/resources/docs_text/``. ``psynet dev docs bundle`` creates it
  before ``python -m build``; it is gitignored and packaged as a Hatch
  artifact. Its ``VERSION`` file guards against a bundle left over from
  another version. The bundle also holds the demos' authored files under
  ``demos/``, which ``psynet docs demos`` points to.

Other installs, such as Git installs, have no local copy; the error message
points to the matching version of the website instead.

Keep imports light: this module runs on every ``psynet docs`` call.
"""

import re
import tomllib
from pathlib import Path

import click

from psynet.light_utils import get_psynet_root

BUNDLED_DOCS_DIR = Path(__file__).parent / "resources" / "docs_text"
DOCS_URL = "https://psynetdev.gitlab.io/PsyNet/"
_PAGE_SUFFIXES = (".txt", ".rst", ".md")


class DocsError(click.ClickException):
    """Raised when the local documentation or a page in it can't be found."""


def _is_source_checkout(root: Path) -> bool:
    """Return whether ``root`` is a PsyNet source checkout with documentation."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file() or not (root / "docs" / "conf.py").is_file():
        return False
    try:
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    name = metadata.get("project", {}).get("name")
    return isinstance(name, str) and name.casefold() == "psynet"


def published_docs_url(version: str) -> str:
    """Return the website URL for the documentation of ``version``."""
    stable = re.fullmatch(r"(\d+\.\d+\.\d+)(\.post\d+)?", version)
    if stable:
        return f"{DOCS_URL}v{stable.group(1)}/"
    if re.fullmatch(r"\d+\.\d+\.\d+rc\d+", version):
        return f"{DOCS_URL}rc/v{version}/"
    return f"{DOCS_URL}alpha/"


def _locate_docs(source_root: Path, bundled_dir: Path, version: str) -> Path:
    source_docs = source_root / "docs"
    if _is_source_checkout(source_root):
        return source_docs
    version_file = bundled_dir / "VERSION"
    if version_file.is_file():
        bundled_version = version_file.read_text(encoding="utf-8").split()[:1]
        if bundled_version == [version]:
            return bundled_dir
        if bundled_version:
            raise DocsError(
                f"This PsyNet installation is version {version}, but its local "
                f"documentation is for version {bundled_version[0]}. "
                f"Read the matching documentation online at "
                f"{published_docs_url(version)}"
            )
    raise DocsError(
        f"This PsyNet installation ({version}) has no local documentation. "
        f"Read it online at {published_docs_url(version)}"
    )


def docs_dir() -> Path:
    """Return the local documentation directory for the installed PsyNet."""
    from psynet import __version__

    return _locate_docs(get_psynet_root(), BUNDLED_DOCS_DIR, __version__)


def demos_dir() -> Path:
    """Return the local demo code for the installed PsyNet.

    In a source checkout this is the repository's ``demos/``; release installs
    bundle the demos' authored files with the documentation.
    """
    docs = docs_dir()
    return docs / "demos" if docs == BUNDLED_DOCS_DIR else docs.parent / "demos"


def _page_name(page: str) -> str:
    """Reduce a page name or website URL to a path such as ``code/pages/theming``."""
    page = page.split("#", 1)[0]
    if page.startswith(DOCS_URL):
        page = re.sub(r"^(v[^/]+/|rc/[^/]+/|alpha/)", "", page[len(DOCS_URL) :])
    return page.strip("/").removesuffix(".html")


def _find_page(root: Path, page: str) -> Path:
    name = _page_name(page)
    root = root.resolve()
    for suffix in _PAGE_SUFFIXES:
        candidate = (root / f"{name}{suffix}").resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    raise DocsError(
        f"No documentation page {name!r} in {root}. "
        f'Search for the topic with: rg -n -i --no-ignore "<term>" "{root}"'
    )


def page_path(page: str) -> Path:
    """Return the file for a page name such as ``code/participants/payment``.

    Website URLs, ``.html`` suffixes and ``#`` anchors are accepted too.
    """
    return _find_page(docs_dir(), page)
