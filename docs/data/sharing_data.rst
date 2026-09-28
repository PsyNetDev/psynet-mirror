Sharing data
============

Before sharing a dataset publicly, delete ``participant_identifiers.csv`` and,
if present, ``lucid_entrant_identifiers.csv``. These hold the recruiter
identifiers, IP addresses and entry information that the table CSVs replace
with pseudonyms (see :doc:`/data/what_an_export_contains`).

Then check the rest of the export yourself. PsyNet doesn't inspect assets,
free-text answers, logs, serialized variables or basic data, and recordings
and other media can identify participants. Don't share ``logs.jsonl``.

.. _export_asset_tokens:

Asset access tokens
-------------------

``database/asset.csv`` includes each asset's ``access_token`` and ``url``,
which are the links the running experiment uses to serve the file
(``/asset/<access_token>``). Once the deployment is gone they are harmless.
If you share an export while the experiment is still running, delete those
columns so the links can't be used to fetch files from it.
