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

Trials don't record which group they belong to. Group membership, for
groups formed by a grouper (see :doc:`/code/multiplayer/synchronization`),
is stored in two tables:

``sync_group``
    One row per group: ``id``, ``group_type``, ``leader_id``, ``active``,
    ``end_time`` (set when the group is closed) and
    ``n_active_participants``. Groups formed by a
    :class:`~psynet.sync.SimpleGrouper` also record ``initial_group_size``,
    ``min_group_size``, ``max_group_size`` and ``accepts_top_ups``.

``participant_link_sync_group``
    One row per member of each group: ``participant_id``, ``sync_group_id``
    and ``active``. The row stays after the participant leaves the group, for
    example by failing or being kicked, with ``active`` set to ``False``.
    ``creation_time`` is when the participant joined.

In a static trial maker, groups can share nodes and networks: in the
``rock_paper_scissors`` demo every pair plays on the same node. Networks of
within-chain trial makers with ``sync_group_type`` record the group in
``network.sync_group_id``.

``trial.position`` is the zero-based position of a trial among the
participant's trials from that trial maker. In a trial maker with
``sync_group_type``, the members of a group start each trial together, so
if they joined the group together, their trials with the same ``position``
form one round.

A participant variable (``participant.var``) holds only its latest value. To
keep a result from every round in the export, save it on the trial, for
example in ``trial.score`` or ``trial.var``.

A convenient layout for dyads and small groups is one row per participant per
round, with columns for the group, the round, the participant, their partner,
the trial ID (to trace each row back to the database) and both players'
responses. Group-level measures can be computed from this table.
For the ``rock_paper_scissors`` demo, where each trial's answer is a
dictionary such as ``{"choose_action": "rock"}``:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        from psynet.sync import ParticipantLinkSyncGroup, SyncGroup

        links = (
            ParticipantLinkSyncGroup.query.join(SyncGroup)
            .filter(SyncGroup.group_type == "rock_paper_scissors")
            .all()
        )
        group_ids = {link.participant_id: link.sync_group_id for link in links}
        members = {}
        for link in links:
            members.setdefault(link.sync_group_id, []).append(link.participant_id)

        trials = RockPaperScissorsTrial.query.filter_by(
            failed=False, complete=True
        ).all()
        actions = {
            (trial.participant_id, trial.position): trial.answer["choose_action"]
            for trial in trials
        }

        rows = []
        for trial in sorted(trials, key=lambda t: (t.position, t.participant_id)):
            group_id = group_ids.get(trial.participant_id)
            partners = [
                p for p in members.get(group_id, []) if p != trial.participant_id
            ]
            partner_id = partners[0] if len(partners) == 1 else None
            rows.append(
                {
                    "group_id": group_id,
                    "round": trial.position,
                    "participant_id": trial.participant_id,
                    "partner_id": partner_id,
                    "trial_id": trial.id,
                    "action": actions[(trial.participant_id, trial.position)],
                    "partner_action": actions.get((partner_id, trial.position)),
                }
            )
        return {"player_round": rows}

For one pair playing three rounds, this returns:

.. code-block:: text

    group_id  round  participant_id  partner_id  trial_id  action    partner_action
    1         0      1               2           1         rock      paper
    1         0      2               1           2         paper     rock
    1         1      1               2           3         scissors  paper
    1         1      2               1           4         paper     scissors
    1         2      1               2           5         scissors  scissors
    1         2      2               1           6         scissors  scissors

Each complete round has one row per member, and ``partner_id`` points in
both directions. A missing ``partner_action`` means the partner has no
completed trial for that round, for example because they dropped out.

The example assumes each participant is in one group of this type. If
participants are regrouped, a participant has one ``participant_link_sync_group``
row per group; assign each trial to the group whose link ``creation_time``
precedes the trial's ``creation_time`` and whose ``end_time`` is empty or
follows it.

.. seealso::

   The :doc:`/skills/basic-data` and :doc:`/skills/basic-data-dyadic-experiment` skills.
