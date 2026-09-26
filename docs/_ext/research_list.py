"""Sphinx directive that lists papers from a BibTeX file in APA style.

The "Research using PsyNet" page uses a single directive::

    .. research-list:: research.bib

It writes one section per technique in ``TECHNIQUES``, each with the label
``research-<tag>``, and skips techniques without papers. Papers are tagged with
the BibTeX ``keywords`` field and may carry several tags, so the same paper can
appear in more than one section. Entries are formatted with the official APA
style file in ``csl/apa.csl`` and listed newest first.
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


class _BibTeX(BibTeX):
    """BibTeX reader that also keeps the ``url`` and ``keywords`` fields."""

    fields = {**BibTeX.fields, "url": "URL", "keywords": "keyword"}


def _tags(reference):
    return {tag.strip() for tag in str(reference.get("keyword", "")).split(",")} - {""}


def _linkify(entry):
    return re.sub(r"(https?://\S+?)(?=\.?$|\.?\s)", r'<a href="\1">\1</a>', entry)


def _format(source, keys):
    """Return the APA references for ``keys`` as an HTML list."""
    bibliography = CitationStylesBibliography(
        CitationStylesStyle(str(APA_STYLE), validate=False), source, formatter.html
    )
    for key in keys:
        bibliography.register(Citation([CitationItem(key)]))
    items = "".join(f"<li>{_linkify(str(e))}</li>" for e in bibliography.bibliography())
    return f'<ul class="research-list">{items}</ul>'


class ResearchList(SphinxDirective):
    """List the papers in a BibTeX file, one section per technique."""

    required_arguments = 1

    def run(self):
        rel_path, path = self.env.relfn2path(self.arguments[0])
        self.env.note_dependency(rel_path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            source = _BibTeX(path, encoding="utf-8")

        for key, reference in source.items():
            tags = _tags(reference)
            if not tags or tags - TECHNIQUES.keys():
                logger.warning(
                    f"{rel_path}: entry {key!r} needs keywords from "
                    f"{sorted(TECHNIQUES)}, got {sorted(tags)}",
                    location=(self.env.docname, self.lineno),
                )

        newest_first = sorted(
            source, key=lambda key: (-int(source[key]["issued"]["year"]), key)
        )
        lines = []
        for tag, heading in TECHNIQUES.items():
            keys = [key for key in newest_first if tag in _tags(source[key])]
            if not keys:
                continue
            lines += [f".. _research-{tag}:", "", heading, "-" * len(heading), ""]
            lines += [".. raw:: html", "", f"   {_format(source, keys)}", ""]

        container = nodes.container()
        nested_parse_with_titles(self.state, StringList(lines, rel_path), container)
        return container.children


def setup(app):
    app.add_directive("research-list", ResearchList)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
