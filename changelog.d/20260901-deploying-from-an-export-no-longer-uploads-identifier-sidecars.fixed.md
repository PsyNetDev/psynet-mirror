`psynet deploy`/`debug --archive` now re-packs the archive you supply and sends
only the table CSVs under `database/` to the server. Passing an `export.zip`
previously uploaded the whole archive, including the recruiter identifier
sidecars and any exported asset files, even though only the table CSVs are read.
