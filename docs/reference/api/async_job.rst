==========
Async jobs
==========

.. Exclude rq.job.Job because sphinx_autodoc_typehints resolves its annotations
.. and can hit an unresolved Redis forward reference even though Job is not
.. rendered on the page.

.. automodule:: psynet.async_job
    :members:
    :show-inheritance:
    :exclude-members: Job
