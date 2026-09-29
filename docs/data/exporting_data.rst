.. highlight:: shell

Exporting data
==============

From the dashboard
------------------

The dashboard's **Export** tab downloads ``export.zip``, with or without the
assets created during the run. If the experiment has artifact storage, the
server also keeps the most recent dashboard download as the deployment's
latest export; each download replaces the previous one. The default
``artifact_storage`` is a
:class:`~psynet.artifact.LocalArtifactStorage` in ``~/psynet-data/artifacts``
on the machine running the experiment.

From the command line
---------------------

Run ``psynet export`` in the experiment directory, in a virtual environment
with the same dependencies as the deployed experiment:

.. code:: bash

    psynet export local
    psynet export ssh --app my-app-name

The export is written to ``exports/latest/`` in the experiment directory.
Useful options:

- ``--server`` picks the server when more than one is registered.
- ``--path`` writes the export somewhere else, for example
  ``--path ~/Documents/my-experiment-data``.
- ``--assets none`` skips asset files, which makes exports of experiments
  with many recordings faster (see :ref:`export_assets`).

A new export is assembled in a temporary directory and moved into place only
once it is complete and validated. The previous ``exports/latest/`` then
moves to ``exports/history/<timestamp>/``. With ``--path``, the previous
export at that path is replaced, not moved to history. A failed or
interrupted export leaves the previous export intact; if both publishing the
new export and restoring the old one fail, the previous export stays at its
recovery path and the error names both locations. ``exports/`` is
excluded by ``deploy.toml`` and ignored by the experiment's ``.gitignore``.

PsyNet doesn't prune ``exports/history/``. Asset files in each entry are hard
links to the shared cache (see `The local asset cache`_), so only the small
table CSVs are duplicated. Delete old entries yourself when you no longer need
them.

.. _data_export_deployed:

During a study
--------------

Export after the first batch of participants, regularly while data
collection runs, and once more after the last participant has finished.
Once you destroy the app or tear down the server, you can no longer export
with ``psynet export``, so treat any data you haven't exported as lost. If an
export fails, rerun the command.

.. lab-note::

   Deposit the final export in your lab's data repository.

How the export reaches your computer
------------------------------------

The deployed experiment always builds the export from its own database. Your
computer never runs the experiment's code or loads the data into a local
database. PsyNet chooses the cheaper of two transfers and reports which one
it used:

- **Complete archive:** the server builds ``export.zip`` and streams it.
  This is used whenever PsyNet can't copy asset files directly, for example
  with S3 storage.
- **Incremental transfer:** for SSH deployments with ``LocalStorage`` and
  ``--assets collected``, the server streams the tables, identifiers and
  manifests, and your computer fetches only the asset files it doesn't
  already have, with one ``rsync --files-from``. Re-exporting a deployment
  whose recordings haven't changed transfers almost nothing.

If ``rsync`` is missing on either machine, PsyNet prints install commands
(``sudo apt install rsync``, or ``brew install rsync`` on macOS) and falls
back to a complete archive. It also falls back if rsync fails or doesn't
deliver every requested file, so an export is never published incomplete.

``psynet export local`` builds the export directly from your local
deployment's database.

Checks before transfer
^^^^^^^^^^^^^^^^^^^^^^

Before transferring anything, PsyNet asks the deployment to identify itself
and compares it with your experiment directory. If the experiment labels
differ, the export stops, because you are almost certainly in the wrong
folder. If the deployed Git commit differs from your checkout, or either side
has uncommitted changes, PsyNet warns and asks for confirmation; in a
non-interactive shell, pass ``--allow-project-mismatch`` to continue:

.. code:: bash

    psynet export ssh --app my-app-name --allow-project-mismatch

These checks also apply with ``--path``. PsyNet checks the downloaded
``manifest.json`` too, so a deployment replaced during the transfer can't
publish the wrong archive; identity fields missing from the downloaded
manifest count as a mismatch. Deployments running a PsyNet version without the
identity check can't be exported with a newer client: install the deployed
version (see ``constraints.txt``) or export from the dashboard.

The local asset cache
---------------------

Command-line exports keep asset files in a persistent cache under
``~/psynet-data/cache/assets/``. Cached files and their hard-linked copies in
exports are read-only, so editing an export can't change the bytes stored
under a content hash. A writable cache entry is re-hashed before reuse; a
read-only one is trusted. If you edited files in the cache, prune it rather
than relying on the next export to notice:

.. code:: bash

    psynet assets cache info
    psynet assets cache list
    psynet assets cache prune --all

When the cache grows past a soft limit (50 GiB by default), PsyNet warns
after the export but doesn't delete anything; a single large experiment may
legitimately exceed the limit. Change the limit with the
``PSYNET_ASSET_CACHE_SOFT_LIMIT_BYTES`` environment variable.

Automatic backups
-----------------

Automatic backups are currently disabled for every experiment, deployed or
not, and are experimental. Don't rely on them; export with ``psynet export``
instead. To try them, set ``automatic_backups = True`` on the experiment
class. Every minute, the experiment then stores its basic data and a
complete export in its artifact storage.
