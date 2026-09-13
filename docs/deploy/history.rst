Deployment history
==================

PsyNet appends an operational event log at
``data/deployment-events.jsonl`` whenever you run a deployment command that
has lasting effect or real cost from the experiment directory:

* ``psynet deploy local|heroku|ssh``
* ``psynet debug heroku|ssh`` (sandbox deployments)
* ``psynet export local|heroku|ssh``
* ``psynet destroy heroku|ssh``
* ``psynet comment``

Disposable ``psynet debug local`` sessions are not recorded.

Each event is one JSON object with at least ``schema_version``, ``at``
(UTC), and ``event``. Action events also include the full command ``argv``
and, when provided, a ``comment`` field. Failures record an ``error``
message when available.

Attach a comment to a command:

.. code-block:: bash

    psynet destroy ssh my-app --server lab --comment "Accidentally deployed to the wrong country"
    psynet export ssh --app my-app --comment "End of day 1"

Add a free-floating note (optionally associated with a local ID or app):

.. code-block:: bash

    psynet comment "Changed headphones."
    psynet comment --id gibbs "Lab booth B"
    psynet comment --app my-app "Paused recruitment overnight"

Browse the log interactively with a Textual full-screen browser when run in a
terminal. The footer lists the keys; the top bar shows the active filters.

* ``↑`` / ``↓`` (or ``j`` / ``k``) move
* ``a`` / ``f`` / ``c`` / ``s`` filter by type (all / failures / comments / succeeded)
* ``0``–``6`` filter by command family
* ``?`` help in the detail pane
* ``q`` quit

Non-interactive environments fall back to a static timeline:

.. code-block:: bash

    psynet history
    psynet history --limit 20
    psynet history --no-interactive
    psynet history --json

Event history may contain operational or participant information and is
excluded by PsyNet's standard ``.gitignore``.
