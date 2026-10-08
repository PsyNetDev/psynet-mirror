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

For examples, see the `example audits
<https://psynetdev.gitlab.io/example-audits/>`_, which coding agents
produced while implementing these studies:

- `Chord pleasantness
  <https://psynetdev.gitlab.io/example-audits/chord-pleasantness/>`_, the
  rating study in :doc:`/introduction/what_its_like`.
- `Personality and the prisoner's dilemma
  <https://psynetdev.gitlab.io/example-audits/prisoners-dilemma/>`_, a
  two-player game with a power analysis.

The experiments' code is in the `example-audits repository
<https://gitlab.com/PsyNetDev/example-audits>`_.

Sections
--------

**Prompt**
   The original request for the experiment.

**Plan**
   The implementation plan agreed before the code was written.

**Power analysis**
   The design simulation used to choose the numbers of participants, stimuli
   and trials, if the study has one; see :ref:`audit_design_simulation` and the
   :doc:`/skills/power-analysis` skill.

**Implementation timeline**
   What was done, in order.

**Implementation notes**
   Decisions made along the way, and anything a reviewer should know.

**Experiment code**
   The experiment's ``experiment.py``, followed by its other Python modules.

**Screenshots**
   Screenshots of the participant pages; see :doc:`frontend`.

**Participant video**
   A recording of a participant's session, with the experiment's sound; see
   :doc:`frontend` and :doc:`/skills/record-participant-video`, whose helper
   records audio from headless Chromium on macOS and Linux.

**Monitor snapshot**
   A static copy of the PsyNet monitor page.

**Performance test**
   Response times with many bots at once, and whether each tested number of
   bots stayed within the response-time and queue-wait limits; see
   :doc:`scalability`.

**Data exports**
   The export produced by bots, in the same format as a real export; see
   :doc:`backend`.

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

   The :doc:`/skills/produce-experiment-audit` skill describes how to prepare
   an audit.

