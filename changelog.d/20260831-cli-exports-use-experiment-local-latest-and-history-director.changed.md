Command-line exports now write to ``exports/latest/`` in the experiment
directory and keep the previous export under ``exports/history/<timestamp>/``.
A new export is assembled in a staging directory and only moved into place once
it is complete and validated, so a failed or interrupted export always leaves
your previous export intact.
