Removed `psynet.data.disable_foreign_key_constraints`, which dropped every foreign-key constraint and never restored them. `ingest_to_model` and `ingest_zip` still drop them before importing.
