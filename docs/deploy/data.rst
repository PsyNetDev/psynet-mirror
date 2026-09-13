.. _data:
.. highlight:: shell

====
Data
====

When an experiment is live, data is stored in a PostgreSQL database.
The data can be inspected in real time via the experiment dashboard,
or it can be exported for offline analysis.

Viewing data in the dashboard
=============================

The 'database' section of the dashboard provides a simple viewer of database objects.
Each object type is displayed in a separate table.
It is possible to perform certain actions on selected objects, such as marking them as 'failed'.

Exporting data from the dashboard
=================================

The 'export' section of the dashboard downloads ``export.zip``.
You choose whether to include assets (none, or collected during the run).
Dashboard downloads also store the archive as the deployment's latest export
artifact, so the most recent complete export stays available on the server.
Only one ``export.zip`` is kept per deployment; earlier versions are replaced.

Exports use *identifier separation*: table CSVs under ``database/`` contain
pseudonymous participant identifiers so the archive remains loadable, while
original recruiter identifiers are written beside them in
``participant_identifiers.csv``. This is not anonymization of assets,
free text, logs, or experiment-defined basic data. Recruiter-identifier
columns must be unconstrained text or JSON; unsupported custom types fail
the export with an error rather than leaking identifiers or writing an
archive that cannot be reloaded.

Exporting data from the command line
====================================

It is also possible to export data from the command line using the 'psynet export' command.
This should normally be run in the experiment directory for the experiment you are running,
using a virtual environment with the same dependencies as the deployed experiment.

.. code:: bash

    psynet export local
    psynet export ssh --app my-app-name
    psynet export heroku --app my-app-name

The latest export is saved to ``exports/latest/`` in the experiment directory.
A new export is assembled in a temporary staging directory and only moved into
place once it is complete and validated, at which point the previous
``latest/`` directory is moved to ``exports/history/<timestamp>/``. A failed or
interrupted export therefore always leaves your previous export intact. If
both publication and restoration fail, the previous tree is kept at its
recovery path and the error names both locations. The
``exports/`` path is listed in ``deploy.toml`` so it is not uploaded on deploy,
and the experiment ``.gitignore`` template ignores it.

PsyNet does not currently prune ``exports/history/``, so it grows by one entry
per export. This is cheaper than it looks: exported asset files are hard links
to the shared cache described in :ref:`export_assets`, so repeated snapshots of
unchanged recordings share their bytes rather than duplicating them. What each
entry does duplicate is the table CSVs, which are small. Delete old
subdirectories of ``exports/history/`` yourself when you no longer want them.

A typical export directory looks like this:

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
    ├── assets/                         # omitted when --assets none
    │   ├── manifest.csv
    │   └── <semantic export paths>
    └── logs.jsonl                      # SSH exports when available

