"""Sphinx directives that list papers from a BibTeX file.

The "Research using PsyNet" page uses::

    .. research-list:: research.bib

That writes one section per technique in ``TECHNIQUES``, each with the label
``research-<tag>``, and skips techniques without papers.

Gallery cards use a shorter form::

    .. example-publications:: rating

which renders author–year links to each paper. Papers are tagged with the
BibTeX ``keywords`` field and may carry several tags, so the same paper can
appear in more than one section. Entries on the research page are formatted
with the official APA style file in ``csl/apa.csl`` and listed newest first.
"""

import re
import warnings
from pathlib import Path

from citeproc import (
    Citation,
    CitationItem,
    CitationStylesBibliography,
    CitationStylesStyle,
    formatter,
)
from citeproc.source.bibtex import BibTeX
from docutils import nodes
from docutils.statemachine import StringList
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import nested_parse_with_titles

logger = logging.getLogger(__name__)

TECHNIQUES = {
    "rating": "Rating large stimulus sets",
    "adaptive": "Adaptive procedures",
    "sampling": "Sampling with people",
    "chains": "Chains and cultural transmission",
    "recording": "Recording and production",
    "create-and-rate": "Create and rate",
    "groups": "Groups and interaction",
    "languages": "Across languages and countries",
}

APA_STYLE = Path(__file__).parent / "csl" / "apa.csl"
DEFAULT_BIB = "research.bib"


class _BibTeX(BibTeX):
    """BibTeX reader that also keeps the ``url`` and ``keywords`` fields."""

    fields = {**BibTeX.fields, "url": "URL", "keywords": "keyword"}


def _tags(reference):
    return {tag.strip() for tag in str(reference.get("keyword", "")).split(",")} - {""}


def _linkify(entry):
    return re.sub(r"(https?://\S+?)(?=\.?$|\.?\s)", r'<a href="\1">\1</a>', entry)


def _paper_url(reference):
    """Return the paper URL from ``url`` or ``doi``."""
    url = str(reference.get("URL") or "").strip()
    if url:
        return url
    doi = str(reference.get("DOI") or "").strip()
    if doi:
        doi = re.sub(r"^https?://doi\.org/", "", doi)
        return f"https://doi.org/{doi}"
    return None


def _family_name(author):
    """Return a citeproc author's family name, including particles."""
    if author is None:
        return ""
    if isinstance(author, str):
        return author
    getter = author.get if hasattr(author, "get") else None
    if getter is not None:
        particle = str(getter("non-dropping-particle") or "")
        family = str(getter("family") or getter("literal") or "")
    else:
        particle = str(getattr(author, "non-dropping-particle", "") or "")
        family = str(
            getattr(author, "family", "") or getattr(author, "literal", "") or ""
        )
    return f"{particle} {family}".strip()


def _cite_label(reference):
    """Return a short author–year label such as ``Marjieh et al. (2024)``."""
    authors = list(reference.get("author") or [])
    names = [name for name in (_family_name(author) for author in authors) if name]
    year = reference["issued"]["year"]
    if not names:
        label = str(reference.get("title", "Paper"))
    elif len(names) == 1:
        label = names[0]
    elif len(names) == 2:
        label = f"{names[0]} & {names[1]}"
    else:
        label = f"{names[0]} et al."
    return f"{label} ({year})"


def _newest_first(source):
    return sorted(source, key=lambda key: (-int(source[key]["issued"]["year"]), key))


def _keys_for_tag(source, tag):
    return [key for key in _newest_first(source) if tag in _tags(source[key])]


def _format(source, keys):
    """Return the APA references for ``keys`` as an HTML list."""
    bibliography = CitationStylesBibliography(
        CitationStylesStyle(str(APA_STYLE), validate=False), source, formatter.html
    )
    for key in keys:
        bibliography.register(Citation([CitationItem(key)]))
    items = "".join(f"<li>{_linkify(str(e))}</li>" for e in bibliography.bibliography())
    return f'<ul class="research-list">{items}</ul>'


def _load_bib(directive, rel_path):
    _, path = directive.env.relfn2path(rel_path)
    directive.env.note_dependency(rel_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _BibTeX(path, encoding="utf-8")


class ResearchList(SphinxDirective):
    """List the papers in a BibTeX file, one section per technique."""

    required_arguments = 1

    def run(self):
        rel_path = self.arguments[0]
        source = _load_bib(self, rel_path)

        for key, reference in source.items():
            tags = _tags(reference)
            if not tags or tags - TECHNIQUES.keys():
                logger.warning(
                    f"{rel_path}: entry {key!r} needs keywords from "
                    f"{sorted(TECHNIQUES)}, got {sorted(tags)}",
                    location=(self.env.docname, self.lineno),
                )

        lines = []
        for tag, heading in TECHNIQUES.items():
            keys = _keys_for_tag(source, tag)
            if not keys:
                continue
            lines += [f".. _research-{tag}:", "", heading, "-" * len(heading), ""]
            lines += [".. raw:: html", "", f"   {_format(source, keys)}", ""]

        container = nodes.container()
        nested_parse_with_titles(self.state, StringList(lines, rel_path), container)
        return container.children


class ExamplePublications(SphinxDirective):
    """Render linked author–year citations for one technique on a gallery card."""

    required_arguments = 1
    option_spec = {"from": lambda value: value.strip()}

    def run(self):
        tag = self.arguments[0].strip()
        if tag not in TECHNIQUES:
            raise self.error(
                f"Unknown technique {tag!r}. Expected one of {sorted(TECHNIQUES)}."
            )
        rel_path = self.options.get("from", DEFAULT_BIB)
        source = _load_bib(self, rel_path)
        keys = _keys_for_tag(source, tag)
        if not keys:
            raise self.error(f"No papers in {rel_path} are tagged {tag!r}.")

        links = []
        for key in keys:
            reference = source[key]
            label = _cite_label(reference)
            url = _paper_url(reference)
            if url:
                links.append(f"`{label} <{url}>`__")
            else:
                logger.warning(
                    f"{rel_path}: entry {key!r} has no url or doi",
                    location=(self.env.docname, self.lineno),
                )
                links.append(label)
        rst = "**Example publications:** " + ", ".join(links)
        container = nodes.container()
        nested_parse_with_titles(self.state, StringList([rst], rel_path), container)
        return container.children


def setup(app):
    app.add_directive("research-list", ResearchList)
    app.add_directive("example-publications", ExamplePublications)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
