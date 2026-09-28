Testing and auditing
====================

Check that your experiment works before real participants see it.
:doc:`tests` covers the automated tests every experiment should pass, in which
simulated participants run through the whole experiment.
:doc:`performance_testing` checks how the server copes when many participants
arrive at once. :doc:`audit` packages this evidence so that you, or a
colleague, can review an experiment before it launches.

When something goes wrong, :doc:`troubleshooting` lists fixes for common
development errors, and :doc:`sqlalchemy_profiling` and
:doc:`introduction_to_sql_alchemy` help when database queries are slow.

.. toctree::
   :maxdepth: 1

   tests
   performance_testing
   audit
   troubleshooting
   sqlalchemy_profiling
   introduction_to_sql_alchemy
