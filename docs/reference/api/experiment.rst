==========
Experiment
==========

.. Exclude Flask helpers because sphinx_autodoc_typehints resolves their
.. annotations and hits unresolved Response forward references.

.. automodule:: psynet.experiment
    :members:
    :show-inheritance:
    :exclude-members: jsonify, send_file, make_response

Scheduled tasks
---------------

``scheduled_task`` is re-exported from Dallinger. Use it on a static method of
your experiment class to run code on the clock process, for example
``@scheduled_task("interval", seconds=10, max_instances=1)``.

.. autofunction:: psynet.experiment.scheduled_task
