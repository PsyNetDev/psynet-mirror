Export archives now accept only exact ``database/<table>.csv`` or legacy
``data/<table>.csv`` members. Nested lookalikes, path traversal, duplicate
members (including normalized or case aliases), and mixed zip or extracted
layouts are rejected. Downloaded zips are classified before unpack and streamed
into the destination directory without allowing path traversal. Asset manifest
export paths are validated before any bytes are transferred, so an unsafe path
is rejected even when the transfer itself cannot run. ``psynet export``
publishes only ``database/`` layouts; legacy ``data/`` zips remain valid for
``psynet load`` and ``--archive``.
