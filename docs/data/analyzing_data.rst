Analyzing data
==============

In the dashboard
----------------

The dashboard's **Database** tab shows each type of database object in its
own table. You can act on selected objects there, for example marking them
as failed. The **Basic data** tab previews the experiment's basic data (see
:doc:`/data/basic_data`).

Checking data during collection
-------------------------------

Keep an analysis script (for example ``export.py``) in the experiment
directory and run it on every export. It should:

- check that participants progress through the whole experiment and
  complete the expected number of trials, using assertions so that
  problems stop the script;
- check the time estimates, for example with a histogram of trial
  durations;
- extract the demographic information you need, such as age and gender;
- convert the raw tables into the format you analyze, for example a CSV
  for R or MATLAB;
- plot the main results, so that unexpected effects show up early.

Running it after the first batch of participants lets you stop a broken
experiment early. For quick checks without a full export, read basic data
from the dashboard or the ``/basic_data`` endpoint.

Reading the tables
------------------

``psynet.export`` has helpers for reading the exported tables:

.. code:: python

    from psynet.export import (
        load_export_table,
        merge_participant_identifiers,
        unpack_json_column,
    )

    trials = load_export_table("export.zip", "trial")
    # Or: load_export_table("path/to/database", "trial")
    # Or: load_export_table("path/to/extracted/export", "trial")
    trials = unpack_json_column(trials, "definition", prefix="definition_")
    participants = load_export_table("export.zip", "participant")
    participants = merge_participant_identifiers(
        participants.rename(columns={"id": "participant_id"}),
        "participant_identifiers.csv",
    )

In group experiments, each synchronized trial records its group and round
in ``sync_group_id`` and ``sync_group_round`` (see :ref:`basic_data_groups`).
This example pairs each trial with the trials of the other group members in
the same round:

.. code:: python

    trials = load_export_table("export.zip", "trial")
    trials = trials[trials["sync_group_id"].notna() & ~trials["failed"]]

    round_ = ["sync_group_id", "sync_group_round"]
    partners = trials[round_ + ["participant_id", "answer"]].rename(
        columns={"participant_id": "partner_id", "answer": "partner_answer"}
    )
    player_rounds = trials.merge(partners, on=round_)
    player_rounds = player_rounds[
        player_rounds["participant_id"] != player_rounds["partner_id"]
    ]

A player who timed out has no answer of their own: in the
``rock_paper_scissors`` demo their ``answer`` is ``None``. The move actually played,
including the random one given to a player who timed out, is in the vars of
the round's node (``actions``), as the demo's basic data shows (see
:ref:`basic_data_groups`).

Group details such as ``group_type`` are in the ``sync_group`` table, and
each member's role and removal reason in ``participant_link_sync_group``.
For cued trials, the group's results are in the ``node`` table, whose
``sync_group_id`` and ``sync_group_round`` match its trials'.

Loading an export into a local database
---------------------------------------

``psynet load export.zip`` replaces the local database with the archive, so
you can query it directly. Stop
``psynet debug`` and any other client using the same database role first:
PsyNet refuses to drop tables while another client using that role is
connected.
