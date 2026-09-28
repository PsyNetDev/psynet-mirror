What an export contains
=======================

While an experiment runs, its data lives in a PostgreSQL database on the
server. An export copies that data into a folder (or an ``export.zip``
archive) for offline analysis.

Parts of an export
------------------

The **database tables** are a copy of every table in the experiment's
database, one CSV per table under ``database/``. They are read in one
repeatable-read transaction, so they describe a single moment. The same
tables let PsyNet restore the experiment to that state (see
:doc:`/deploy/reference/deploy_from_archive`).

**Basic data** is a smaller set of files that you define for your analysis
by implementing ``get_basic_data`` (see :doc:`/data/basic_data`). It is
present only if you have implemented that method.

**Assets** are media files such as audio recordings; by default an export
includes only those created during the experiment (see :ref:`export_assets`).

**Server logs** (``logs.jsonl``) are included in exports from an SSH server
when they are available. They may contain confidential information, so
don't share them.

Basic data and assets are built after the table snapshot, from the live
experiment, so they describe the moment the export ran rather than the
same database instant as the tables.

Folder layout
-------------

.. code-block:: text

    export/
    ├── database/
    │   ├── participant.csv
    │   ├── trial.csv
    │   └── …
    ├── participant_identifiers.csv
    ├── lucid_entrant_identifiers.csv   # Lucid experiments only
    ├── manifest.json
    ├── basic_data.json OR basic_data/  # optional
    ├── assets/                         # omitted with --assets none
    │   ├── manifest.csv
    │   └── <semantic export paths>
    └── logs.jsonl                      # SSH exports, when available

``database/`` contains a CSV only for tables with at least one row, so
unused tables such as ``chat_message.csv`` are absent. ``manifest.json``
still lists every table under ``table_row_counts``, with ``0`` for omitted
files. Boolean columns are written as ``True`` / ``False`` rather than
PostgreSQL's ``t`` / ``f``.

``manifest.json`` also records the deployed Git commit
(``git_commit_sha``), whether the working tree had uncommitted changes
(``git_dirty``), the experiment label, and an ``export_format_version``.
Exports don't include the experiment's source code; check out that commit to
recover it.

.. _export_assets:

Which assets are included
-------------------------

By default (``--assets collected``), an export includes only assets created
while the experiment was running, for example participant recordings. It
leaves out stimuli prepared before launch, ``ExternalAsset`` URLs and
on-demand assets, whose metadata still appears in ``database/asset.csv``.
``--assets none`` leaves out asset files entirely. If you need a stimulus
pack for supplementary materials, copy the files from the experiment
directory or from storage.

On the server, asset files are stored under content-addressed paths
(``objects/sha256/<digest>``). In an export they appear under readable paths
built from each asset's ``export_path``, for example grouped by module and
participant. ``assets/manifest.csv`` maps each file to its asset ID, local
key, associated participant, trial or node, extension and SHA-256 hash.

Identifier separation
---------------------

Table CSVs replace recruiter identifiers with pseudonyms, so that the
archive still satisfies the database's constraints and can be loaded with
``psynet load``. The original identifiers are in
``participant_identifiers.csv``, keyed by ``participant_id``: ``worker_id``,
``assignment_id``, ``hit_id``, ``unique_id``, ``client_ip_address`` and
``entry_information``. Lucid experiments also write
``lucid_entrant_identifiers.csv``.

In ``database/participant.csv`` the identifier columns hold participant-ID
pseudonyms and ``entry_information`` is an empty JSON object (``{}``).
Recruiter identifiers in other tables are replaced with the same pseudonyms
when they match a known participant (for example Dallinger's
``notification.assignment_id``), and ``request.params`` is always redacted.

An identifier that matches no exported participant, such as the literal
assignment ``unknown`` that Dallinger records for some errors, is removed. A
nullable column becomes empty; a ``NOT NULL`` column receives a placeholder
``redacted-<table>-<row id>``, because an empty CSV field would load as NULL
and break ``psynet load``. Nullability comes from the live schema, so the
same rule applies to identifier columns in experiment-defined tables.
Recruiter-identifier columns must be unconstrained text or JSON; other
column types make the export fail rather than leak identifiers.

Identifier separation is not anonymization: PsyNet doesn't inspect assets,
free-text answers, logs, serialized variables or basic data. See
:doc:`/data/sharing_data`.
