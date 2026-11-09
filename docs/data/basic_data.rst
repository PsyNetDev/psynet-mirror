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
:class:`~psynet.trial.main.SyncGroupNode`, which can hold the group's results;
the ``lowest_unique_number`` demo builds a table per player and round and
one per room from them (see :ref:`rounds-cued-trials`).

Group membership, for groups formed by a grouper (see
:doc:`/code/multiplayer/synchronization`), is stored in two tables:

``sync_group``
    One row per group: ``id``, ``group_type``, ``leader_id``, ``active``,
    ``end_time`` (set when the group is closed) and
    ``n_active_participants``. Groups formed by a
    :class:`~psynet.sync.SimpleGrouper` also record ``initial_group_size``,
    ``min_group_size``, ``max_group_size`` and ``accepts_top_ups``.

``participant_link_sync_group``
    One row per member of each group: ``participant_id``, ``sync_group_id``,
    ``active`` and, for groups a :class:`~psynet.sync.Regrouper` formed with
    ``roles``, ``role``. The row stays after the participant leaves the group, for
    example by failing or being removed from it, with ``active`` set to ``False``
    and the reason in ``removal_reason``.
    ``creation_time`` is when the participant joined.

In a static trial maker, groups can share nodes and networks: in the
``rock_paper_scissors`` demo every pair plays on the same node. Networks of
within-chain trial makers with ``sync_group_type`` record the group in
``network.sync_group_id``.

``trial.position`` is the zero-based position of a trial among the
participant's own trials from that trial maker, so it differs from
``sync_group_round`` for a member who joined late or played in several groups.

A participant variable (``participant.var``) holds only its latest value. To
keep a result from every round in the export, save it on the trial, for
example in ``trial.score`` or ``trial.var``, and the group's results on the
node its trials share, as in :ref:`basic_data_regrouper`.

A convenient layout for dyads and small groups is one row per participant per
round, with columns for the group, the round, the participant, their partner,
the trial ID (to trace each row back to the database) and both players'
responses. Group-level measures can be computed from this table.
The ``rock_paper_scissors`` demo builds it from its trials. The barrier that
ends each round saves each player's action, their partner's and the score on
their trial, including the random action played for someone who ran out of
time, because that action is in no answer:

.. literalinclude:: ../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.score_trial

``get_basic_data`` then reads one row from each scored trial:

.. literalinclude:: ../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: Exp.get_basic_data

For one pair playing three rounds, in which participant 2 timed out in
round 1, this returns:

.. code-block:: text

    group_id  round  participant_id  trial_id  action    timed_out  partner_id  partner_action  partner_timed_out  score
    1         0      1               1         rock      False      2           paper           False              -1
    1         0      2               2         paper     False      1           rock            False              1
    1         1      1               3         scissors  False      2           paper           True               1
    1         1      2               4         paper     True       1           scissors        False              -1
    1         2      1               5         scissors  False      2           scissors        False              0
    1         2      2               6         scissors  False      1           scissors        False              0

Each scored round has one row per member, and ``partner_id`` points in both
directions. A round that was never scored, for example because a partner
dropped out before choosing, has no rows. Participants who are regrouped have
one ``sync_group_id`` per group, so their rounds with each partner stay apart.

.. _basic_data_regrouper:

Games with a regrouper
~~~~~~~~~~~~~~~~~~~~~~

In games that re-pair players with a :class:`~psynet.sync.Regrouper`, each
group the regrouper forms is one round of one group. With one cued trial per
player per round (see :ref:`rounds-cued-trials`), each trial records the pair
and the player's role, and the pair's node holds its results. The
``ultimatum_pairing`` demo reads one table from the trials, one from the
nodes and one per player:

.. literalinclude:: ../../demos/experiments/ultimatum_pairing/experiment.py
   :pyobject: Exp.get_basic_data

Rounds a player sat out have no trial, so the third table counts them with
:meth:`~psynet.sync.Regrouper.rounds_sat_out`; each visit to the regrouper,
with ``sat_out`` set for a sit-out, is a row of the
``participant_link_barrier`` table.

.. seealso::

   The :doc:`/skills/basic-data` and :doc:`/skills/basic-data-group-experiment` skills.
