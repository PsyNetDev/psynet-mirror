.. _simulated_participants:
.. _practice_data:

Bots and response models
========================

A bot is a simulated participant. It takes the experiment through the same
server and timeline as a real participant, but without a browser. PsyNet
uses bots for :doc:`logic testing <logic_testing>`, for
:doc:`performance testing <performance_testing>`, and to produce the
simulated data in an :doc:`audit <audits>`.

Bot answers
-----------

By default, a bot gives a valid answer to each page, for example a random
choice from the options or a number in the allowed range. Pages that
collect recordings need a sample file for bots to submit.

A page can override the default answer. For example, bots in a rating study
can rate some stimuli higher than others, and bots in a chain can copy the
previous answer with some error. In group experiments, several bots take
the experiment together.

Response models
---------------

A response model is code, kept with the experiment, that generates bot
answers from assumptions about how participants behave. The same model is
used for the practice data and the power analysis below, so both rest on
the same stated assumptions.

Practice data
-------------

``psynet audit simulate`` runs bots and saves their export in the audit.
The export has the same tables, columns and files as a real one, so the
analysis can be written and tested before data collection. If the bots use
a response model, the analysis should recover the effects built into the
model.

Power analysis
--------------

PsyNet's default approach to power analysis is precision estimation:

1. Simulate the whole experiment many times with a response model.
2. Run the planned analysis on each simulated dataset.
3. Measure how precisely it estimates the quantities of interest.
4. Repeat for different numbers of participants, stimuli or trials.

If participants are paid, compare the precision of each design with its
cost. Record where the response model's parameter values come from (pilot
data, the literature, or a guess). The results are shown in the audit's
*Design simulation* section.

Limitations
-----------

- Bots don't display pages, so they don't detect layout problems.
- Bot answers are generated, not collected from people. Simulated data
  can't show whether participants understand the task or how they will
  respond.
