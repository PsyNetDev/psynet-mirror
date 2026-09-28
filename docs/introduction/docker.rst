.. _docker:

Docker
======

`Docker <https://www.docker.com/>`_ runs software in 'containers' that behave
like self-contained operating systems. PsyNet uses it in two places:

- **Local services.** On your computer, Docker runs the PostgreSQL database
  and the Redis cache that PsyNet needs. ``psynet services ensure`` starts
  them. The experiment itself runs in its own Python environment, the
  ``.venv`` folder that ``psynet setup`` creates, so ``psynet debug local``
  uses Docker for the experiment only when you pass ``--docker``.
- **Deployment.** When you deploy, PsyNet builds the experiment into a Docker
  image that captures all of its dependencies. The server runs that image,
  so later changes to Python versions or operating systems don't affect the
  deployed experiment. See :ref:`deployment_build_context` for which files
  go into the image.
