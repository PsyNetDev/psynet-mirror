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
others, and nobody is failed for it.

Forming cohorts
---------------

A :class:`~psynet.sync.SimpleGrouper` forms the cohorts. It starts a cohort
of four as soon as four players are waiting, or a smaller one after a
minute (``start_short_after``), and lets latecomers join until the cohort's
second round starts (``join_existing_groups`` and ``join_criterion``; see
:class:`~psynet.sync.SimpleGrouper`):

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: SimpleGrouper(
   :end-before: while_loop(
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
   :end-before: def play_round

The round starts as soon as the whole cohort (``within``) is waiting, or at
the ``deadline`` (counted from when the first player is back) without whoever
isn't back yet, if enough players are waiting to
form a pair; latecomers join the next round.
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
  been in;
- ``pairing.rounds_sat_out(participant)`` counts the rounds they sat out,
  and ``pairing.sat_out(participant)`` says whether they sat out the
  latest one.

Each round of the timeline then looks like this:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: play_round

Making a decision
-----------------

The decision page reads the player's role, and its
:class:`~psynet.group_prompt.GroupPrompt` shows the pair. The partner gets
a tick as soon as they have decided. Players normally appear as their
:doc:`pseudonym's <pseudonyms>` animal, which stays the same from
round to round. ``names="anonymous"`` draws both players as the same grey figure
instead, so that nobody recognises a partner from an earlier round:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: decision_page

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

The :class:`~psynet.sync.GroupBarrier` after the decision page waits for
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
``on_arrival_message`` to the barrier to change it) and joins the next round
when they come back.

A player who was removed from their pair passes the round's later group
barriers straight through. A player who was never in a pair, or whose pair
was closed by a :class:`~psynet.sync.GroupCloser`, gets an error there,
which usually means a grouper is missing.

Scoring the round
-----------------

The barrier's ``on_release`` scores the pair once both have arrived, or once
the one who is left has, and records the round (see
:ref:`basic_data_regrouper`): ``barrier.record_group`` stores the pair's
offer and its result once, and ``barrier.record`` each player's decision
and coins. A page reloaded later still shows them. When a partner left or
ran out of time, nobody is paid. The ``left`` argument lists the members
who left the pair this round, and ``sync_group_removal_reason`` tells a
partner who was too slow apart from one who returned the study:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: score_round

The results page reads the pair's round with
:func:`~psynet.sync.group_rounds`, passes both answers to the prompt as
speech bubbles, and reads the player's coins from their own round with
:func:`~psynet.sync.participant_rounds`:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: show_outcome

.. figure:: ../../_static/images/rounds/outcome.png
   :width: 600
   :alt: The results page, with "I offer 6" and "I accept 4+" speech bubbles

.. figure:: ../../_static/images/rounds/ran_out.png
   :width: 600
   :alt: The results page of a player who ran out of time: "You ran out of time, so nobody was paid."

   A player whose time ran out.

Sitting out
-----------

With three players in a cohort, one of them has no partner. The player who has
played the most rounds sits the round out; with ``left_over="sit_out"``
they move on to a page saying so instead of waiting (see
:class:`~psynet.sync.Regrouper`). A player who was paired but removed
from the pair before reaching the decision page is told that they were away
instead:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: not_playing

.. figure:: ../../_static/images/rounds/sit_out.png
   :width: 600
   :alt: A page saying "You sit out this round. It doesn't count towards your rounds."

Ending the game
---------------

The rounds loop runs until a player has played their rounds, has sat out
too often, or their cohort is down to one player:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: keep_playing

Players who finish leave the cohort, so that the regrouper doesn't wait for
them in later rounds. With ``reason="finished"`` their leaving doesn't
dissolve the cohort below its quorum, so the last players aren't told that
too few players remained while they finish their own rounds. A later
``GroupBarrier`` for the cohort would still dissolve it below its quorum;
here, only the pairs have barriers:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: leave_cohort

.. _rounds-variations:

Variations
----------

**Larger groups.** The ``lowest_unique_number`` demo regroups all waiting
players into rooms of up to eight every 10 seconds, with
``every=10`` and no ``within``. Each player picks a number, and
the room sees who has picked, who ran out of time and who is still deciding:

.. figure:: ../../_static/images/rounds/dash.png
   :width: 700
   :alt: A room of five: three players with a tick, one with a grey dash, and one still deciding

**Fixed roles.** With ``keep_roles=True``, players keep the role they first
play for the whole game, and newcomers get the role that lets the most
waiting players play.

**Turns one after the other.** In games such as a trust game, the investor
decides before the trustee. Put each role's page in a
:func:`~psynet.timeline.conditional` on the role, followed by a
:class:`~psynet.sync.GroupBarrier` for the pair: the other player waits at
the barrier while it is not their turn. A ``waiting_screen`` on the barrier
tells them whose turn it is; a :class:`~psynet.group_prompt.GroupPrompt` with
``show_progress=False`` shows the pair there without the waiting
player's own tick. In bot tests, ``advance_past_wait_pages(bots,
stop_at="investor_sent")`` leaves the bots waiting at that barrier, so the
test can take the investor's turn first. Once the investor's answer releases
the barrier, the same call moves the trustee on: ``stop_at`` holds only bots
the barrier hasn't released yet.

**Your own grouping.** ``form_groups`` replaces the default grouping, for
example to pair players by their earlier answers. With roles, return each
group as a ``{role: participant}`` dict. See
:class:`~psynet.sync.Regrouper` for this and the other settings.
