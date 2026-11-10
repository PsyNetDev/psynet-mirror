Late, slow and leaving players: case studies
============================================

Group games rarely run as planned: a player joins after the game has
started, another closes their tab, a third reads the results slowly. This
page follows eight such cases through concrete designs, and says what
each player sees, whom they wait for and when they move on. The rules
behind them are in :ref:`round barriers and group barriers
<rounds-barrier-visits>` and :ref:`sync-dropout-settings`; this page only
applies them. Each case ends with the test that checks it, so if PsyNet's
behaviour changes, the test fails until the page is updated.

All the cases share one design, a fixed group answering a loop of
questions, unless the case says otherwise. Each question is one round: a
cued trial whose ``show_trial`` ends with a :class:`~psynet.sync.GroupBarrier`,
so the barrier waits for that round's players and its release closes the
round (see :ref:`rounds-cued-trials`):

.. code-block:: python

    class EstimateTrial(Trial):
        sync_group_type = "team"

        def show_trial(self, experiment, participant):
            return join(
                self.estimate_page(),
                GroupBarrier(id_="submitted", group_type="team",
                             on_release=self.score_round),
                self.revise_page(),
            )

    Timeline(
        SimpleGrouper(group_type="team", initial_group_size=2),
        Module(
            "game",
            for_loop(label="q", iterate_over=range(3),
                     logic=lambda q: EstimateTrial.cue({"q": q}, round=q)),
        ),
    )

The players are called Ann, Ben and Cat, and times count from the start of
the round. A barrier without ``late_after`` lets each member wait at most
its ``max_wait_time``, 20 s by default; the cases assume shorter waits,
except the one where the wait runs out. When a design makes members wait
for a slow page, size that limit or ``late_after`` for it (see
:ref:`sync-timeouts`).

A fixed pair
------------

Ann and Ben are paired and both play every round. Ann submits her estimate
at 12 s, Ben at 25 s.

- Ann waits at ``submitted`` from 12 s to 25 s.
- At 25 s the barrier releases both, ``on_release`` scores the round once,
  and the round closes. Both trials record ``sync_group_outcome="stayed"``.

Nobody waits longer than the slower partner takes. To stop a partner who
never answers from holding the other up, give the estimate page a
``time_limit`` and the barrier ``late_after`` (see :ref:`rounds-slow-players`).

Checked by ``test_case_a_fixed_pair_waits_only_for_the_slower_partner`` in
``tests/isolated/test_trial_cue_groups.py``.

A late joiner while the round is open
-------------------------------------

The grouper takes newcomers (``join_existing_groups=True``, with a
``max_group_size`` of 3).

1. Ann and Ben start round 0. Ann submits and waits at ``submitted``.
2. Cat joins the group, and Ben submits.
3. Cat's cue joins round 0: same node, same definition. She submits.

Ben doesn't pass at step 2: the round is still open and Cat has no trial in
it yet, so the barrier waits for her too. All three are released together
when Cat arrives, and ``on_release`` scores the round for all three. So Ann
and Ben wait for Cat's whole estimate page. ``late_after`` counts for Cat
from when she joined, so a newcomer who never comes back holds the others
up for at most ``late_after`` after joining.

Checked by
``test_case_a_late_joiner_joins_the_open_round_and_its_barrier_waits_for_them``
in ``tests/isolated/test_trial_cue_groups.py``.

A late joiner after the round has closed
----------------------------------------

The same grouper, but Cat joins later:

1. Ann and Ben both submit in round 0; ``submitted`` releases them and the
   round closes. They move on to the revise page.
2. Cat joins the group.
3. Cat's cue of round 0 is skipped: she sees nothing for it, and the
   progress bar moves on. A later barrier of round 0, such as one after the
   revise page, doesn't wait for her.
4. Cat's cue of round 1 starts that round. She submits and waits at
   ``submitted``.
5. Ann and Ben finish round 0, and their cues of round 1 join Cat's round.
   When both have submitted, all three are released.

So Cat skips the round she was too late for and then waits, at round 1's
barrier, for the others to finish round 0. Code that reads
``participant.current_trial`` right after the cue should check it for
``None``, which it is after a skipped cue (see
:ref:`a fixed group's loop of rounds <rounds-fixed-group-loop>`).

