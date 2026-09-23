General research process
========================

Experiment lifecycle
--------------------

Experiments follow a relatively fixed lifecycle.

-  :ref:`Design <lab-deployment-design>`: Start with a research question and design an
   experiment that can answer it. Discuss the design with collaborators,
   lab members, or ``#online-experiments`` on Slack before
   implementation.

-  :ref:`Test <lab-deployment-test>`: Test the experiment automatically, on yourself, and
   with a small set of colleagues or friends.

-  :doc:`Provision <provisioning>`: Prepare the server
   that will host the experiment. Use an internal server when appropriate
   or provision an EC2 server when participant location or capacity
   requires it.

-  :doc:`Launch <deploying>`: Launch the experiment for real
   participants. For a first deployment, start with a pilot.

-  :doc:`Monitor <monitoring_and_managing>`: Watch
   the experiment during data collection, check for errors, review data
   quality, and compensate participants when needed.

-  :doc:`Export & Terminate <exporting_and_terminating>`: Export the
   data, run preliminary checks, and terminate the experiment once data
   collection is complete.

-  :doc:`Teardown <teardown>`: If you used an EC2 server, turn it off
   when you are done.

.. image:: /_static/images/lab_deployments/image7.png
   :width: 8.5in

.. _lab-deployment-design:

Design
------

Designing an experiment is an iterative process. It often requires
multiple designs to get things right. Generally the design phase
together with the test phase should be what you spend most time and
energy on. Unlike lab experiments, once you get your experiment right,
it’s trivial to collect the data on participants.

We recommend the following procedure:

-  Define the question you want to answer and design an experiment that
   addresses it.

-  Get feedback from collaborators and lab members.

-  Once you settle on an idea, look for a PsyNet demo that implements
   some of the relevant components. You may need building blocks from
   multiple demos, or in some cases custom PsyNet functionality.

-  A central philosophy of a healthy lab workflow is to help each other
   get unstuck.
   If you encounter a technical or design problem and have already spent
   a reasonable amount of time on it, ask for help:

   -  Post technical problems in ``#psynet-support`` or design questions
      in ``#online-experiments`` on Slack.

   -  Raise the issue during standing.

.. _lab-deployment-test:
.. _testing-within-the-group:

Test
----

Use the full :doc:`testing tutorial </guides/testing/tests>` for details on
PsyNet's test commands. In the lab deployment workflow, the important
checkpoint is that the experiment has been tested in the same order it
will be deployed:

1. Run the experiment locally and take it yourself as if you were a real
   participant. This helps verify the task, instructions, time estimate,
   payment estimate, and edge cases:

   .. code:: bash

      psynet debug local

2. Run bot tests to catch obvious logic failures:

   .. code:: bash

      psynet test local --n-bots 3 --parallel

3. Run a shortened pilot with colleagues or collaborators using
   ``hotair`` recruitment. Before launching, confirm that the experiment is
   configured with ``recruiter = hotair`` in ``config.txt`` or the equivalent
   experiment configuration. Then provision a server and launch a remote debug
   session from the experiment directory:

   .. code:: bash

      psynet debug ssh --app <app_name> --dns-host <your-subdomain>.<your-domain> --server <your-subdomain>.<your-domain>

4. Use the pilot data to verify your analysis and export scripts before
   collecting real participant data.

Pay particular attention to whether the experiment stops automatically,
whether it slows down under load, how many simultaneous participants the
server can handle, and whether resource-intensive synthesis or analysis
steps need stronger hardware.

Automatic translation
---------------------

PsyNet supports automatic machine translation so you can run your
experiment in different languages. Treat translation as part of the
pre-launch checklist: set the target locale, mark strings for
translation, generate translations, then review the translated experiment
before recruiting real participants.

For full setup instructions, including OpenAI and Google translation
backends, see the
:doc:`internationalization tutorial </guides/participants/internationalization>`.
The command you normally run from the experiment directory is:

.. code:: bash

   psynet translate

Recruiters
----------

We currently use three recruiters: **Prolific, CINT, and Lab Recruiter
(LR).** Please decide which one to use.

-  `Prolific <https://www.prolific.com/>`__ offers a high-quality,
   diverse participant pool, ideal for academic and market research.

-  `CINT <https://www.cint.com/>`__ provides access to a larger
   participant pool, making it particularly useful for recruiting
   participants across different countries and languages, allowing
   for more culturally diverse studies. The provisioning steps for
   both platforms are identical. For detailed instructions, please
   refer to the recruiter-specific steps for Prolific and CINT. Note that
   Lucid was recently acquired by CINT, a large global recruiter.

-  **Lab Recruiter** (LR) is an internally established recruitment
   system that offers full control over participant selection without
   third-party involvement. Labs that run their own Lab Recruiter
   instance can use it to recruit from their own participant pool.

For configuration keys such as ``recruiter``, ``wage_per_hour``,
``base_payment``, ``initial_recruitment_size``, and
``soft_max_experiment_payment``, see the
:doc:`configuration reference </reference/configuration>`.
For the order of recruiter-specific setup checks, continue to
:doc:`recruiter_specific_deployment_steps`.
