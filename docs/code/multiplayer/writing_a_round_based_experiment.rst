Writing a round-based experiment
================================

Many group experiments are games played over several rounds: players are
paired or grouped, decide, see the result, and are grouped again for the
next round. This page builds one such game step by step, the
``ultimatum_pairing`` demo, and then shows how other games vary it. Each
class and option links to its API reference where it first appears;
:doc:`synchronization` is the reference for everything else.

In the demo, cohorts of up to four players form as players arrive. Each round, the
cohort is split into pairs, and in each pair a proposer offers part of 10
coins while the responder says the smallest offer they would accept. A
player who is slow, closes their tab or sits a round out never holds up the
others, and nobody is failed for it. Each player's round is one trial, and
the two trials of a pair share a node that holds the pair's results, so the
game's data can be read back from trials and nodes.

Forming cohorts
---------------

A :class:`~psynet.sync.SimpleGrouper` forms the cohorts. It starts a cohort
of four as soon as four players are waiting, or a smaller one after a
minute (``start_short_after``), and lets latecomers join until the cohort's
second round starts (``join_existing_groups`` and ``join_criterion``; see
:class:`~psynet.sync.SimpleGrouper`):

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: SimpleGrouper(
   :end-before: Module(
   :dedent: 8

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: cohort_accepts_newcomers

Pairing players each round
--------------------------

A :class:`~psynet.sync.Regrouper` at the start of each round splits the
cohort into new pairs. Each time a player reaches it, they leave last round's
pair and wait for the next split:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: pairing = Regrouper(
   :end-before: OUTCOME_TEXTS

The round starts as soon as the whole cohort (``within``) is waiting, or at
the ``deadline`` (counted from when the first player is back) without whoever
isn't back yet, if enough players are waiting to
form a pair. A player who isn't back by then is still in the cohort, and
joins the next round.
With ``roles``, each pair has a proposer and a responder, and each player
alternates between them. Partners from last round are kept apart where
possible. ``waiting_message`` counts down to the deadline. See
:class:`~psynet.sync.Regrouper` for these options:

.. figure:: ../../_static/images/rounds/next_round.png
   :width: 700
   :alt: A waiting page saying "The next round starts in at most 25 s."

The regrouper keeps the round's bookkeeping, so the game doesn't need to
store it in participant variables:

- ``pairing.role(participant)`` is ``"proposer"`` or ``"responder"``;
- ``pairing.rounds_played(participant)`` counts the pairs the player has
  joined, including one whose partner left or that they were removed from;
- ``pairing.rounds_sat_out(participant)`` counts the rounds they sat out,
  and ``pairing.sat_out(participant)`` says whether they sat out the
  latest one.

.. _rounds-cued-trials:

One trial per player per round
------------------------------

Each round of the timeline is the regrouper followed by one trial per player,
added with :meth:`Trial.cue() <psynet.trial.main.Trial.cue>`, without a trial
maker:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: Module(
   :end-before: leave_group("cohort")
   :dedent: 8

The trial class sets ``sync_group_type``, so the trials that a pair's
members cue in a round share one :class:`~psynet.trial.main.SyncGroupNode`.
Each trial records the pair (``sync_group_id``), the player's role
(``sync_group_role``), the pair's round (``sync_group_round``) and how the
round ended for the player (``sync_group_outcome``, see
:ref:`rounds-explaining-the-outcome`), and keeps
them after the pair ends. The ``Module`` gives the nodes a ``module_id`` to
find them by when exporting.

``cue`` numbers each group's rounds by itself, from 0:

- A cue joins the group's newest node in the module while that round is
  open and the player has no trial on it. A round closes when a barrier in
  its trial (in ``show_trial``) releases the group, and only then.
- Otherwise it starts the group's next round.

So every pair here, new each round, plays round 0, while a fixed group cued
in a loop plays rounds 0, 1, 2 and so on, whichever trial classes it cues.
A member who joins it late joins its current round only until a barrier
in that round's trial releases the group. After that, even while the others are
still on a page after the barrier, the newcomer starts the next round,
which the others then join. So put a ``GroupBarrier`` in each round,
inside ``show_trial`` after the answer page, as in the one below: it
keeps the members in step, and its release closes the round. A round
without one never closes, so a latecomer can join it after the others
have finished. In a module that a loop repeats, a member's first cue in
the next run can also join the previous run's last round while it is open,
so end each round there with a ``GroupBarrier`` that closes it.

.. _rounds-barrier-visits:

When a member reaches a ``GroupBarrier``, PsyNet records which of two kinds
of visit it is:

- A **round visit**, if the member is in their cued trial of the group and
  the trial hasn't ended, that is, the barrier is in ``show_trial``. It
  waits for the members whose current trial is in that round, and, while the
  round is open, for those who haven't cued yet, because their cue will
  join it. Its release closes the round, and ``on_release`` gets the
  round's node.
- A **group visit**, from any other barrier: before the first cue, in
  ``show_feedback``, at the start of each iteration, after the loop, or
  where the group cues no rounds. It waits for every member, whatever
  round they are in, and ``on_release`` gets ``node=None``.

Neither kind waits for a member who has finished the barrier's module, as
when their loop ended earlier. An ID used both inside ``show_trial`` and
outside it gives two separate barriers, one of each kind, which can wait
for each other like any two barriers; PsyNet logs a warning when members
visit both, so give them distinct IDs. Every release, except letting one
member go after ``max_wait_time``, is the group's pass: ``on_release`` runs,
and the pass counts for ``left`` and ``late_after``. For example:

.. code-block:: python

    class EstimateTrial(Trial):
        sync_group_type = "team"

        def show_trial(self, experiment, participant):
            return join(
                self.estimate_page(),
                GroupBarrier(id_="estimates", group_type="team",
                             on_release=self.score_round),   # round visit; closes the round
                PageMaker(self.revise_page, time_estimate=10),
            )

    Module("game", for_loop(label="q", iterate_over=range(3),
                            logic=lambda q: EstimateTrial.cue({"q": q}, round=q)))

A late joiner skips the rounds that have closed, joins the open one, and
``estimates`` waits for them there. A member who skipped a round never
visits its barriers, and one who is already in the next round has no trial
on this one, so neither holds it up. :doc:`catch_up_case_studies` follows
these and other cases, such as players leaving or reading slowly, step by
step.

.. _rounds-group-barriers-in-loops:

Keep a round's barriers in ``show_trial`` if the group can take newcomers
during the module. A group barrier inside the loop, such as
``GroupBarrier("ready", ...)`` at the start of each iteration or one in
``show_feedback``, waits for every member, so a newcomer who reaches it
waits for members who are waiting in the round's trial for them. Neither
can pass until ``late_after`` or ``max_wait_time`` moves someone on, and
PsyNet logs a warning naming both barriers. ``late_after`` on either
barrier fails the members it waits for at the other, so ``late_after`` on
the round's barrier can fail a newcomer who arrived on time at the group
barrier. Move that barrier into
``show_trial``, or stop newcomers from joining during the module with
``stop_top_ups=True`` on a barrier before it (see the ``stop_top_ups``
argument of :class:`~psynet.sync.GroupBarrier`).

In a module that a loop repeats, a barrier at the start of the next run is
a group visit too: it waits for every member still in the module,
including one still finishing the previous run and a newcomer starting
their first run, and not for a member whose loop has ended. A member on a
page between the module and its next run, inside the loop but outside the
module, counts as having left it. So a faster member's next run starts
without them, and the group drifts out of step: they play rounds alone, or
wait for each other until ``late_after`` or ``max_wait_time`` acts. PsyNet
raises a ``ValueError`` when the experiment loads if a ``while_loop`` after
a grouper shows content pages between runs of a group module it repeats,
with no barrier between the pages and the next run. A group module is a
trial maker with a ``sync_group_type``, or any other module that directly
contains a ``GroupBarrier`` or a page maker such as a ``for_loop`` of
cued rounds. A module around one, such as a ``"session"`` module around
the game, isn't, as a barrier waits only for the members still in its own
module, and a round for those in its trial maker. Other modules, such as
a quiz each player takes alone, aren't checked themselves, but their
pages count as pages between runs, as do pages in an outer module after
the game. The error names the group module. Move the pages into it, or
add a ``GroupBarrier`` right after them, outside it, which waits for the
members on the pages too, so each run starts together. A trial maker
can't hold the pages, so it needs the barrier:

.. code-block:: python

    # Raises: a member on "Break" has left "game", so the next run starts without them.
    while_loop("runs", play_again, join(Module("game", rounds), break_page), 2)

    # Raises too: "session" doesn't count, so a member on "Break" has left "game".
    while_loop("runs", play_again, Module("session", Module("game", rounds), break_page), 2)

    # Keep the break inside the module...
    while_loop("runs", play_again, Module("game", rounds, break_page), 2)

    # ... or wait for the group after it, outside the module.
    ready = GroupBarrier(id_="ready", group_type="pair")
    while_loop("runs", play_again, join(Module("game", rounds), break_page, ready), 2)

A barrier inside the module, at its start, doesn't count, as it doesn't
wait for members who have left the module; nor does a barrier before the
pages, or one in a module that the pages aren't in. A barrier's own
waiting page isn't a content page. Pages inside a ``switch`` or
``conditional`` count as shown, whichever branch they are in, but a
barrier inside one doesn't count, as members on another branch don't pass
it. The check has limits:

- It decides which modules are grouped from what they contain at load, so
  a module whose page maker only builds solo pages still counts as one;
  moving the pages into the module is harmless then.
- A barrier in every branch of a ``switch`` still doesn't count; put one
  barrier after the ``switch`` instead.
- A ``for_loop`` or :class:`~psynet.timeline.PageMaker` builds its logic
  when the participant reaches it, so the check can't see what it shows.
  If one is all there is between the runs, PsyNet warns instead of
  raising, and doesn't see a module inside it.

The warning at run time, when the group and a member wait for each other,
still catches the cases the check misses.

A barrier in a module where the group cues no rounds, such as one before a
separate module of rounds, waits for every member too: a newcomer who
reaches it after the group has gone waits there for members who are
further on, until the barrier's time-outs remove someone. Give such a
barrier ``pass_newcomers=True`` (see :ref:`sync-newcomers-at-passed-barriers`).

So a trial has two round counters. ``sync_group_round`` counts the group's
rounds, and is ``None`` on a trial played without a group. Use it for what
the group shares, such as what a round shows and the group's rows in the
export. ``trial.position`` counts the player's own trials in the
module, grouped or not. Use it for the player's own sequence, such as the
round in a per-player export when groups change every round. The two agree
only in a fixed group that every member joined before the loop. In a fixed
group's loop with ``round=`` (below), ``sync_group_round`` is the loop
value.

Every trial in a round gets the definition of the round's first cue. Here,
a definition taken from the player's own position in the loop, as in
``logic=lambda i: OfferTrial.cue({"block": i})``, would fail: a pair that
the regrouper forms from players at different rounds would cue two
definitions for one round and get a ``ValueError``. Use a function taking
``round`` or ``group`` instead, such as
``OfferTrial.cue(lambda round: {"block": round})``. A round with no content
of its own needs no definition: ``OfferTrial.cue()`` gives every trial
``{}``.

.. _rounds-fixed-group-loop:

A fixed group that plays a loop of rounds together should pass the loop
value as ``round=``:

.. code-block:: python

    for_loop(
        label="questions",
        iterate_over=range(len(QUESTIONS)),
        logic=lambda i: EstimateTrial.cue({"question": i}, round=i),
        time_estimate_per_iteration=EstimateTrial.time_estimate,
    )

Each iteration is then the group's round of that number, whoever cues it
first, so its definition can come from the loop. A member who joins late
skips the rounds that the group finished without them: rounds where they
have no trial and whose barrier in ``show_trial`` has released the group.
They play the rest, and the barriers of a round they skipped don't wait for
them. A skipped
round shows nothing and earns no time credit, but the progress bar moves on
as if it had been played. A skipped cue leaves ``participant.current_trial``
as ``None``, so code after the cue in the same iteration that reads the
trial, such as a page showing ``participant.current_trial.answer``, should
check for it first:

.. code-block:: python

    logic=lambda i: join(
        EstimateTrial.cue({"question": i}, round=i),
        conditional(
            "played_round",
            lambda participant: participant.current_trial is not None,
            PageMaker(
                lambda participant: InfoPage(
                    f"You answered {participant.current_trial.answer}."
                ),
                time_estimate=5,
            ),
        ),
    )

A member who leaves the group plays the remaining
iterations alone, with the same loop values. One who leaves and rejoins
it skips a cue of a round in which they already have a trial of that
class, even an open round.
Rounds are ordered by when
the group first plays them, so the loop values needn't increase. Don't
pass ``round=`` with a
regrouper: its groups mix players at different loop positions, whose trials
would be split across rounds. A module whose cues pass ``round=`` runs once
per participant, because a group's rounds belong to the module id: give
each run its own module id. Its cues raise an error if the participant has
run the module before. Cueing a round again after a later one, even one
the participant skipped, or a trial class again in the same round, also
raises an error.

Classes cued in the same open round share its node and definition: if the
members cue different classes, such as an offer trial for the proposer and
a reply trial for the responder, their trials share the node. Put
role-specific content in the definition, keyed by role, or derive it from
``self.sync_group_role``. A round with two phases, such as an offer and a
reply, is normally one trial class with several pages. Only phases played
one after the other by trials of two classes need ``round=``, because the
second cue would otherwise start the next round, the player already having
a trial on the round's node. Pass both cues the same ``round=``, such as
the loop value in a fixed group's loop. A member with a trial in the round
joins it even after its barrier has released the group, while a late
joiner without one skips the whole round, both phases, and the second
phase's round barriers don't wait for them.

The ``switch`` decides once, before the trial: a player in a pair gets
the trial, one who sat out gets a page instead (see
:ref:`rounds-sitting-out`), and one whose cohort has gone moves on to the
page saying the game ended early:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: round_status

Once started, the trial runs to its end, where
it is scored, even if the player is removed from their pair partway, so
its feedback covers every outcome of the round. A round that is one cued
trial needs no more than this; ``join(..., stop_if=...)`` is for rounds of
several steps.

The trial's ``show_trial`` is the decision page followed by a
:class:`~psynet.sync.GroupBarrier` for the pair:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: OfferTrial.show_trial

Making a decision
-----------------

The decision page reads the player's role from the trial, and its
:class:`~psynet.group_prompt.GroupPrompt` shows the pair. The partner gets
a tick as soon as they have decided. Players normally appear as their
:doc:`pseudonym's <pseudonyms>` animal, which stays the same from
round to round. ``names="anonymous"`` draws both players as the same grey figure
instead, so that nobody recognises a partner from an earlier round:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: OfferTrial.decision_page

.. figure:: ../../_static/images/rounds/decision.png
   :width: 600
   :alt: The responder's decision page, with a tick on the partner who has already decided

The page's ``time_limit`` gives each player 30 seconds. A player who
doesn't answer in time moves on with no answer (``time_limit_answer``,
``None`` by default), and their partner sees a grey dash instead of a
tick.

.. _rounds-slow-players:

Moving slow players on
----------------------

The barrier after the decision page waits for
both partners. A player who hasn't reached it within ``late_after`` seconds
of the round's start is late, and with ``late_action="leave_group"`` is removed
from the pair, so that their partner carries on alone (see
:class:`~psynet.sync.GroupBarrier` for both options). A player on a page
with a time limit is not late before that limit has run out and an answer
sent at the deadline has had 10 seconds to arrive, so the late limit need
not be longer than the page's time limit.
For example, with a 30-second decision page and
``late_after=30``:

- A player who answers after 12 seconds waits at the barrier for their
  partner.
- A partner who leaves the page open without answering moves on at 30
  seconds, when the time limit runs out. The pair continues together, and
  nobody is paid.
- A partner who closes their tab partway through the page is removed from
  the pair about 40 seconds into the round: 10 seconds after the page's time
  limit.
- A partner whose tab never opened the page is removed from the pair 30
  seconds after the round started.

30 seconds is long enough for a tab in the background to notice that a
round has started. ``late_after`` counts from the previous barrier, so pages
without a time limit before the decision page, such as the last round's
results, count towards it: give them a time limit too, or make
``late_after`` long enough for a slow reader. A player who was removed from the pair sees "Your
partner went on without you. Please continue." on the progress bar (pass
``on_arrival_message`` to the barrier to change it).

With ``late_action="leave_group"`` a late player would leave the pair only
(see :ref:`sync-leaving-a-group`), so they would still be in the cohort, and
the next split would wait for them until its deadline. A late player has
usually closed their page, so the demo uses ``late_action="leave_all_groups"``,
which takes them out of the cohort too. The barrier checks for late players
only while their partner waits at it, so if neither partner comes back, the
next split waits for its deadline. A late player who comes back is told that
they were away, and their game ends.

The cohort's grouper sets ``below_quorum="continue_without_group"``. In this
demo it never takes effect: the cohort accepts top-ups and the demo never
stops them, so the cohort isn't dissolved here, and ``keep_playing`` (below)
ends the game once fewer than two players are left. It makes the recipe
safe to copy into a cohort without top-ups, or one whose top-ups stop (see
:ref:`groups_below_min_size`), where removing a late player would dissolve
the cohort if that left it below its quorum, and the default
``below_quorum="fail"`` would fail the players who were on time.

A player removed from their pair finishes the trial: its later group
barriers let them straight through, and its feedback tells them they were
away, because their trial's ``sync_group_outcome`` is ``"late"``.

Scoring the round
-----------------

The barrier's ``on_release`` scores the pair once both have arrived, or once
the one who is left has. It takes ``trials``, the members' trials, and
``node``, the node they share, so a ``@classmethod`` on the trial class can
save the pair's offer and result on the node and each player's coins on
their trial, where a page reloaded later still finds them. When a partner
left or ran out of time, nobody is paid. The ``left`` argument lists the
members who left the pair this round, and
``sync_group_removal_reason`` tells a partner who was too slow apart from
one who returned the study. ``trials`` only holds the trials of members
still in the pair, so the players of the round come from ``node.all_trials``,
which also keeps the trial of a player removed for being away:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: OfferTrial.score_pair

The barrier is inside ``show_trial``, so the trials have not ended yet when
``on_release`` runs: ``trial.answer`` holds each member's answer so far,
which here is their decision, or ``None`` if their page ran out of time.

.. _rounds-explaining-the-outcome:

Explaining the outcome
----------------------

The trial ends after the barrier, so its feedback can read what was stored
during the round rather than work it out from the player's groups:

- ``self.sync_group_outcome`` says how the round ended for this player:
  ``"stayed"`` once the barrier released the pair with them in it, or why
  they left the pair before then, here ``"late"`` for a player taken out for
  being away (see :ref:`round outcomes <sync-round-outcome>` for every value);
- ``self.answer`` is their own decision, ``None`` if they ran out of time;
- ``self.node.var`` holds what ``on_release`` saved for the pair.

A partner's outcome is on their trial in ``self.node.all_trials``.
``outcome`` turns these into one key of ``OUTCOME_TEXTS``:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: OfferTrial.outcome

``show_feedback`` shows that text, and when the pair made a deal, passes
both answers to the prompt as speech bubbles:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: OfferTrial.show_feedback

.. figure:: ../../_static/images/rounds/outcome.png
   :width: 600
   :alt: The results page, with "I offer 6" and "I accept 4+" speech bubbles

.. figure:: ../../_static/images/rounds/ran_out.png
   :width: 600
   :alt: The results page of a player who ran out of time: "You ran out of time, so nobody was paid."

   A player whose time ran out.

To pay a bonus as well, return a score from ``score_answer`` and the bonus
from ``compute_performance_reward``, as the ``lowest_unique_number`` demo
does; both run when the trial ends, after ``on_release``.

.. _rounds-sitting-out:

Sitting out
-----------

With three players in a cohort, one of them has no partner. The player who has
played the most rounds sits the round out; with ``left_over="sit_out"``
they move on without a pair instead of waiting (see
:class:`~psynet.sync.Regrouper`), so the ``switch`` gives them a page
instead of a trial that round. A player who was paired but removed from the
pair before submitting their decision has a trial, and the first check in
``outcome`` above tells them that they were away.

.. figure:: ../../_static/images/rounds/sit_out.png
   :width: 600
   :alt: A page saying "You sit out this round without a partner. If you sit out 2 rounds, the game ends early for you."

Ending the game
---------------

The rounds loop runs until a player has played their rounds, has sat out
too often, has left the cohort, or their cohort is down to one player:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: keep_playing

Players who finish leave the cohort with
:func:`leave_group("cohort") <psynet.sync.leave_group>`, so that the
regrouper doesn't wait for them in later rounds. It removes them with
``reason="finished"``, which shows them as "(finished)" and never dissolves
the cohort. This cohort accepts top-ups and the demo never stops them, so
another reason wouldn't dissolve it either, but ``"finished"`` keeps the
recipe safe to copy into a cohort without top-ups, or one that stops them,
where the last players finishing their rounds could otherwise leave it
below its quorum (see :ref:`groups_below_min_size`).

Exporting the rounds
--------------------

The results stay on the trials and nodes, so ``get_basic_data`` builds one
table per player per pair from the trials, including each player's
``sync_group_outcome``, and one per pair from the nodes.
Rounds a player sat out have no trial, so a third table counts them with the
regrouper (see :doc:`/data/basic_data`):

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: Exp.get_basic_data

.. _rounds-variations:

Variations
----------

**Larger groups and fixed rounds.** The ``lowest_unique_number`` demo
regroups all waiting players into rooms of up to eight every 10 seconds,
with ``every=10`` and no ``within``, for a fixed number of rounds. Each
room is new, so its trials are all in round 0. A room can mix players at
different rounds of the game, for example a latecomer playing their first
round with others playing their second, so the export numbers each player's
own trials as their round:

.. literalinclude:: ../../../demos/experiments/lowest_unique_number/experiment.py
   :pyobject: get_timeline

A player left with nobody to play with, for example a latecomer whose
last round comes after everyone else has finished, waits at the regrouper
for up to a minute. Then ``max_wait_action="continue_without_group"`` lets
them carry on without a room, and the ``conditional`` shows them a short
page instead of the round, rather than failing them.

Each player picks a number, and the room sees who has picked, who ran out
of time and who is still deciding:

.. figure:: ../../_static/images/rounds/dash.png
   :width: 700
   :alt: A room of five: three players with a tick, one with a grey dash, and one still deciding

The barrier's ``on_release`` applies the winning rule once and saves the
room's result in ``node.var.result`` (``"won"``, ``"no_unique_number"`` or
``"one_choice"``), so the feedback and the export read it rather than apply
the rule again.

**A draw per group.** ``definition`` can also be a function, for example
``lambda group: {"target": random.choice(TARGETS)}``. It is called once per
group and round, when the first member's trial creates the node, so the
whole group plays the same draw. A player who is in no group of that type
when the trial starts gets an ungrouped trial, with ``sync_group_id`` set to
``None``; ``show_trial`` can check ``self.sync_group is None`` to give them
a solo version.

**Fixed roles.** With ``keep_roles=True``, players keep the role they first
play for the whole game, and newcomers get the role that lets the most
waiting players play.

**Turns one after the other.** In games such as a trust game, the investor
decides before the trustee. With cued trials, the role pages and the
barriers between turns all go in the ``show_trial`` of one trial class. Put
each role's page in a
:func:`~psynet.timeline.conditional` on the role, followed by a
:class:`~psynet.sync.GroupBarrier` for the pair: the other player waits at
the barrier while it is not their turn. A ``waiting_screen`` on the barrier
tells them whose turn it is; a :class:`~psynet.group_prompt.GroupPrompt` with
``show_progress=False`` shows the pair there without the waiting
player's own tick. In bot tests, ``advance_past_wait_pages(bots,
stop_at="investor_sent")`` leaves the bots waiting at that barrier, so the
test can take the investor's turn first. Once the investor's answer releases
the barrier, the same call moves the trustee on: ``stop_at`` holds only bots
the barrier hasn't released yet. The first turn's barrier closes the round
to newcomers: a player who joins the pair after it starts the next round
rather than joining a round whose first turn is over.

**Your own grouping.** ``form_groups`` replaces the default grouping, for
example to pair players by their earlier answers. With roles, return each
group as a ``{role: participant}`` dict. See
:class:`~psynet.sync.Regrouper` for this and the other settings.

**A trial maker.** A trial maker with ``sync_group_type``, as in the
``rock_paper_scissors`` demo, gives a group's members their trials
together and numbers the group's rounds from 0 in ``sync_group_round``.
Cued trials suit games whose groups change every round, or whose rounds are
a plain loop in the timeline.
