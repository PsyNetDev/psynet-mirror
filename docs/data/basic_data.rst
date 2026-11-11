Basic data
==========

Basic data is a summary of the experiment's data that you define yourself,
by implementing ``get_basic_data`` on the experiment class with SQLAlchemy
queries. It appears in exports, in the dashboard's **Basic data** tab and at
the ``/basic_data`` endpoint.

As a dictionary
---------------

Return a dictionary of data, and it is saved as a JSON file:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        return {
            "trials": [
                {
                    "id": trial.id,
                    "question": trial.definition.get("question"),
                    "answer": trial.answer,
                }
                for trial in Trial.query.all()
            ]
        }

As data frames
--------------

In exports, a dictionary of data frames also works, and each is saved as a
CSV file. The dashboard tab, the ``/basic_data`` endpoint and backups need
JSON data, so check ``context`` and return data frames only when it is
``"export"``. The ``static`` demo does this:

.. literalinclude:: ../../demos/experiments/static/experiment.py
   :pyobject: Exp.get_basic_data
   :dedent: 4

PsyNet writes participants' answers to the CSV files unchanged. A
spreadsheet such as Excel may run text that starts with ``=``, ``+``,
``-`` or ``@`` as a formula, so open untrusted exports in a tool that
doesn't, such as pandas or R, or import them as text.

PsyNet doesn't anonymize basic data. If a public release must omit
identifiers, leave them out in ``get_basic_data``.

An unfinished trial, abandoned or still running when the data are read,
can have an ``answer``: the answer given so far, before ``format_answer``
has run. Filter trials on ``complete`` as well as ``failed``, for example
``Trial.query.filter_by(complete=True, failed=False)``, or export
``complete`` as a column when a table keeps a row for every trial, such as
the group tables below.

Over HTTP
---------

A running experiment serves basic data at ``/basic_data``, so you can fetch it
without exporting. The endpoint requires the dashboard credentials as query
parameters, ``dashboard_user`` and ``dashboard_password``. The
``basic_data_url`` property builds the full URL:

.. code:: python

    from psynet.experiment import Experiment

    url = Experiment.basic_data_url
    # https://your-experiment-url.com/basic_data?dashboard_user=...&dashboard_password=...

.. code:: bash

    curl "https://your-experiment-url.com/basic_data?dashboard_user=USER&dashboard_password=PASSWORD"

All query parameters, including the credentials, are passed to
``get_basic_data`` as keyword arguments, so one method can serve several
views:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        sheet = kwargs.get("sheet", "participant")
        if sheet == "participant":
            return [...]
        elif sheet == "trial":
            return [...]

The endpoint returns JSON, which Python reads with ``requests.get(url).json()``
and R with ``jsonlite::fromJSON(url)``. Because the credentials are part of the
URL, keep sensitive information out of basic data.

.. _basic_data_groups:

Group experiments
-----------------

Trials of a trial maker with ``sync_group_type``, and cued trials whose
class sets ``sync_group_type``, record the group the participant was in when
the trial was created, in ``trial.sync_group_id``, and their role in it, if
a :class:`~psynet.sync.Regrouper` gave one, in ``trial.sync_group_role``.
``trial.sync_group_round`` says which of the group's rounds the trial belongs
to, counted from 0 and shared by a member who joined the group late; a group
re-formed every round, as by a :class:`~psynet.sync.Regrouper`, plays only
round 0. The group's trials with the same
``sync_group_id`` and ``sync_group_round`` are one round. All three stay after
the group ends. Cued trials of one group and round also share a
:class:`~psynet.sync.SyncGroupRound` (``trial.group_round``), which can hold
the group's results in ``var`` and records in ``closed_at`` when a group
barrier released the round and in ``dissolved_at`` when the group dissolved during it
(see :ref:`dissolved rounds <sync-dissolved-round>`);
the ``public_goods`` demo builds a table per player and round and
one per team and round from them (see :ref:`rounds-one-trial-per-player`). The
``crowd_estimate`` demo does the same for a fixed group that plays one round
per question; a player who answered on their own has a row with an empty
``crowd_id``. Its ``outcome`` column, from ``trial.sync_group_outcome``, says
how the round ended for each player: ``"stayed"`` if they were in the group
when the median was shared, or why they left before that;
``estimate_timed_out`` says whether their estimate's time limit ran out,
which the trial stores right after the estimate page from
``participant.last_response`` (``trial.time_limit_reached`` follows the
trial's latest timed page, here the revised estimate), and ``in_median``
whether it counted.

Groups that stay together save their rounds the same way. The
``public_goods`` demo saves the group's ``contributions`` (``None`` for a
player who ran out of time), ``pot``, ``multiplied_pot``, ``share`` and the
number of players who left since the previous round was scored, from
``on_release``'s ``left``, once per round on the round record, and
each player's ``contribution`` and ``payoff`` on their trial:

.. literalinclude:: ../../demos/experiments/public_goods/experiment.py
   :pyobject: ContributionTrial.score_round

