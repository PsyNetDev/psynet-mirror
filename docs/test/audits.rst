.. _audits:

Audits
======

An experiment audit collects the evidence that an experiment was built and
tested as intended, for someone to review before launch. It lives in the
experiment's ``audit/`` folder and is rendered as a static website.
``psynet audit init`` creates the audit; a coding agent usually keeps it up
to date as it works. To view it, run
``psynet audit serve --render`` in the experiment folder and open the address
it prints.

Sections
--------

**Prompt**
   The original request for the experiment.

**Plan**
   The implementation plan agreed before the code was written.

**Implementation timeline**
   What was done, in order.

**Implementation notes**
   Decisions made along the way, and anything a reviewer should know.

**Experiment code**
   The experiment's ``experiment.py``.

**Screenshots**
   Screenshots of the participant pages; see :doc:`frontend`.

**Participant video**
   A recording of a participant's session; see :doc:`frontend`.

**Monitor snapshot**
   A static copy of the PsyNet monitor page.

**Performance test**
   Response times with many bots at once; see :doc:`scalability`.

**Data exports**
   The export produced by bots, in the same format as a real export; see
   :doc:`backend`.

**Design simulation**
   The simulation used to choose the numbers of participants, stimuli and
   trials, if the study has one; see :ref:`audit_design_simulation` and the
   :doc:`/skills/power-analysis` skill.

**Analysis**
   The planned analysis, run on the simulated export.

**Additional files**
   Other recorded artifacts, such as logs.

**Blockers**
   Anything that is unfinished or could not be checked, with the reason and
   the next step.

**Checks**
   Automated checks and their results.

Mark artifacts that don't apply as ``not_applicable``; the Checks panel is
hidden when no checks are recorded.

.. seealso::

   :doc:`/test/audit_reference`, for the audit's files and commands.