``database/`` contains a CSV only for tables that have at least one row, so a
typical experiment does not include unused tables such as ``chat_message.csv``.
``manifest.json`` still lists every table under ``table_row_counts``, with a
count of ``0`` for omitted files. Boolean columns are written as ``True`` /
``False`` (not PostgreSQL's raw ``t`` / ``f``) so analysis tools can treat them
as logical values; ``psynet load`` still accepts that spelling.

If you want to choose your own export location, use the ``--path`` argument:

.. code:: bash

    psynet export ssh --app my-app-name --path ~/Documents/my-experiment-data

By default the export command downloads **collected** assets: managed files
deposited during this deployment (for example participant recordings).
This can slow down data export if you have many files. You can disable this
behavior using the ``--assets`` argument:

.. code:: bash

    psynet export ssh --app my-app-name --assets none

Treat exported media as potentially identifying. Cached stimuli, external
URLs, and on-demand assets are not part of the archive; copy stimuli from
the experiment directory or storage if you need them for supplementary
materials.

``manifest.json`` records the git commit SHA that was deployed
(``git_commit_sha``), whether the working tree was dirty (``git_dirty``), the
experiment label, and an ``export_format_version``. Exports do not include a
source-code zip; check out that commit to recover the experiment code.

How the export gets to your computer
------------------------------------

Exports are always built by the deployed experiment itself, against its own
database. Your computer never runs the experiment's code and never ingests the
data into a local database. PsyNet then picks the cheapest way to transfer the
result, and tells you which one it used:

* **Complete archive.** The server builds ``export.zip`` and streams it to your
  computer. This is used for Heroku and for any
  deployment whose asset bytes PsyNet cannot copy directly (for example
  S3-backed storage).
* **Incremental transfer.** For SSH deployments whose assets live in
  ``LocalStorage``, the server streams a small core snapshot (tables,
  identifiers, ``manifest.json``, and an asset manifest), and your computer
  fetches only the asset objects it does not already have with one
  ``rsync --files-from``. Re-exporting a deployment whose recordings have not
  changed therefore transfers almost nothing.

``psynet export local`` builds the export directly from your local
deployment's database, without going through its own dashboard.

Before anything is transferred, PsyNet asks the deployment to identify itself
and compares it with your experiment directory. If the experiment labels do not
match, the export stops: you are almost certainly in the wrong folder. If the
deployed Git commit differs from your checkout, or either side has uncommitted
changes, PsyNet warns and asks for confirmation. In a non-interactive shell you
must pass ``--allow-project-mismatch`` to continue. These checks apply even when
you supply ``--path``. PsyNet checks the downloaded ``manifest.json`` too,
including after a successful preflight, so a deployment replaced during the
transfer cannot publish the wrong archive. Missing downloaded identity fields
are treated as a mismatch when preflight supplied them. A deployment whose
PsyNet predates the preflight endpoint cannot be exported with this client.
Install that earlier version (see ``constraints.txt``) and retry, or export
from the dashboard.

.. code:: bash

    psynet export ssh --app my-app-name --allow-project-mismatch


Identifier separation
=====================

Table CSVs under ``database/`` replace direct recruiter identifiers with pseudonyms so that database
constraints remain satisfied and the archive can be loaded with ``psynet load``.
Original identifiers are available in ``participant_identifiers.csv``, keyed by
``participant_id``. That sidecar includes ``worker_id``, ``assignment_id``,
``hit_id``, ``unique_id``, ``client_ip_address``, and ``entry_information``
(serialized as in the database). In ``database/participant.csv`` the identifier
columns are replaced with participant-id pseudonyms and ``entry_information``
is an empty JSON object (``{}``), so the NOT NULL constraint still holds on
``psynet load``. Lucid experiments also write
``lucid_entrant_identifiers.csv``. Recruiter identifier columns on other copied
tables are remapped to the same participant pseudonyms when they match a known
participant (for example Dallinger ``notification.assignment_id``).
``request.params`` is always redacted.

An identifier that matches no exported participant cannot be pseudonymized.
Dallinger, for instance, records an experiment error against the literal
assignment ``unknown``. Such a value is removed, but *how* it is removed depends
on the column: a nullable column becomes empty, while a ``NOT NULL`` column
receives a placeholder of the form ``redacted-<table>-<row id>``. The
distinction matters because ``COPY`` reads an empty CSV field as NULL, so
blanking a ``NOT NULL`` column would produce an archive that
``psynet load`` cannot read. Nullability is taken from the live schema, so the
same rule applies automatically to identifier columns on experiment-defined
tables.

.. _export_asset_tokens:

Sharing an export
=================

To share a dataset publicly, delete ``participant_identifiers.csv`` (and
``lucid_entrant_identifiers.csv`` if present). Then look through the rest of
the archive for anything else you would not want public. PsyNet does not
inspect assets, free-text answers, logs, serialized variables, or
experiment-defined basic data.

``database/asset.csv`` includes ``access_token`` and ``url``. Those are the
same browser capabilities the running experiment uses
(``/asset/<access_token>``). Once the deployment has finished they are
harmless. If you share an export while the experiment is still live, delete
those columns so the tokens cannot be used against the running app.

.. _export_assets:

Assets
======

By default (``--assets collected``), only managed assets deposited during the
course of the experiment are exported — for example audio recordings.
Pre-existing assets such as ``CachedAsset`` stimuli and ``ExternalAsset`` URLs
are omitted, and on-demand assets are not generated. Use ``--assets none`` to
skip asset files entirely.

If you need a stimulus pack for supplementary materials, copy those files from
the experiment directory or from storage rather than from the data export.

Managed asset bytes are stored on the server under content-addressed paths of the
form ``objects/sha256/<digest>``. Exported archives instead materialize those
bytes under semantic paths from each asset's ``export_path`` (for example
module and participant folders). The ``assets/manifest.csv`` file maps semantic
metadata (asset id, local key, associations, extension, sha256, and so on) onto
those files. External and on-demand assets are omitted from the export tree;
their metadata remains in ``database/asset.csv``, including ``access_token``
and ``url`` (see :ref:`export_asset_tokens`).

Live browser access for local and on-demand assets uses a permanent access
token at ``/asset/<access_token>``. S3-backed managed assets use a direct public
object URL. Content hashes identify bytes for storage and export; they are not
used as browser capabilities. The old ``obfuscate`` and ``personal`` asset flags
have been removed.

Command-line exports reuse a persistent local cache under
``~/psynet-data/cache/assets/``. Cached files and their hard-linked export
copies are read-only so editing an export cannot silently change the bytes
stored under a content hash. A **writable** cache entry is re-hashed before
reuse; a **read-only** hit is trusted without hashing again. If you edited
files under ``~/psynet-data/cache/assets`` (or suspect they were altered),
prune the cache rather than relying on the next export to notice. Inspect or
clear the cache with:

.. code:: bash

    psynet assets cache info
    psynet assets cache list
    psynet assets cache prune --all

SSH command-line exports copy missing managed-asset objects from the server
with one ``rsync --files-from`` into that cache, instead of one download per
file. Repeat exports on the same machine transfer only new objects. If
``rsync`` is missing locally or on the SSH host, PsyNet prints install
commands (``sudo apt install rsync``, or ``brew install rsync`` on macOS) and
falls back to a complete server-built archive, so the export still succeeds.
The same fallback applies if rsync fails, or exits successfully without
supplying every requested object: because the server can always read its own
files, PsyNet retries with a complete archive rather than publishing an
incomplete export. Warm-cache repeat exports do not need rsync at all.

