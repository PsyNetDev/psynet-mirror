====================
Experiment variables
====================

There are a couple of variables tied to an experiment all of which are documented
in the :class:`~psynet.experiment.Experiment` class. They have been assigned reasonable default values which can be
overridden. Also, they can be enriched with new variables in the following way:

::

    import psynet.experiment

    class SomeExperiment(psynet.experiment.Experiment):
        variables = {
            "new_variable": "some-value",  # Adding a new variable
        }

Experiment variables of an instance of ``Experiment`` can be accessed through the ``var`` property like
``experiment.var.new_variable``. Similarly they can also be set like ``experiment.var.set("new_variable", "some-value")``.
