Changed database export to one PostgreSQL repeatable-read snapshot with
identifier separation. All table CSVs and identifier sidecars are read through
the same database transaction.

``export.zip`` contains physical table CSVs under ``database/`` with
pseudonymous participant identifiers. Original recruiter identifiers are written
to ``participant_identifiers.csv`` (and ``lucid_entrant_identifiers.csv`` for
Lucid). The ``--anonymize`` flag and class-based ORM CSV export have been
removed. Analysis helpers ``load_export_table``, ``unpack_json_column``, and
``merge_participant_identifiers`` are provided under ``psynet.export``. The
``extra_var`` registry and implicit VarStore flattening have been removed;
``claim_var`` no longer accepts ``extra_vars``. Runtime properties created with
``claim_var`` are preserved. VarStore values remain in the physical ``vars``
column and can be unpacked with ``unpack_json_column``. Selected assets are
always exported when requested.
