.. _Version control with Git:

Using Git with an experiment
============================

Every PsyNet experiment is a Git repository. ``psynet setup`` runs
``git init`` if the directory isn't one already, and Git itself is installed
as part of :doc:`/install`.

What PsyNet uses Git for
------------------------

A remote deployment needs at least one commit. PsyNet records the deployed
commit, and whether any deployed file had uncommitted changes, with the
deployment. ``psynet export`` compares that record with your local checkout
and warns if they differ. :doc:`/deploy/how_deployment_works` describes
which files count.

Commit and tag before deploying
-------------------------------

Commit all changes before a live deployment, then tag the commit so that you
can find the deployed version later:

.. code-block:: bash

    git add .
    git commit -m "Prepare pilot deployment"
    git tag -a deploy-pilot -m "Pilot deployment"
    git push
    git push --tags

``git push`` doesn't push tags, so push them separately. To look at the
experiment as it was deployed, run ``git switch --detach deploy-pilot``, and
``git switch -`` to return.

Keep the repository on a Git host such as `GitHub <https://github.com/>`_ or
`GitLab <https://gitlab.com/>`_, so that it is backed up and collaborators
can see it.

.. lab-note::

   The Computational Auditory Perception group at the Max Planck Institute
   for Empirical Aesthetics keeps experiment repositories in its private
   GitLab group, ``https://gitlab.com/computational-audition-lab``.

Choose what to commit
---------------------

Commit ``experiment.py`` and your other source files, ``requirements.txt``,
``constraints.txt``, ``config.txt``, ``deploy.toml`` and the generated
boilerplate listed in :doc:`/code/project/experiment_directory`. Small
stimulus files can be committed too.

The stock ``.gitignore`` already excludes virtual environments, ``.env``,
logs, exports and PsyNet's generated files. Add these yourself:

- credentials, such as API keys and deploy tokens;
- participant data, including anything you copy out of an export;
- large media files that you host elsewhere.

``.gitignore`` only controls Git. Which files are deployed is set in
``deploy.toml``, so a Git-ignored file can still be deployed.

Adding a file to ``.gitignore`` doesn't stop Git tracking a file that was
already committed. Stop tracking it with:

.. code-block:: bash

    git rm --cached secret-api-key.txt

The file stays in the repository's history. If it contained credentials,
revoke them and issue new ones. GitHub's guide to
`removing sensitive data <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository>`_
describes how to rewrite history if you need to.

Learn Git
---------

The Software Carpentry lesson
`Version control with Git <https://swcarpentry.github.io/git-novice/>`_
covers the everyday commands. The free book
`Pro Git <https://git-scm.com/book/en/v2>`_ is a complete reference. Most
IDEs, including VS Code and Cursor, have a Git panel for staging, committing
and resolving merge conflicts.
