"""Sphinx directive for lab-specific notes inside general pages.

Usage::

    .. lab-note::

       Ask your lab administrator for the shared Prolific workspace.

Renders as an admonition titled "In a lab", styled by ``.admonition.lab-note``
in ``_static/css/custom.css``. Use it for details that only apply when a lab
provides shared accounts, servers or conventions, so other readers can skip it.
"""

from docutils import nodes
from docutils.parsers.rst.directives.admonitions import BaseAdmonition


class LabNote(BaseAdmonition):
    """An admonition for lab-specific instructions."""

    node_class = nodes.admonition

    def run(self):
        self.arguments = ["In a lab"]
        self.options["class"] = self.options.get("class", []) + ["lab-note"]
        return super().run()


def setup(app):
    app.add_directive("lab-note", LabNote)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
