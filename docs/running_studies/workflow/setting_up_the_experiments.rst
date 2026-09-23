Pre-launch setup overview
=========================

This page is a summary of the checks to complete before launching your
experiment. Each section links to the detailed documentation where you
can find full instructions. Recruiter-specific instructions are covered
in :doc:`Recruiter-specific steps <recruiter_specific_deployment_steps>`.

Define the experiment configuration
-----------------------------------

Make sure the required experiment parameters are set and match the
version you intend to deploy:

- Consent.
- Experiment title and description.
- Payment settings.
- Expected completion time.
- Target participant count.
- Locale, if the experiment is translated.

Run the estimate command from the experiment directory:

.. code:: bash

   psynet estimate

Use the output to confirm that the expected completion time and
compensation are reasonable before you configure the recruiter.

.. _storage:

Choose a storage backend
------------------------

Use a deployment-ready storage backend. For experiments with assets,
choose either S3 storage or local storage according to the needs of the
experiment. Do not deploy with ``DebugStorage`` — it is only intended
for local development. For guidance on storage options, see the
:doc:`Assets tutorial </guides/trials/assets>`.

Choose a recruiter
------------------

Choose the recruiter before you launch, because each recruiter has
different setup requirements:

- :ref:`Prolific <lab-deployment-prolific>`.
- :ref:`CINT <lab-deployment-cint>`.
- :ref:`Lab Recruiter <lab-deployment-lab-recruiter>`.

After choosing the recruiter, read the matching section in
:doc:`Recruiter-specific steps <recruiter_specific_deployment_steps>`
and configure all recruiter-specific settings.

Test the experiment
-------------------

Before public deployment, test the experiment in each of these modes:

- **Local test:** Run the experiment on your own machine with
  ``psynet debug local``.
- **Docker test:** Run the experiment through the Docker installation to
  confirm that dependencies are captured in ``requirements.txt``.
- **Remote debug:** Run the experiment on the deployment server with
  ``psynet debug ssh``.
- **Hotair:** Share a private testing link (set ``recruiter = hotair``)
  before publishing the experiment to real participants.

For full details on each testing mode, see the
:ref:`testing section <lab-deployment-test>` of the general research
process.

Final pre-launch check
----------------------

Before running the deployment command:

- Restore the full production version of the experiment if you shortened
  it for testing.
- Confirm that the recruiter configuration has been changed from
  ``hotair`` to the intended live recruiter.
- Check that all recruiter-specific requirements are complete.
- Discuss the payment strategy and confirm the budget. For Prolific,
  make sure the account has enough balance before launching.
