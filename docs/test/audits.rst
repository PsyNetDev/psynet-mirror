.. _audits:

Audits
======

An experiment audit collects the evidence that an experiment was built and
tested as intended, for someone to review before launch. It lives in the
experiment's ``audit/`` folder and is rendered as a static website.

A coding agent creates and updates the audit as it works. To view it, run
``psynet audit serve --render`` in the experiment folder and open the
address it prints.

Sections
--------

**Prompt**
   The original request for the experiment.

**Plan**
   The implementation plan agreed before the code was written.

**Implementation timeline and notes**
   What was done, in order, and any decisions made along the way.

**Experiment code**
   The experiment's ``experiment.py``.

**Screenshots and participant video**
   Screenshots of the participant pages, and a recording of a session.

**Performance test**
   Page response times with many simulated participants at once. See
   :doc:`performance_testing`.

**Data exports**
   The export produced by :doc:`simulated participants
   </test/bots>`, in the same format as a real export.

**Design simulation**
   The power analysis, if the study has one. See :doc:`/test/bots`.

**Analysis**
   The planned analysis, run on the simulated export.

**Blockers**
   Anything that is unfinished or could not be checked, with the reason and
   the next step.

**Checks**
   Automated checks and their results.

Sections that don't apply to an experiment are omitted.

Before launch
-------------

The audit records what was checked, not whether those were the right
checks. Before launching, also take the experiment yourself on a laptop and
on a phone.

.. seealso::

   :doc:`/test/audit_reference`, for the audit's files and commands.
