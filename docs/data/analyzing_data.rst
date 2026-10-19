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

In group experiments, join trials to their groups through
``participant_link_sync_group`` (see :ref:`basic_data_groups`). This example
pairs each trial with the trials of the other group members in the same
round:

.. code:: python

    groups = load_export_table("export.zip", "sync_group")
    links = load_export_table("export.zip", "participant_link_sync_group")
    trials = load_export_table("export.zip", "trial")

    groups = groups.rename(columns={"id": "sync_group_id"})
    members = links.merge(groups[["sync_group_id", "group_type"]], on="sync_group_id")
    members = members[members["group_type"] == "rock_paper_scissors"]

    trials = trials[(trials["trial_maker_id"] == "rock_paper_scissors") & ~trials["failed"]]
    trials = trials.merge(members[["participant_id", "sync_group_id"]], on="participant_id")
    partners = trials[["sync_group_id", "position", "participant_id", "answer"]].rename(
        columns={"participant_id": "partner_id", "answer": "partner_answer"}
    )
    player_rounds = trials.merge(partners, on=["sync_group_id", "position"])
    player_rounds = player_rounds[
        player_rounds["participant_id"] != player_rounds["partner_id"]
    ]

Loading an export into a local database
---------------------------------------

``psynet load export.zip`` replaces the local database with the archive, so
you can query it directly. Stop
``psynet debug`` and any other client using the same database role first:
PsyNet refuses to drop tables while another client using that role is
connected.
