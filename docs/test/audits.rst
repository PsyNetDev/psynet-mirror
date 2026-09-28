.. _audits:

Audits
======

An experiment audit collects the evidence that an experiment was built and
tested as intended, for someone to review before launch. It lives in the
experiment's ``audit/`` folder and is rendered as a static website. A coding
agent creates and updates the audit as it works. To view it, run
``psynet audit serve --render`` in the experiment folder and open the address
it prints.

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
   Screenshots of the participant pages, and a recording of a session; see
   :doc:`frontend`.

**Performance test**
   Response times with many bots at once; see :doc:`scalability`.

**Data exports**
   The export produced by bots, in the same format as a real export; see
   :doc:`backend`.

**Design simulation**
   The power analysis, if the study has one. PsyNet's default approach is
   precision estimation: the whole experiment is simulated many times, with
   bots whose answers come from a response model; the planned analysis is run
   on each simulated dataset; and the precision of its estimates is compared
   across numbers of participants, stimuli or trials. If participants are
   paid, each design's precision is compared with its cost. The section also
   records where the response model's parameter values come from: pilot
   data, the literature, or a guess.

**Analysis**
   The planned analysis, run on the simulated export.

**Blockers**
   Anything that is unfinished or could not be checked, with the reason and
   the next step.

**Checks**
   Automated checks and their results.

Sections that don't apply to an experiment are omitted.

.. seealso::

   :doc:`/reference/audit`, for the audit's files and commands.
