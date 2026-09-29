.. _experiment_directory:

Experiment directory
====================

An experiment is a directory containing ``experiment.py`` and the files
listed below. ``psynet setup`` and ``psynet scripts scaffold`` create the
boilerplate files that are missing. Which files are deployed is decided by
``deploy.toml`` (see :doc:`/deploy/how_deployment_works`).

Files you edit
--------------

``experiment.py``
    Defines the ``Experiment`` class and its timeline. Helpers can live in
    sibling modules (see :ref:`experiment_python_modules`).

``requirements.txt``
    The Python packages the experiment needs, including the PsyNet pin (see
    :ref:`dependencies`).

``config.txt``
    Configuration for local runs and deployment (see
    :doc:`/reference/configuration`). It must exist but may be empty. An
    existing file is never overwritten. When upgrading an older experiment
    that keeps its settings in ``Experiment.config``, create an empty file
    with ``touch config.txt`` rather than scaffolding the template.

``static/``
    Files the participant's browser loads directly, such as stimuli, scripts
    and images. ``static/your-file.png`` is served at
    ``/static/your-file.png``. This is the usual place for a stimulus set (see
    :doc:`/code/using_stimuli`).

``templates/``
    `Jinja <https://jinja.palletsprojects.com/>`_ templates that customize
    PsyNet's front end (see :doc:`/code/pages/custom_front_ends`). Most
    experiments leave it empty.

``README.md``
    A description of the experiment for future readers. PsyNet creates a
    default one when it is missing and never overwrites it.

``deploy.toml``
    Which files enter debug staging and deployment. PsyNet creates it from a
    template when it is missing and never overwrites it.

``.gitignore``
    Which files Git tracks. It has no effect on deployment.

``prepare_docker_image.sh``
    Optional. Installs system packages into the Docker image (see
    :ref:`dependencies`).

Generated files
---------------

Don't edit these files by hand, with one exception: ``constraints.txt`` can
be written by hand when generation fails (see
:ref:`dependencies_handwritten_constraints`). Commit all of them except
``.cursor/skills/psynet/``. ``psynet scripts update`` replaces the
boilerplate templates with those of the installed PsyNet version, and
``psynet scripts scaffold`` recreates any that are missing.

``constraints.txt``
    Exact versions of every Python package, generated from
    ``requirements.txt`` by ``psynet setup`` or
    ``psynet generate-constraints``.

``Dockerfile``
    Defines the experiment's Docker image.

``Dockertag``
    The name of the Docker image, set to the directory name.

``.python-version``
    The Python major and minor version that was active when the experiment
    was scaffolded.

``test.py`` and ``pytest.ini``
    Run bots through the experiment with ``psynet test local``. Customize the
    test by overriding methods of the ``Experiment`` class rather than
    editing ``test.py`` (see :doc:`/test/backend`).

``__init__.py``
    Makes the directory a Python package.

``AGENTS.md``
    Instructions for coding agents working in the experiment.

``.vscode/launch.json``
    The VS Code and Cursor debugger configuration used by
    :func:`psynet.debugger`.

``.github/workflows/test.yml``
    A GitHub Actions workflow that runs the experiment's test on each push
    and pull request.

``.cursor/skills/psynet/``
    PsyNet's Agent Skills for coding agents. ``psynet scripts update``
    replaces this directory. The stock ``.gitignore`` and ``deploy.toml``
    exclude it. Other directories under ``.cursor/skills/`` belong to the
    experiment and are kept.

Runtime files
-------------

PsyNet creates these while running the experiment. The stock ``.gitignore``
and ``deploy.toml`` exclude them.

``.deploy/``
    Deployment resources, such as database templates and launch metadata.

``server.log``
    The log of the last local run.

``static/assets/``
    Assets prepared for local runs.

``exports/``
    Data exported with ``psynet export``.

.. _experiment_python_modules:

Importing other Python files
----------------------------

Experiment code can be split across several ``.py`` files in the experiment
directory. Dallinger imports the directory as the package
``dallinger_experiment``, so ``experiment.py`` must import its siblings with
relative imports:

.. code-block:: python

    from . import adaptive_logic

    def choose_next_item(state):
        return adaptive_logic.select_item(state)

For the same reason, ``python experiment.py`` is not a valid import check;
use ``psynet test local``.
