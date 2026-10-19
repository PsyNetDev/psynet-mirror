Removed the ``--assets all`` export option.

Exports now include either no assets (``--assets none``) or files deposited
during the run (``--assets collected``, the default), such as recordings.
Cached stimuli, external URLs, and on-demand assets are no longer copied into
the archive. Copy stimuli from the experiment directory or storage if you need
them for supplementary materials. Passing ``all`` (CLI ``--assets all``, or
dashboard ``?assets=all``) raises an error with this guidance. The dashboard
export page no longer offers an All choice.