Checked by ``test_case_a_late_joiner_skips_a_closed_round_and_waits_in_the_next``
in ``tests/isolated/test_trial_cue_groups.py``.

A member leaves partway through a round
---------------------------------------

The group has no top-ups and the grouper sets
``below_quorum="continue_without_group"``. Ann (and Ben, in a group of
three) submit and wait at ``submitted``; then the last member returns the
study.

- **The group keeps its quorum** (three players, ``quorum=2``): the barrier
  stops waiting for the member who left. Ann and Ben are released at the
  next barrier check, usually within a second or two. ``on_release`` runs
  with ``left`` listing the leaver, and Ann's and Ben's trials record
  ``"stayed"``.
- **The group falls below its quorum** (a pair): it is dissolved. Ann is
  released, ``on_dissolve`` runs for her instead of ``on_release``, her
  trial records ``"group_dissolved"``, and her next page says "Your
  partner is no longer in your group. Please continue." She plays the rest
  of the timeline without a group (see :ref:`sync-leaving-a-group`).

With the default ``below_quorum="fail"``, a dissolved group fails Ann
instead, and a group that still takes newcomers is not dissolved but waits
at the barrier for one (see :ref:`groups_below_min_size`).

Checked by ``test_case_a_member_leaves_mid_round`` in
``tests/isolated/test_trial_cue_groups.py``, for both group sizes.

A slow reader between runs of a looped module
---------------------------------------------

The pair plays the whole game several times, with a results page after
each run, and ``submitted`` has a ``max_wait_time`` longer than Ben's
reading. A module that runs again can't pass ``round=``, so the cues
don't number their rounds:

.. code-block:: python

    rounds = for_loop(label="q", iterate_over=range(3),
                      logic=lambda q: EstimateTrial.cue({"q": q}))
    while_loop("runs", play_again, Module("game", rounds, results_page), 2)

1. Ann and Ben finish run 1's last round together.
2. Ann reads the results for 5 s, starts run 2, submits her first estimate
   and waits at ``submitted``.
3. Ben reads the results for 60 s. His first cue of run 2 joins Ann's
   round, and when he submits, both are released.

Ann waits for Ben's reading and his estimate: the round is open, and Ben is
still in the module, on its results page, with no trial in the round yet.
With the default ``max_wait_time`` of 20 s, Ann's wait would run out and
fail her, so give the results page a ``time_limit``, or size the barrier's
limits for slow readers.

**With the results page outside the module**, as in
``while_loop("runs", play_again, join(Module("game", rounds), results_page), 2)``,
Ben on the results page would count as having left the module, so nothing
would wait for him. At step 2, Ann would play run 2's first round alone,
and the pair would drift out of step. PsyNet therefore refuses this
timeline when the experiment loads:

.. code-block:: text

    ValueError: A while_loop repeats module 'game' and shows pages 'results'
    between its runs, outside the module, with no barrier after them. [...]
    Move the pages into the module, or add a GroupBarrier after them, outside
    the module, so that each run starts together.

A ``GroupBarrier`` at the start of the module doesn't help, and the check
still raises: Ben has left the module, so the barrier lets Ann through,
and when Ben reaches it, he waits there for Ann while she waits in the
round for him, until ``late_after`` or ``max_wait_time`` moves someone
on. With ``late_after`` on that barrier, it fails Ann, who was on time,
and lets Ben go. Either fix works:

.. code-block:: python

    # Keep the results page inside the module, as above.
    while_loop("runs", play_again, Module("game", rounds, results_page), 2)

    # Or wait for the whole pair after the page, outside the module.
    next_run = GroupBarrier(id_="next_run", group_type="team")
    while_loop("runs", play_again,
               join(Module("game", rounds), results_page, next_run), 2)

With the barrier, Ann waits at ``next_run`` while Ben reads, and it
releases both together when he arrives. See :ref:`group barriers in loops
<rounds-group-barriers-in-loops>` for what the check can't see.

