Late, slow and leaving players: case studies
============================================

Group games rarely run as planned: a player closes their tab, another
reads the results slowly, a third is left over when pairs are formed. This
page follows such cases through concrete designs, and says what each
player sees, whom they wait for and when they move on. The rules behind
them are in :ref:`whom a group barrier waits for
<rounds-group-barrier-rule>` and :ref:`sync-dropout-settings`; this page only
applies them. Each case ends with the test that checks it, so if PsyNet's
behaviour changes, the test fails until the page is updated.

All the cases share one design, a fixed group answering a loop of
questions, unless the case says otherwise. Each question is one round: a
cued trial whose ``show_trial`` includes a :class:`~psynet.sync.GroupBarrier`,
so the barrier waits for every member of the group and its release closes
the round (see :ref:`rounds-cued-trials`). With ``accumulate_answers``,
``trial.answer`` keeps each page's answer under its label, so the answer of
the estimate page, labelled ``"estimate"``, stays in
``trial.answer["estimate"]`` after the revise page:

.. code-block:: python

    class EstimateTrial(Trial):
        sync_group_type = "team"
        accumulate_answers = True

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
  released without ``on_release`` running, her trial records
  ``"group_dissolved"``, so ``show_feedback`` can score her estimate from
  ``trial.answer["estimate"]`` (see
  :ref:`round outcomes <sync-round-outcome>`), and her next page says "Your
  partner is no longer in your group. Please continue." She plays the rest
  of the timeline without a group (see :ref:`sync-leaving-a-group`).

With the default ``below_quorum="fail"``, a dissolved group fails Ann
instead, and a group that still takes newcomers is not dissolved but waits
at the barrier for one (see :ref:`groups_below_min_size`).

Checked by ``test_case_a_member_leaves_mid_round`` in
``tests/isolated/test_trial_cue_groups.py``, for both group sizes.

A slow reader between runs
--------------------------

The pair plays the whole game several times, with cues that don't pass
``round=`` (a module that runs again can't), and a results page after each
run, inside the game's module or outside it. Ann reads the results
quickly and waits at run 2's first barrier; it waits for Ben, however long
he reads, and releases both together. Size that barrier's
``max_wait_time`` or ``late_after`` for slow readers.

Checked by ``test_case_a_slow_reader_between_runs_of_a_looped_module`` in
``tests/isolated/test_trial_cue_groups.py`` for the page inside the module,
and by ``test_a_barrier_after_the_pages_between_runs_waits_for_the_slow_member``
for a page outside it.

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

- Ann is released, and ``on_release`` doesn't run. Her trial records
  ``"group_dissolved"``.
- Ben's trial records ``"group_dissolved"`` too. When he submits his
  estimate, ``submitted`` lets him straight through, and his next page says
  "Too few members of your group remained. Please continue." (in a pair: "Your partner is no longer in your group. Please
  continue.").

Both estimates stay on their trials, in ``trial.answer["estimate"]``, so an
export or ``on_finalized`` can score the round from ``node.all_trials`` (see
:ref:`round outcomes <sync-round-outcome>`). Ann's ``show_feedback`` may run
before Ben has submitted his.

Ben's trial runs to its end, so he still sees the revise page. To skip the
rest of the round once he has left, wrap its steps in ``join(...,
stop_if=...)`` (see :ref:`sync-leaving-a-group`).

Checked by ``test_case_a_group_dissolves_under_a_member_on_a_round_page``
in ``tests/isolated/test_trial_cue_groups.py``, and the stored estimates by
``test_a_dissolved_round_keeps_its_answers_and_outcomes``.

Members end up at different barriers
------------------------------------

The pair still takes newcomers during the game, and each question starts
with a ``GroupBarrier(id_="ready", group_type="team")`` before the cue.
Ann and Ben are in a round when Cat joins. Cat goes through the game from
its start, so she waits at ``ready`` while Ann waits for her at
``submitted``. Ben then submits, or leaves the pair, or is removed as late:

- Each barrier waits for the members at the other, so nobody passes until
  ``late_after`` or ``max_wait_time`` moves someone on.
- Within a second or so, the background barrier check records one error
  for the pair that names both barriers and who waits at each, logs it and
  lists it under the dashboard's Errors tab. A bot test fails with
  :class:`~psynet.sync.GroupDivergenceError` and that message.

To avoid this, stop top-ups before the game with ``stop_top_ups=True``
(see :ref:`sync-lobby-top-ups`), and see :ref:`members at different
barriers <rounds-group-barriers-in-loops>`.

Checked by ``test_a_sweep_reports_members_waiting_for_each_other_at_different_barriers``
in ``tests/isolated/test_trial_cue_groups.py``, for each way Ben goes.
