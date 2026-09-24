Pre-launch setup overview
=========================

This page is a summary of the checks to complete before launching your
experiment. Each section links to the detailed documentation where you
can find full instructions. Recruiter-specific instructions are covered
in :doc:`Recruiter-specific steps <recruiters/index>`.

Estimate duration and cost
--------------------------

Set ``wage_per_hour`` according to your recruiter and your lab's payment
policy (each recruiter page lists the usual value). Make sure every
page's ``time_estimate`` is realistic, then run this from the experiment
directory:

.. code:: bash

   psynet estimate

Use the output to confirm that the expected completion time and
compensation are reasonable before you configure the recruiter.

Then check the estimate against real timings:

- Use your own data (and, optionally, pilot data from colleagues) for
  each trial, any pre-screeners, and the whole experiment.
- Start with a small number of participants (for example 10). If the
  real duration is more than about 30% off, update ``time_estimate``
  values and redeploy.
- Once you have live data, update the estimates from that data.

Each recruiter page notes anything extra: Prolific's recommended wage
and putting cost in the study title, CINT's country minimum wage and
omitting cost from the title, Lab Recruiter's lab payment policy.

Define the experiment configuration
-----------------------------------

Make sure the required experiment parameters are set and match the
version you intend to deploy:

- Consent.
- Experiment title and description. Mention Chrome, approximate
  duration, and headphones or a microphone if the task needs them.
- Payment settings.
- Expected completion time.
- Target participant count.
- Locale, if the experiment is translated.

Example title and description:

.. code-block:: text

   Check recorded texts (Chrome browser, headphones required, ~10–15 mins)

   In this experiment you will hear spoken sentences and need to judge
   the quality of their transcript. The experiment requires Chrome and
   headphones. It lasts 10–12 min.

You can set these in ``config.txt`` or on the ``Experiment`` class; see
:doc:`/reference/configuration`. Recruiter-specific keys such as
``get_prolific_settings()`` or ``get_lucid_settings()`` stay on the
matching recruiter page.

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