The trial pays its round's payoff as a bonus through ``score_answer`` and
``compute_performance_reward``, so each participant's bonus is the sum of
their trials' ``performance_reward``, and the export and the payments agree.
Its ``player_round`` table also gives each trial's ``sync_group_outcome``,
which says whether the player stayed to the end of the round or why they
left it (see :ref:`round outcomes <sync-round-outcome>`), and ``timed_out``
from the trial's
:attr:`~psynet.trial.main.Trial.time_limit_reached` rather than inferred
from a missing answer. Its ``team_round`` table reads the round record of each team
and round, including its ``dissolved_at``, set when
the group dissolved during the round, which cancels it. Basic data must be
JSON-serializable, so that datetime is exported as an ISO timestamp with
:func:`~psynet.utils.serialise_datetime`:

.. literalinclude:: ../../demos/experiments/public_goods/experiment.py
   :start-at: "team_round": [
   :end-at: for n in teams
   :dedent: 12
   :append: ],

Group membership, for groups formed by a grouper (see
:doc:`/code/multiplayer/synchronization`), is stored in two tables:

``sync_group``
    One row per group: ``id``, ``group_type``, ``leader_id``, ``active``,
    ``end_time`` (set when the group is closed) and
    ``n_active_participants``. Groups formed by a
    :class:`~psynet.sync.SimpleGrouper` also record ``initial_group_size``,
    ``quorum``, ``max_group_size``, ``below_quorum``, ``accepts_top_ups`` and
    ``top_ups_stopped_at`` (when a group that accepted top-ups stopped
    accepting them).

``participant_link_sync_group``
    One row per member of each group: ``participant_id``, ``sync_group_id``,
    ``active`` and, for groups a :class:`~psynet.sync.Regrouper` formed with
    ``roles``, ``role``. The row stays after the participant leaves the group, for
    example by failing or being removed from it, with ``active`` set to ``False``
    and the reason in ``removal_reason``.
    ``creation_time`` is when the participant joined, ``admitted_at`` when
    the group admitted them (empty if they were never admitted; see
    :ref:`sync-admission-points`), and ``admission_points_passed`` how many
    of the group's admission points they passed once admitted.

In a static trial maker, groups can share nodes and networks. Networks of
within-chain trial makers with ``sync_group_type`` record the group in
``network.sync_group_id``.

``trial.position`` is the zero-based position of a trial among the
participant's own trials from that trial maker, so it differs from
``sync_group_round`` for a member who joined late or played in several groups.

A participant variable (``participant.var``) holds only its latest value. To
keep a result from every round in the export, save it on the trial, for
example in ``trial.score`` or ``trial.var``, and the group's results on the
round its trials share, as in :ref:`basic_data_regrouper`.

A convenient layout for dyads and small groups is one row per participant per
round, with columns for the group, the round, the participant, their partner,
the trial ID (to trace each row back to the database) and both players'
responses. Group-level measures can be computed from this table.
The ``rock_paper_scissors`` demo builds it from its trials. The barrier
that ends each round saves on each player's trial the action they played,
their partner's action and the result (see ``score_round`` under
"Barriers" in :doc:`/code/multiplayer/synchronization`). The action saved
for someone who ran out of time is the random one played for them; it is
not in ``trial.answer``, which stays ``None``, and ``timed_out`` reads
:attr:`~psynet.trial.main.Trial.time_limit_reached`. ``get_basic_data`` reads one row
from every trial, including the trial of a player who left during the
round:

.. literalinclude:: ../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: Exp.get_basic_data

For one pair playing three rounds, in which participant 2 timed out in
round 1, this returns (leaving out the ``outcome``, ``"stayed"`` in every
row, and ``partner_timed_out``):

.. code-block:: text

    pair_id  round  participant_id  trial_id  choice    action    timed_out  partner_id  partner_action  result  points
    1        0      1               1         rock      rock      False      2           paper           lost    -1
    1        0      2               2         paper     paper     False      1           rock            won     1
    1        1      1               3         scissors  scissors  False      2           paper           won     1
    1        1      2               4         None      paper     True       1           scissors        lost    -1
    1        2      1               5         scissors  scissors  False      2           scissors        drew    0
    1        2      2               6         scissors  scissors  False      1           scissors        drew    0

Each round has one row per member who started it, and ``partner_id``
points in both directions. A round that was never scored, for example because a partner
dropped out before choosing, has ``None`` in the result columns, and its
``outcome`` says how the player left the pair: when a partner goes silent,
the player who waited for them leaves as ``"waited_too_long"`` and the
silent partner, if they had started that round, as ``"group_dissolved"``
(a partner who went silent between rounds has no row for the next round). Participants who are regrouped have
one ``sync_group_id`` per group, so their rounds with each partner stay apart.

.. _basic_data_regrouper:

Games with a regrouper
~~~~~~~~~~~~~~~~~~~~~~

In games that re-pair players with a :class:`~psynet.sync.Regrouper`, each
group the regrouper forms is one round of one group. With one cued trial per
player per round (see :ref:`rounds-one-trial-per-player`), each trial records the pair
and the player's role, and the pair's round record holds its results. The
``ultimatum_pairing`` demo reads one table from the trials, one from the
rounds and one per player:

.. literalinclude:: ../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: Exp.get_basic_data

Rounds a player sat out have no trial, so the third table counts them with
:meth:`~psynet.sync.Regrouper.rounds_sat_out`; each visit to the regrouper,
with ``sat_out`` set for a sit-out, is a row of the
``participant_link_barrier`` table.

.. seealso::

   The :doc:`/skills/basic-data` and :doc:`/skills/basic-data-group-experiment` skills.
