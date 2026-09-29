.. _concept_adaptive_experiments:

Adaptive experiments
====================

In an adaptive experiment, earlier responses decide what is measured or
assigned next: the next difficulty level, the next stimulus pair, the next
item in a test, or the condition a new participant is given. The rule that
makes this choice is the **selection policy**, and the thing it chooses is the
**adaptive unit**, such as a stimulus, an item, a node, a chain, or a
condition.

.. admonition:: What PsyNet provides

   PsyNet provides the building blocks: staircase and chain trial makers,
   selection hooks on trial makers (``custom_node_filter``, ``select_node``,
   ``custom_chain_filter`` and ``select_chain``), ``Trial.cue`` with page
   makers and loops for selection in the timeline, and asynchronous
   code blocks and scheduled tasks for background updates. It has no built-in
   adaptive-design framework: the specification, the state snapshots and the
   decision records described here are a recommended way of using those
   building blocks, implemented in your experiment's own code.

Kinds of adaptivity
-------------------

Adaptive designs differ in whose responses the policy uses:

- **Within-participant adaptivity** uses only the current participant's
  previous answers, together with a fixed model of the items or task.
  Staircases and computerized adaptive tests work this way. Each
  participant's state is their own, and nothing they do affects other
  participants.
- **Across-participant adaptivity** uses responses accumulated from everyone
  so far. Active learning, adaptive experimental design, and adaptive
  allocation to conditions work this way. One participant's answers change
  what later participants receive, and several participants may be choosing
  at the same moment.
- **Combined adaptivity** does both. For example, an online-calibrated test
  estimates each participant from their own answers, while the item
  difficulties are re-estimated from all participants' answers.

A design also states what the procedure estimates: attributes of participants
(an ability or a threshold), attributes of items (a difficulty), population
parameters, or a combination. Within- and across-participant estimates can
use different models and be updated on different schedules.

PsyNet supports several ways of building these designs:

- **Staircases** are a built-in within-participant design. The difficulty
  gets harder after a run of correct answers and easier after a mistake, in
  geometric steps. Each staircase stops after a maximum number of trials or a
  number of **reversals**, the points where the difficulty changes direction.
  The participant's score is the mean difficulty at the reversals, and PsyNet
  can pass or fail participants on that score.
- **Chains** make each new node from the responses to the previous one (see
  :doc:`chains`). A within-participant chain is a participant's own adaptive
  sequence. An across-participant chain is shared state that many
  participants move forward in turn.
- **Custom selection in the timeline** puts trials directly into a loop,
  without a trial maker. Before each trial, a function reads the
  participant's previous answers and chooses the next trial (see "Trials
  without a trial maker" in :doc:`trials`). This is the most flexible
  approach, and the usual choice for a custom within-participant procedure.
- **Custom selection in a trial maker** keeps a static or chain trial maker
  and replaces only the step that picks the next node or chain. Balancing,
  performance checks, and trial-based recruitment keep working.
- **Model-based selection**, such as active learning, fits a statistical
  model to the responses and picks the unit whose response is expected to be
  most useful, for example by expected information gain or Thompson
  sampling. PsyNet has no built-in trial maker for this. It is built from
  custom selection plus stored model fits, as described below.

Specifying the design
---------------------

An adaptive design needs these decisions before it is implemented:

- **Adaptive unit**: what the policy chooses.
- **Observations**: how each raw answer becomes the value the model uses,
  such as correct or incorrect, a rating, or a response time. The raw answer
  is kept as well.
- **Covariates**: which participant or context information the model uses,
  if any, such as age group or condition.
- **Learner model**: the likelihood, parameters, and priors used to learn
  from the observations. The learner model is part of the deployed
  experiment.
- **Update strategy**: whether the model is refit from all data each time,
  started from the previous fit but still given all data (a **warm start**),
  or updated incrementally with only the new data (**online learning**).
  Refitting from all data is the safest choice when several participants
  take part at once.
- **Selection policy**: the objective and decision rule, how ties are broken,
  and the eligibility rules, such as no repeated items or a maximum number of
  times each item is shown.
- **Stopping rule**: a fixed number of trials, or a rule based on the
  responses, with a maximum.
- **Refresh rule** (across-participant designs): when the shared model is
  refit, for example after every 20 new responses or every five minutes, and
  what selection does while no new fit is ready. Using the latest fit even if
  it is out of date, waiting for a new fit, and falling back to a fixed
  allocation are three different designs; choose one in advance.
- **Response time budget**: how long selection may take while the
  participant waits. Aim for under about a second.
- **Simulation response model**: how simulated participants answer. It can
  match the learner model or deliberately differ from it, to test what
  happens when the learner model is wrong. It is a testing assumption, not
  part of the experiment.
- **Acceptance criteria**: how much better than a non-adaptive design the
  adaptive design must be, set before the simulation results are seen.

Where the state lives
---------------------

The completed, non-failed trials are the authoritative record. Each trial
stores what was presented and what the participant answered. Everything the
policy uses, such as an ability estimate or a fitted model, is derived from
those trials.

