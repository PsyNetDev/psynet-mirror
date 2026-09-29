.. _concept_design_simulation:

Design simulation
=================

A **design simulation** runs the planned experiment many times on computer-
generated participants before any real data are collected. Each simulated
experiment is analyzed with the planned analysis, and the results show how
well each candidate design would answer the research question and, if the
experiment pays participants, what each design would cost. Experimenters use
it to choose the number of participants, stimuli and trials. The simulation
is optional; when there is one, it is part of the experiment's audit.

.. admonition:: Who does what

   - **PsyNet** runs simulated participants (bots) through the experiment and
     shows a simulation's results table, run record and notebook in the
     experiment's audit. It has no command that runs the simulation itself.
   - **A coding agent**, with the ``power-analysis`` skill (see
     :doc:`/code/project/agent_skills`), agrees the question, candidate
     designs and assumptions with you, then writes the response model and the
     simulation in your experiment and hands back the results.
   - **You** check that the assumptions are plausible and that the
     conclusions follow from the results, using the review questions at the
     end of this page. :doc:`/test/design_simulation` describes the
     recommended setup, for reviewing the agent's work or doing it yourself.

Designs, assumptions and scenarios
----------------------------------

A design simulation keeps three things apart: what the experimenter chooses,
what is assumed about the world, and what the analysis tries to learn.

- A **design** is an experiment that could be run: the number of
  participants, stimuli and trials per participant, the allocation across
  conditions, or the budget of an adaptive procedure.
- **Assumptions** describe the world the design is tested in: how noisy
  single responses are, how much participants and stimuli differ, how strong
  an effect is, and how many responses go missing. They are uncertain before
  data collection. The number of stimuli is a design choice; the population
  the stimuli are drawn from is an assumption.
- A **scenario** is one design combined with one complete set of
  assumptions. Five participant counts, two trial counts and three noise
  levels give 30 scenarios.
- A **replicate** is one complete simulated experiment under a scenario,
  with newly drawn participants and responses. Many replicates per scenario
  show how much the results would vary between repeated real experiments.
- An **analysis target** is one scientific quantity evaluated in each
  scenario, such as a condition effect or a set of stimulus profiles. Several
  targets are analyzed from the same simulated experiments; they don't need
  separate simulated worlds.
- A **decision criterion** is the rule that says whether a design is good
  enough for a target, such as a maximum margin of error.

Testing several plausible assumption sets matters when the choice of design
depends on them. A design that works only under optimistic assumptions is
less convincing than one that stays adequate across a reasonable range.

Response models
---------------

A **response model** generates simulated answers from assumptions about how
participants behave. For a rating task it might say that a rating is the
participant's usual level, plus the effect of the condition, plus random
noise, rounded to the rating scale. Its parameter values come from pilot
data, the literature, or judgment, and the simulation records which.

PsyNet recommends one response model for both the design simulation and the
experiment's bots, so that the bots' practice data and the design simulation
describe the same simulated world. The response model applies the same
rounding and limits as the real response controls.

The response model is kept separate from two other models that may share
its mathematics:

- the **estimator**, the planned analysis that tries to recover the
  quantities of interest from the responses;
- in an adaptive experiment, the **learner**, which uses its own model of
  participants to choose what to present next.

In a simulation of an adaptive experiment, the response model can match the
learner or deliberately differ from it, to test how the procedure copes when
its assumptions are wrong. In the real experiment, participants supply the
responses.

Precision and power
-------------------

A classical **power analysis** asks how often a hypothesis test would reject
the null hypothesis if an effect of a given size were real. PsyNet's
recommended default is **precision estimation** instead: it asks how precisely
the planned analysis would estimate each quantity of interest. Precision
suits experiments that measure profiles, rankings or many stimulus-specific
values, where there is no single test to power, and it still applies when
there is one.

Each quantity of interest is an **estimand**, such as a mean difference
between conditions, a regression slope, or a stimulus's response profile.
Across replicates, the planned estimator gives a spread of estimates for each
estimand:

- The **sampling standard error** is the standard deviation of these
  estimates. It approximates how much the estimate would vary between
  repeated real experiments.
