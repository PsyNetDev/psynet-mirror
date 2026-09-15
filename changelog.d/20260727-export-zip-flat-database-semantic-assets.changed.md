Replaced dual ``psynet.zip`` / ``database.zip`` downloads with a single
``export.zip`` product.

Table CSVs now live in a flat ``database/`` directory (no nested zip and no
``data/`` prefix). Asset exports use semantic ``export_path`` trees again;
``--assets none`` omits the assets folder. Lucid identifier sidecars are written
only when Lucid rows exist. ``--archive`` and ``load_export_table`` accept
``export.zip``, a ``database/`` directory, or an extracted export directory.
