Documented how to import Python files that sit beside ``experiment.py``.
From the experiment package use ``from . import my_module``. Standalone
scripts such as ``python -m audit.simulate.design.core`` keep top-level
imports and must be run from the experiment root.
