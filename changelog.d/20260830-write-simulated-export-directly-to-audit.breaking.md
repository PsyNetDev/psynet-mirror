Moved audit evidence collection to ``psynet audit simulate`` and
``psynet audit performance-test``. Top-level ``psynet simulate`` is removed;
use ``psynet audit simulate``. These commands require an initialized
audit packet, write canonical evidence paths, and update ``audit.json``.
The audit performance-test command runs locally; remote SSH collection is
not part of this command. Top-level ``psynet performance-test`` remains
available for measurement-only runs and no longer accepts ``--audit``.
Simulated exports now exist only at
``audit/simulate/analysis/simulated_export/``. A failed rerun leaves the
previous export in place. Directory artifacts are limited to
``simulate_export``; other present artifacts must be files. Extra files beside
``analysis.ipynb`` appear in the Analysis panel.
