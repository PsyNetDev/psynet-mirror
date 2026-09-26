"""Sphinx directive that shows demo screenshots as a phone-sized carousel.

Each line of the directive body is a demo path relative to ``demos/``::

    .. demo-carousel::

       experiments/gibbs
       experiments/mcmcp

A demo's screenshot is ``_static/images/gallery/<path with / replaced by __>.png``.
Demos without a screenshot show a placeholder. Each slide links to the demo's
source on GitLab.
"""

import html
import posixpath
from pathlib import Path

from docutils import nodes
from sphinx.util.docutils import SphinxDirective

DEMO_URL = "https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/{}"
GALLERY_DIR = Path("_static") / "images" / "gallery"
PLACEHOLDER = "phone_placeholder.svg"


class DemoCarousel(SphinxDirective):
    """Render the listed demos as a horizontally scrolling carousel."""

    has_content = True

    def run(self):
        demos = [line.strip() for line in self.content if line.strip()]
        static_root = posixpath.relpath(
            "_static", posixpath.dirname(self.env.docname) or "."
        )
        slides = "".join(self._slide(demo, static_root) for demo in demos)
        dots = "".join(
            '<button class="demo-carousel-dot" type="button" '
            f'aria-label="Show demo {i + 1}"></button>'
            for i in range(len(demos))
        )
        controls = (
            '<div class="demo-carousel-controls">'
            '<button class="demo-carousel-prev" type="button" aria-label="Previous demo">&#8249;</button>'
            f"{dots}"
            '<button class="demo-carousel-next" type="button" aria-label="Next demo">&#8250;</button>'
            "</div>"
            if len(demos) > 1
            else ""
        )
        markup = (
            '<div class="demo-carousel">'
            f'<div class="demo-carousel-track">{slides}</div>{controls}</div>'
        )
        return [nodes.raw("", markup, format="html")]

    def _slide(self, demo, static_root):
        image = demo.replace("/", "__") + ".png"
        self.env.note_dependency(str(GALLERY_DIR / image))
        if not (Path(self.env.srcdir) / GALLERY_DIR / image).exists():
            image = PLACEHOLDER
        src = posixpath.join(static_root, "images", "gallery", image)
        name = html.escape(demo.rsplit("/", 1)[-1])
        return (
            f'<a class="demo-carousel-slide" href="{DEMO_URL.format(demo)}">'
            f'<img class="demo-phone" src="{src}" alt="Screenshot of the {name} demo" loading="lazy">'
            f'<span class="demo-carousel-caption">{name}</span></a>'
        )


def setup(app):
    app.add_directive("demo-carousel", DemoCarousel)
    app.add_css_file("css/demo_carousel.css")
    app.add_js_file("js/demo_carousel.js")
    return {"parallel_read_safe": True, "parallel_write_safe": True}
