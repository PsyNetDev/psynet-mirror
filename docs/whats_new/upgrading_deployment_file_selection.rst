Migrating deployment file selection
===================================

PsyNet now uses ``deploy.toml`` to decide which experiment files enter local
debug staging and remote deployment packages. Earlier versions used Git
visibility and ``.gitignore`` for this purpose.

This is a deliberate separation:

* ``.gitignore`` decides which files Git tracks.
* ``deploy.toml`` decides which files PsyNet copies.

Create and review the policy
----------------------------

Run ``psynet setup`` or ``psynet scripts scaffold`` to create the stock
``deploy.toml`` without overwriting an existing policy. The first debug, test,
or deployment command after that auto-created file stops before copying files,
whether the file was created by setup or by the launch command itself.
The message lists files covered by ``.gitignore`` but not by the new policy.
Git-ignored files may still be deployed after that one-time review.
In-repo demo prepare and pytest's temporary scaffold skip that pause so the
first local test or debug can run.

Preview the complete deployment plan:

.. code-block:: console

   dallinger deployment-files list

This command only prints the files that PsyNet would copy. It does not start or
deploy the experiment. Check the output for credentials, private data, exports,
large local files, and generated files. Add anything that should stay local to
the ``[exclude]`` section of ``deploy.toml``, then run the preview again.

``paths`` are root-relative prefixes, ``names`` are basenames excluded in every
directory, and ``suffixes`` are literal filename endings. Git globs and
negation are not supported, so translate custom ``.gitignore`` rules
deliberately instead of copying them verbatim. See Dallinger's
`deploy.toml guide <https://github.com/Dallinger/Dallinger/blob/master/docs/source/deploy_toml.rst>`_
for the complete format.

Remove old Docker selection files
---------------------------------

``.dockerignore`` is no longer supported. PsyNet removes recognized generated
copies, but preserves custom files and stops debug or deployment until their
rules have been moved to ``deploy.toml`` and the old file has been removed.

Generated experiment-local ``docker/`` helper scripts are also obsolete because
they bypass the reviewed deployment plan. Replace commands such as
``bash docker/run`` or ``bash docker/psynet`` with:

.. code-block:: console

   psynet debug local
   psynet debug local --docker

The ``psynet setup --docker`` option has been removed. Run ``psynet setup``
first, then choose ``psynet debug local --docker`` when Docker execution is
needed.

Verify the migration
--------------------

After updating ``deploy.toml``:

#. Run ``dallinger deployment-files list`` and inspect the complete output.
#. Confirm that authored experiment files are present.
#. Confirm that credentials, exports, participant data, virtual environments,
   generated local files, and the ``audit/`` review packet are absent.
#. Run ``psynet test local``.
#. Commit the reviewed ``deploy.toml`` before a remote deployment.

PsyNet never overwrites an existing ``deploy.toml``. If your experiment already
has one, add ``audit`` to ``[exclude].paths`` so the local review packet is not
copied into debug staging or the deployment package. Stock templates created
from this PsyNet version already include that path.

Git provenance records the commit and whether deployment-selected files contain
uncommitted changes. Remote deployments require at least one Git commit; local
debug and test runs may use a newly initialized repository.
