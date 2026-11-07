Writing a round-based experiment
================================

Many group experiments are games played over several rounds: players are
paired or grouped, decide, see the result, and are grouped again for the
next round. This page builds one such game step by step, the
``ultimatum_pairing`` demo, and then shows how other games vary it. See
:doc:`synchronization` for the concepts used here.

In the demo, teams of up to four players form in a lobby. Each round, the
team is split into pairs, and in each pair a proposer offers part of 10
coins while the responder says the smallest offer they would accept. A
player who is slow, closes their tab or sits a round out never holds up the
others, and nobody is failed for it.

Forming teams
-------------

A :class:`~psynet.sync.SimpleGrouper` forms the teams. It starts a team
of four as soon as four players are waiting, or a smaller one after a
minute, and lets latecomers join until the team's second round starts:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: SimpleGrouper(
   :end-before: while_loop(
   :dedent: 8

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: team_accepts_newcomers

Pairing players each round
--------------------------

A :class:`~psynet.sync.Regrouper` at the start of each round splits the
team into new pairs. Each time a player reaches it, they leave last round's
pair and wait for the next split:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: pairing = Regrouper(
   :end-before: def play_round

The round starts as soon as the whole team is waiting, or at the
``deadline`` without whoever isn't back yet, if enough players are waiting to
form a pair; latecomers join the next round.
With ``roles``, each pair has a proposer and a responder, and each player
alternates between them. Partners from last round are kept apart where
possible. ``content`` counts down to the deadline:

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
:ref:`pseudonym's <chatroom-pseudonyms>` animal, which stays the same from
round to round. ``anonymous=True`` draws both players as the same grey figure
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
both partners. With ``timeout_between_barriers_action="kick"``, a player who
doesn't arrive in time is taken out of the pair, and their partner carries
on alone. For a player on a page with a time limit, the timeout counts from
the end of that limit, so it only needs to cover players who left the page.
For example, with a 30-second decision page and
``timeout_between_barriers_time=30``:

- A player who answers after 12 seconds waits at the barrier for their
  partner.
- A partner who leaves the page open without answering moves on at 30
  seconds, when the time limit runs out. The pair continues together, and
  nobody is paid.
- A partner who closes their tab partway through the page is taken out at
  60 seconds: 30 seconds after the time limit.
- A partner whose tab never opened the page is taken out 30 seconds after
  the round started.

30 seconds is long enough for a tab in the background to notice that a
round has started. A player who was taken out sees "Your partner went on
without you. Please continue." on the progress bar (pass
``on_arrival_message`` to the barrier to change it) and joins the next round
when they come back.

A barrier that kicks lets players who are no longer in a group pass
straight through (``skip_if_not_in_group`` defaults to ``True``). Pass
``skip_if_not_in_group=True`` to the round's other group barriers too;
without it, a player who reaches a group barrier outside a group gets an
error.

Scoring the round
-----------------

The barrier's ``on_release`` scores the pair once both have arrived, or once
the one who is left has. It stores each player's outcome, so that a page
reloaded later still shows it. When a partner left or ran out of time,
``score_round`` stores a message saying so and pays nobody. Otherwise it
looks up each player's role and pays out the offer:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: roles = {pairing.role(p): p for p in participants}
   :end-before: def decision_page
   :dedent: 4

The results page passes both answers to the prompt as speech bubbles:

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

With three players in a team, one of them has no partner. With
``release_left_over=True``, the player who has played the most rounds sits
the round out and sees a page saying so. A player who was paired but taken
out before reaching the decision page is told that they were away instead:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: not_playing

.. figure:: ../../_static/images/rounds/sit_out.png
   :width: 600
   :alt: A page saying "You sit out this round. It doesn't count towards your rounds."

Ending the game
---------------

The rounds loop runs until a player has played their rounds, has sat out
too often, or their team is down to one player:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: keep_playing

Players who finish leave the team, so that the regrouper doesn't wait for
them in later rounds:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: leave_team

.. _rounds-variations:

Variations
----------

**Larger groups.** The ``lowest_unique_number`` demo regroups all waiting
players into rooms of up to eight every 10 seconds, with
``deadline=Clock(10)`` and no ``within``. Each player picks a number, and
the room sees who has picked, who ran out of time and who is still deciding:

.. figure:: ../../_static/images/rounds/dash.png
   :width: 700
   :alt: A room of five: three players with a tick, one with a grey dash, and one still deciding

**Fixed roles.** With ``keep_roles=True``, players keep the role they first
play for the whole game, and newcomers get the role that lets the most
waiting players play.

**Your own grouping.** ``form_groups`` replaces the default grouping, for
example to pair players by their earlier answers. See
:class:`~psynet.sync.Regrouper` for this and the other settings.