Incremental transfer is offered for ``--assets collected`` on deployments using
``LocalStorage``. S3-backed assets always use the complete archive.

If the cache grows past a soft limit (50 GiB by default), PsyNet warns after
export but does **not** fail or delete objects. A single large experiment may
legitimately exceed the limit. Override the threshold with the environment
variable ``PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES``.

Export data types
=================

Several types of data can be exported during the export process. They each have different functions.

The **database tables** are a portable copy of the physical database at a given time
(``database/*.csv`` plus identifier sidecars and ``manifest.json``).
Those files are read in one repeatable-read database transaction.
They are useful for restoring experiments from a specific state and for analysis that reads
table CSVs directly. ``psynet debug`` / ``deploy --archive`` accepts ``export.zip``,
a ``database/`` directory, or an extracted export directory containing ``database/``.

The **basic data files** are a minimal set of data files that provide the essential information for downstream analysis.
They are only present if the experimenter has implemented the ``get_basic_data`` method in their experiment class.

The **assets** correspond to heavy files (e.g. audio, video) that are associated with the experiment.
Not all experiments use assets. Choose ``--assets none`` to omit the assets folder.
Basic data and assets are built after that table snapshot, from the live experiment,
so they reflect the moment the export ran rather than the same database instant as the CSVs.

The **server logs** can also be exported when exporting from an SSH server.
These come in the form of a ``logs.jsonl`` file. Don't share these publicly
as they may contain confidential information.

A dashboard or CLI export combines these pieces into one ``export.zip`` (or an
extracted export directory).

Analysing database tables
=========================

PsyNet provides helpers for reading the canonical tables without reconstructing an
older class-based CSV layout:

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

More about basic data
=====================

The basic data route is really intended for confident experimenters.
If you are not comfortable with SQLAlchemy, you may want to stick to the default export methods.

You define the basic data representation for your experiment by implementing the ``get_basic_data`` method
in your experiment class. You have a lot of flexibility in how you implement this method.

JSON method
-----------

One possibility is to return an arbitrary dictionary of data.
In this case, the data will be saved as a JSON file.
For example:

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

DataFrame method
----------------

Alternatively, you can return a dictionary of dataframes.
In this case, the data will be saved as a set of CSV files.
For example:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        import pandas as pd

        trials = [
            {
                "id": trial.id,
                "participant_id": trial.participant_id,
                "animal": trial.definition.get("animal"),
                "block": trial.block,
                "answer": trial.answer,
                "score": trial.score,
            }
            for trial in StaticTrial.query.all()
        ]
        participants = [
            {
                "id": participant.id,
                "status": participant.status,
                "bonus": participant.bonus,
            }
            for participant in Participant.query.all()
        ]
        return {
            "trial": pd.DataFrame.from_records(trials),
            "participant": pd.DataFrame.from_records(participants),
        }

PsyNet does not automatically anonymize or otherwise reinterpret experiment-defined
basic data. If you need to omit identifiers from a public release of basic data, do
that explicitly in your ``get_basic_data`` implementation.

Accessing basic data via the dashboard
--------------------------------------

You can preview the basic data in the dashboard by clicking on the 'Basic data' tab.


Accessing basic data via HTTP
------------------------------

Once you have implemented the ``get_basic_data`` method, you can access your basic data via an HTTP endpoint at ``/basic_data``.
This allows you to fetch data directly from a running experiment without needing to export it first.

The endpoint requires dashboard credentials, which can be provided as query parameters:
``dashboard_user`` and ``dashboard_password``.

You can construct the full URL using the ``basic_data_url`` property:

.. code:: python

    from psynet.experiment import Experiment

    url = Experiment.basic_data_url()
    # Returns: https://your-experiment-url.com/basic_data?dashboard_user=...&dashboard_password=...

Alternatively, you can access the endpoint directly by including the credentials in the URL:

.. code:: bash

    curl "https://your-experiment-url.com/basic_data?dashboard_user=USER&dashboard_password=PASSWORD"

Any GET parameters you pass to the endpoint will be forwarded to your ``get_basic_data`` method via the ``**kwargs`` parameter.
This allows you to implement dynamic behavior based on URL parameters.
For example, you could filter data by a specific parameter:

.. code:: python

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        sheet = kwargs.get("sheet", "participant")
        # Return different data based on the 'sheet' parameter
        if sheet == "participant":
            return [...]
        elif sheet == "trial":
            return [...]

The endpoint returns JSON data directly, making it easy to consume from various tools:

- **Python**: Use ``requests.get(url).json()`` or ``urllib.request.urlopen(url).read()``
- **R**: Use ``jsonlite::fromJSON(url)``
- **Web browser**: Simply navigate to the URL to view the JSON data

Note that the endpoint should not expose sensitive information, as the authentication credentials are included in the URL itself.

Automatic backups
=================

PsyNet does have some functionality implemented for making regular data backups.
However, at the time of writing, this is disabled by default and should be considered experimental.
To enable it, you can set the ``automatic_backups`` class attribute to ``True`` in your experiment class.
