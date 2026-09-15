Installing PsyNet via Docker (removed)
======================================

The experiment-local Docker helper scripts (``bash docker/build``,
``bash docker/psynet``, and the rest of the generated ``docker/`` directory)
have been removed. They called ``docker build`` directly and could not honor
``deploy.toml``.

Install PsyNet in a virtual environment, then use the standard commands:

- ``psynet debug local`` for a local virtualenv run
- ``psynet debug local --docker`` or a Docker deploy command when you want
  Dallinger to build from the reviewed ``deploy.toml`` plan

See :ref:`installation` and :ref:`docker`.