- The **margin of error** is half the width of an approximate confidence
  interval, about 1.96 sampling standard errors at 95% confidence. An
  estimate of 0.7 with a margin of error of 0.2 means roughly 0.5 to 0.9.
- The **standardized margin of error** divides the margin of error by the
  noise in a single response, so that designs are comparable across response
  scales.
- **Bias** is the average difference between the estimates and the true
  value built into the response model. A precise but biased estimator is not
  acceptable.
- **Coverage** is how often the estimator's own confidence intervals contain
  the true value, when the estimator produces intervals.

Unless the experimenter chooses otherwise, PsyNet recommends requiring a 95%
margin of error of at most 0.20 single-response standard deviations for every
primary estimand. For a profile or other set of values, the largest margin of
error across the set is a conservative criterion.

Because the simulation uses a finite number of replicates, its own summaries
are uncertain too. This **Monte Carlo error** is reported alongside each
result; if it could change which design is chosen, more replicates are
needed.

For adaptive experiments, the main measure is often how closely each
participant's final estimate matches their true value, reported as the root
mean squared error, with correlation, bias and coverage as diagnostics.

What to simulate
----------------

Each replicate simulates every trial of the complete experiment: the planned
allocation to conditions and stimuli, missing responses, the response scale
and its rounding, and differences between participants and stimuli. The
planned analysis then runs on each simulated dataset. Shortcuts such as
analytical formulas or rejection rates of a simpler test are not substitutes
for the planned analysis.

Participants are drawn afresh for each replicate. Stimuli are drawn afresh
too when the study aims to generalize beyond the particular stimuli used;
they stay fixed when the claim is only about that set. The same reasoning
applies to items, groups and networks.

The design simulation runs as standalone code on the experimenter's
computer, not through PsyNet's server, so that it can run thousands of
replicates. In an adaptive experiment, it simulates the full
cycle of choosing a stimulus, generating a response and updating the
estimates, and the adaptive procedure is one of the design factors compared.

The set of candidate designs should be fine enough to show where the
criterion is first met and where further participants or trials bring
little gain.

Adaptive stopping
-----------------

An adaptive procedure that can stop early does not use its maximum number of
trials. Comparing it with a fixed design at that maximum overstates its
efficiency. The simulation first finds a suitable fixed number of trials,
with stopping switched off, and then reports what the stopping rule saves
against that baseline: the average number of trials, the saving in time and
money, and the change in precision. Fewer trials are only a saving if the
precision cost is shown alongside.

Participant costs
-----------------

If the experiment pays participants, each design's precision is compared with
its cost. PsyNet estimates the payment per participant from the timeline's
time estimates and the hourly wage, and the cost of other designs follows
from the number of participants and trials. Before the timeline exists, the
costs come from planned page and trial durations and are labeled as
provisional. The report states the currency and whether the total includes
performance bonuses, recruiter fees, or extra recruitment to replace
participants who drop out.

Reporting the results
---------------------

The report starts with how to read the statistics and with the simulation's
assumptions: the response model, where its parameter values come from, the
numbers of participants and replicates, missing data, costs left out, and the
purpose of each alternative assumption set. It then shows precision against
the number of participants or trials, with the required precision marked,
and lists the smallest designs that meet the criterion, nearby alternatives,
and how the choice changes under the alternative assumptions.

What to check when reviewing a design simulation
------------------------------------------------

- Are the estimands the quantities the research question is about, and is
  every primary estimand evaluated?
- Is the estimator the analysis that will be run on the real data?
- Where do the response model's parameter values come from, and are values
  based on judgment identified as such?
- Do the alternative assumption sets cover the plausible range, and does the
  chosen design stay adequate across them?
- Are stimuli drawn afresh between replicates when the claim generalizes
  beyond the sampled stimuli?
- Is bias reported next to precision, and is the Monte Carlo error small
  enough not to change the chosen design?
- Were failed model fits counted rather than dropped?
- For an adaptive procedure that stops early, is it compared at its actual
  average number of trials?
- Are costs based on the current timeline, and does the report say what they
  include?

.. seealso::

   :doc:`/test/design_simulation` describes the files, code and commands for a
   design simulation in the experiment's audit.
