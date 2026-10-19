Removed ``psycopg2-binary``, ``redis``, and ``yaspin`` from PsyNet's core
bootstrap dependencies (now ``click``, plus ``tomli`` only on Python < 3.11 for
parsing ``pyproject.toml``). ``psynet services`` probes Redis with a stdlib RESP
``PING`` and PostgreSQL via ``psycopg2`` when available, otherwise ``pg_isready``
or a PostgreSQL protocol fingerprint that does not authenticate. Version-check
spinners still use ``yaspin`` via a lazy import under ``psynet[experiment]``.
