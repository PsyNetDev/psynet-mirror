Added ``psynet simulate --audit``, which zips ``data/simulated_data/`` to
``./audit/artifacts/simulated_data.zip`` after the usual simulate export and
marks ``simulation_export`` present. Use ``--no-mark-present`` to write the
zip without updating ``audit.json``.
