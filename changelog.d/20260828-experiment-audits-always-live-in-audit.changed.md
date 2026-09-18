Experiment audits always live in ``./audit/`` under the experiment
directory. Run ``psynet audit`` from that experiment directory; commands take
no packet path and no ``--experiment`` option. Running from a directory named
``audit`` is an error. ``--audit`` on simulate and performance-test is a
boolean flag that writes into ``./audit/``. Experiment source is the parent of
``audit/``; leftover ``experiment.source_path`` and
``experiment.source_base`` fields are ignored with a warning.
