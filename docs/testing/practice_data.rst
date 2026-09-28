.. _practice_data:

Practice data and power analysis
================================

Practice data
-------------

``psynet audit simulate`` runs simulated participants and saves their
export in the audit. The export has the same tables, columns and files as a
real one, so the analysis can be written and tested before data collection.
If the bots use a response model, the analysis should recover the effects
built into the model.

Power analysis
--------------

PsyNet's default approach to power analysis is precision estimation:

1. Simulate the whole experiment many times with a response model.
2. Run the planned analysis on each simulated dataset.
3. Measure how precisely it estimates the quantities of interest.
4. Repeat for different numbers of participants, stimuli or trials.

If participants are paid, compare the precision of each design with its
cost. Record where the response model's parameter values come from (pilot
data, the literature, or a guess).

The results are shown in the audit's *Design simulation* section.
