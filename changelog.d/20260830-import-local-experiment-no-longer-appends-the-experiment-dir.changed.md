``import_local_experiment()`` no longer appends the experiment directory to
``sys.path``. Sibling imports in ``experiment.py`` still use
``from . import adaptive_logic``. A later bare ``import adaptive_logic`` after
the experiment class is loaded no longer works.