- **Within-participant state** is usually recomputed from the participant's
  own completed trials before each selection. A stored estimate is only a
  shortcut and must agree with a recomputation.
- **Chain state** is the chain's current node. Only complete, fully
  processed, non-failed trials are used to make the next node.
- **Across-participant state** is fitted from all participants' trials. When
  fitting is too slow to run while a participant waits, it runs in the
  background, and each result is saved as a **snapshot**: a fitted model
  that is never changed once saved. A snapshot is marked **ready** only after
  it is completely saved, and selection reads only the newest ready snapshot.
  A failed fit is recorded, and selection keeps using the previous ready
  snapshot.

Each snapshot records which trials it was fitted from: their number, and an
identifier of the exact set, such as a hash of their sorted trial IDs. The
highest trial ID included is not enough, because an older trial can finish
after a newer one. Each snapshot also records the model version and random
seed, so it can be reproduced from the exported data.

Only one refit may claim each update. If two refits run at once, one must
fail cleanly rather than both publishing a snapshot. Online learning also
needs a guarantee that each response is added exactly once. A warm start is
only a starting value: the new fit must still include every response added
since the previous snapshot.

Stopping
--------

A fixed test length is the simplest stopping rule. A rule based on the
responses typically combines a minimum number of trials with a precision
target, or, for a staircase, a number of reversals. Every such rule also has
a maximum number of trials, because a precision target can fail to be reached
on unusual response patterns.

A variable-length loop needs an expected number of trials for the progress
bar and time estimates. By default, PsyNet gives every participant the same
time credit for the loop, based on that expected number, however many trials
they actually do. Setting the expected number to the maximum keeps estimates
from being too low. A time limit on the loop is also possible, but by default
it ends the experiment unsuccessfully for participants who reach it.

Recording decisions
-------------------

A trial records what happened. A **decision record** records why that trial
was assigned: the candidates considered, the one chosen, the policy's score
for it, the snapshot or history it was based on, and the version of the
policy code. The decision is saved when the trial is created, not after the
participant answers, and in the same database transaction as the trial, so
there is never a decision without its trial, or a trial without its decision.

Eligibility rules such as "no repeated items" are checked against the
decision records, because a trial that was assigned but never completed still
counts as shown.

Simulating before deployment
----------------------------

An adaptive policy is tested in two ways:

- A **standalone simulation** runs the whole adaptive procedure many times
  without starting PsyNet. It draws responses from the simulation response
  model and calls the same selection and stopping code the experiment uses.
  This tests the science: whether the policy recovers the true values it is
  meant to estimate.
- **Bots** run the adaptive procedure through the real experiment. This tests
  the integration: that trials are created, answers are stored, decisions are
  recorded, and the export contains everything the analysis needs. For
  across-participant designs, run several bots at once.

The standalone simulation compares the adaptive policy with at least one
realistic non-adaptive design, such as random order or a fixed test form,
using the same items, simulated participants, and maximum number of trials.
Compare the two at the same numbers of trials, so gains from better selection
are not confused with gains from collecting more data. When the stopping rule
is part of the design, also compare them with their real stopping rules, for
accuracy and length. The main result is a plot of how closely the estimates
match the simulated true values (for example their correlation, alongside
RMSE and bias) against the number of trials, one line per policy.

Repeat the comparison with simulation response models that deliberately
differ from the learner model, such as guessing, lapses of attention, or item
difficulties that are wrong, while keeping the adaptive policy unchanged.
This comparison belongs to the same simulation campaign as the power
analysis, in the audit's design simulation (see :doc:`design_simulation`). If the
adaptive policy does not clearly beat the non-adaptive one, prefer the
simpler design.

Risks
-----

- **Selection too slow.** Repeatedly refitting a large model from all trials
  while a participant waits makes pages slow to load.
- **Two participants at once.** Across-participant state read and written by
  several participants at the same time can lose or double-count responses.
- **A silent change of design.** Shortlisting candidates, approximating the
  model, updating in batches, or falling back to a fixed allocation changes
  the policy that is actually deployed. Such changes need to be part of the
  specification and the simulation.
- **Unbounded loops.** A stopping rule without a maximum can keep a
  participant in the loop indefinitely.
- **Unrecorded provenance.** Without decision records, the analysis cannot
  tell which model or history produced each assignment.
- **Uneven exposure.** An adaptive policy can show some items far more often
  than others, or suit some groups of participants better than others.

What to check when reviewing
----------------------------

- Is every decision in the specification written down, including the refresh
  rule and what happens while no new fit is ready?
- Does selection use only completed, non-failed trials?
- Is there a decision record for every adaptive trial, pointing to the
  snapshot or history it used?
- Does the stopping rule have a maximum, and does the expected number of
  trials match it?
- Is selection fast enough for the response time budget, measured rather
  than assumed?
- Does the standalone simulation call the same selection code as the
  experiment, and compare against a non-adaptive design, including under a
  misspecified response model?
- For across-participant designs, have several bots run at once, and does
  each snapshot record exactly which trials it was fitted from?

.. seealso::

   :doc:`/code/adaptive_experiments` shows how each of these ideas appears in
   code, using the ``demos/features/trial_cue_adaptive`` demo.
