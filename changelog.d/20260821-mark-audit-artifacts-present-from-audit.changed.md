``psynet simulate --audit`` and ``psynet performance-test local --audit`` now
mark ``simulation_export`` and ``performance_result`` present after writing the
canonical files. Pass ``--no-mark-present`` to write the file without updating
``audit.json``.
