Fixed Markdown display outputs being omitted from rendered audit notebooks.
The audit now renders ``text/markdown`` with the same Markdown renderer used
for reports, before falling back to ``text/plain``.
