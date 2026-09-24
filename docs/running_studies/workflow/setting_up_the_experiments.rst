Pre-launch setup overview
=========================

This page is a summary of the checks to complete before launching your
experiment. Each section links to the detailed documentation where you
can find full instructions. Recruiter-specific instructions are covered
in :doc:`Recruiter-specific steps <recruiters/index>`.

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
:doc:`Recruiter-specific steps <recruiters/index>`
and configure all recruiter-specific settings.

Test the experiment
-------------------

Complete :ref:`lab-deployment-test` before a public launch.

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
