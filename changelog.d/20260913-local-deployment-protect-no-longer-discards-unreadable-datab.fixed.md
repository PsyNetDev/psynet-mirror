Fixed local deployment recovery so ``debug``/``prepare`` never discard an
unreadable database, skip redundant recovery after a clean participant-finish
snapshot, and re-stamp deployment identity immediately after archive ingest.