Checked by ``test_case_a_slow_reader_between_runs_of_a_looped_module`` in
``tests/isolated/test_trial_cue_groups.py`` for the page inside the module,
by ``test_a_barrier_after_the_pages_between_runs_waits_for_the_slow_member``
for the barrier after the page, and by
``test_a_page_between_runs_leaves_the_run_start_waiting_until_late_after``
for the barrier at the start of the module. The load-time error is checked
by ``test_timeline_rejects_pages_between_runs_of_a_looped_module`` in
``tests/isolated/test_sync.py``.

An odd player out with a regrouper
----------------------------------

A cohort of three is split into new pairs every round:

.. code-block:: python

    SimpleGrouper("cohort", initial_group_size=3)
    for_loop(..., logic=join(
        Regrouper("pair", within="cohort", roles=["proposer", "responder"],
                  left_over="sit_out", deadline=30),
        switch(...),   # the round's trial, or a sit-out page
    ))

1. All three reach the regrouper. It pairs two of them as proposer and
   responder. The third sits out: they move on at once without a pair, so
   the ``switch`` shows them the sit-out page (see :ref:`rounds-sitting-out`).
   Their :meth:`~psynet.sync.Regrouper.role` is ``None`` and
   :meth:`~psynet.sync.Regrouper.sat_out` is ``True``.
2. The sitter is back at the regrouper first and waits there for the pair.
   If the pair is still playing one ``deadline`` after the sitter arrived,
   the sitter waits at most one more ``deadline``, then sits out again.
3. When the pair is back, the regrouper pairs the sitter, who has played
   the fewest rounds, with one of the two. The other sits this round out.

Checked by ``test_case_an_odd_player_out_sits_out_then_plays_the_next_round``
in ``tests/isolated/test_regrouper.py``, and the deadline in step 2 by
``test_regrouper_left_over_waits_for_cohort_still_in_the_round``.

A barrier's maximum wait runs out
---------------------------------

The pair has no top-ups, and ``submitted`` has no ``late_after``, so its
``max_wait_time`` (20 s by default) applies. Ann submits; Ben has closed his
tab and never arrives. 20 s after Ann arrived, her wait runs out, and the
barrier's ``max_wait_action`` and the grouper's ``below_quorum`` decide:

.. list-table::
   :header-rows: 1

   * - ``max_wait_action``
     - ``below_quorum``
     - Ann, who waited
     - Ben, who didn't arrive
   * - ``"fail"`` (default)
     - ``"fail"`` (default)
     - failed
     - failed when the pair dissolves
   * - ``"fail"``
     - ``"continue_without_group"``
     - failed
     - carries on alone
   * - ``"leave_group"``
     - ``"fail"``
     - carries on alone
     - failed
   * - ``"leave_group"``
     - ``"continue_without_group"``
     - carries on alone
     - carries on alone

Ann's release doesn't count as the pair passing the barrier, so
``on_release`` doesn't run. Her trial
records ``"waited_too_long"`` when she carries on (with the notice "Your
partner didn't arrive in time. Please continue."), or
``"left_experiment"`` when she is failed. Ben's trial records
``"group_dissolved"`` in every row. So with the defaults both are failed,
including Ann, who was on time. To move on without the absent member instead,
give the barrier ``late_after`` (see :ref:`sync-dropout-settings`).

Checked by ``test_case_max_wait_time_runs_out`` in
``tests/isolated/test_trial_cue_groups.py``, for all four rows.

A group dissolves while a member is still on a round page
---------------------------------------------------------

A group of three without top-ups, whose grouper sets
``below_quorum="continue_without_group"``. Ann waits at ``submitted``, Ben
is still on the estimate page, and Cat returns the study. The group falls
below its quorum of three and is dissolved:

- Ann is released, and ``on_dissolve`` runs for her.
- Ben gets neither callback, and his trial records ``"group_dissolved"``.
  When he submits his estimate, ``submitted`` lets him straight through,
  and his next page says "Too few members of your group remained. Please
  continue." (in a pair: "Your partner is no longer in your group. Please
  continue.").

Ben's trial runs to its end, so he still sees the revise page. To skip the
rest of the round once he has left, wrap its steps in ``join(...,
stop_if=...)`` (see :ref:`sync-leaving-a-group`).

Checked by ``test_case_a_group_dissolves_under_a_member_on_a_round_page``
in ``tests/isolated/test_trial_cue_groups.py``.
