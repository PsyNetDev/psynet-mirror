Running a study
===============

The steps below take an experiment that already runs locally through to
real data collection and teardown. They assume you have a server
registered with Dallinger (see :doc:`/deploy/setting_up_a_server`).
Prolific is the worked example; CINT and Lab Recruiter differ in the
recruiter-specific steps, which are covered in their guides
(:doc:`/deploy/recruiters/cint`, :doc:`/deploy/recruiters/lab_recruiter`).

Before launch
-------------

.. _lab-deployment-test:
.. _testing-within-the-group:

Test the experiment
^^^^^^^^^^^^^^^^^^^

Test in the same order the experiment will be deployed:

1. Take the experiment yourself as a participant, checking the
   instructions, the time each part takes, and edge cases:

   .. code:: bash

      psynet debug local

2. Run the automated bot tests (see :doc:`/test/backend`):

   .. code:: bash

      psynet test local

   Add ``--n-bots 3 --parallel`` to check that several participants can
   run at once.

3. Run the experiment in Docker locally, so that missing dependencies show
   up before you reach the server:

   .. code:: bash

      psynet debug local --docker

4. If the experiment has an audit (see :doc:`/test/audits`), review it
   with ``psynet audit serve --render``.

5. Pilot the experiment on your server (see `Pilot`_).

Check the code and dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- The experiment must be in a Git repository with at least one commit.
  PsyNet records the deployed commit and whether the working tree had
  uncommitted changes, and ``psynet export`` compares them with your
  checkout later, so commit everything before you deploy and push to your
  remote.
- The PsyNet and Dallinger versions you tested locally must match
  ``requirements.txt``. If you change ``requirements.txt``, regenerate and
  commit ``constraints.txt`` with ``psynet generate-constraints``; PsyNet
  refuses to deploy with an out-of-date ``constraints.txt``. See
  :doc:`/code/project/dependencies`.
- Remote deployment refuses to start while the experiment contains
  ``# TODO`` or ``// TODO`` comments in ``.py``, ``.html`` or ``.js``
  files. Resolve them, or set ``SKIP_TODO_CHECK=1``.
- ``docker_image_base_name`` must be set in ``config.txt`` or
  ``~/.dallingerconfig``. Any name works, because the image is built on
  your server:

  .. code-block:: ini

     [Docker]
     docker_image_base_name = psynet-experiments

Consent
^^^^^^^

The timeline must contain a consent page; deployment fails without one.
Some recruiters require a particular consent (CINT requires
``LucidConsent``). See :doc:`/reference/api/consent`.

Time estimate and payment
^^^^^^^^^^^^^^^^^^^^^^^^^

Set ``wage_per_hour`` and give every page a realistic ``time_estimate``,
then run:

.. code:: bash

   psynet estimate

.. code-block:: text

   Estimated maximum reward for participant: £5.00.
   Estimated time to complete experiment: 10 min 0 sec.

The estimate follows the longest route through the timeline and ignores
performance bonuses. Check it against real timings from your own run and
the pilot. If the real duration differs by more than about 30%, adjust the
``time_estimate`` values. Use the estimated reward as ``base_payment``
and the estimated duration as the recruiter's completion time (for
Prolific, ``prolific_estimated_completion_minutes``). How each recruiter
turns these values into payments, and the usual ``wage_per_hour``, is in
its guide; for Prolific see :doc:`/deploy/recruiters/prolific`.

PsyNet also caps spending per participant and per experiment; see
:doc:`/code/participants/payment_limits`.

.. lab-note::

   Agree the payment strategy and total budget with your lab before
   launching. If the lab shares a Prolific workspace, ask the
   administrator to add funds if the balance does not cover the study.

Title and description
^^^^^^^^^^^^^^^^^^^^^

Set ``title`` and ``description`` in ``config.txt`` or the experiment's
``config`` dictionary (see :doc:`/reference/configuration`). The title is
limited to 128 characters. Mention the requirements participants must meet
before they start: a Chrome browser, headphones or a microphone if
needed, and the approximate duration. In the description, say briefly what
the task involves and how you pay participants who do not finish, for
example after a failed pre-screening task or a technical error.

.. code-block:: text

   title = Check recorded texts (Chrome browser, headphones required, ~10–15 mins)
   description = In this experiment you will hear spoken sentences and judge
       the quality of their transcript. You are paid in proportion to how far
       you get through the experiment.

Whether to put the payment in the title depends on the recruiter: do so on
Prolific, not on CINT.

Recruiter settings
^^^^^^^^^^^^^^^^^^

Choose the recruiter (see :doc:`/deploy/recruiters/index`) and complete
its setup, including credentials in ``~/.dallingerconfig``,
qualifications, and recruiter-specific configuration keys. For Prolific,
see :doc:`/deploy/recruiters/prolific`.

.. _storage:

Storage
^^^^^^^

Experiments with assets need a deployment-ready storage backend: local
storage on the server or S3. ``DebugStorage`` is only for local
development. See :doc:`/code/trials/assets`.

Translations
^^^^^^^^^^^^

If the experiment runs in other languages, set ``locale``, generate the
translations with ``psynet translate``, and review the translated
experiment before recruiting. See
:doc:`/code/participants/internationalization`.

Pilot
-----

Pilot the experiment on the server with the ``generic`` recruiter, which
creates no study on any recruitment platform. Prolific has no sandbox
mode, so this is the way to try the deployed experiment without
recruiting. Set the recruiter in ``config.txt``:

.. code-block:: ini

   recruiter = generic

Shorten the experiment if that makes piloting easier (for example fewer
trials), then launch a debug deployment:

.. code:: bash

   psynet debug ssh --app my-study-pilot --server your-server.example.org

The experiment is available at
``https://my-study-pilot.your-server.example.org`` within a minute or two.
The terminal prints a *Single recruitment link*; take the experiment
through it yourself and send it to a few colleagues. Check:

- the median completion time against your estimate;
- that the experiment ends automatically for every route through it;
- that the server stays responsive with several participants at once,
  and that heavy synthesis or analysis steps run fast enough;
- that your analysis scripts work on the pilot data (export it as
  described in `Export`_).

``psynet debug`` deployments do not register with the deployment monitor
or send Slack notifications. Remove the pilot when you are done:

.. code:: bash

   psynet destroy ssh --app my-study-pilot --server your-server.example.org

.. _lab-deployment-actual-deployment:

Launch
------

Restore the full version of the experiment if you shortened it, set the
live recruiter, and commit:

.. code-block:: ini

   recruiter = prolific

For CINT, ``get_lucid_settings()`` sets the recruiter; for Lab Recruiter,
use ``lab-recruiter``.

If your server is only reachable over a VPN, connect to it. Then deploy
from the experiment directory:

.. code:: bash

   psynet deploy ssh --app my-study --server your-server.example.org

``--app`` becomes the first part of the participant URL
(``https://my-study.your-server.example.org``), so use lowercase letters,
digits and hyphens. If your DNS record only publishes a fixed list of
subdomains, the app name must be one of them. Several experiments can run
on one server with different app names.

``--server`` is the name you registered the server under. If you omit it
and several servers are registered, PsyNet asks you to choose.
``dallinger ec2 provision --dns-host`` registers a server twice (under its
AWS hostname and under the DNS name), so pass ``--server`` explicitly in
that case. If you registered the server by IP address, also pass
``--dns-host``.

The command builds the experiment image on the server, starts the
experiment's services, and opens recruitment; see
:doc:`/deploy/how_deployment_works`. When it finishes it prints:

- the recruitment message (for Prolific, a link to the new draft study);
- the dashboard link with its user name and password;
- a command and a Dozzle URL for viewing the logs.

Save these. Open the dashboard and check that the experiment is running.
If the command fails or hangs, see
:doc:`/deploy/reference/troubleshooting`.

To redeploy from an earlier export after fixing a problem, see
:doc:`/deploy/reference/deploy_from_archive`.

Review the draft study on Prolific
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PsyNet creates the study as a draft in the workspace and project set in
``~/.dallingerconfig``, filling in the title, description, reward,
completion time, completion codes and any qualifications. Open it from the
link in the terminal and check:

- **Payment**: the reward and completion time match your estimate, and
  the formatting of the description is as intended.
- **Process submissions**: PsyNet registers its completion codes with
  automatic approval and completes submissions itself, so you do not
  approve participants by hand. If the draft offers "Manually review" or
  "Approve and pay", keep **Approve and pay**.
- **Places**: the number of participants, taken from
  ``initial_recruitment_size``. Start with about 10; much smaller numbers
  can make Prolific deprioritize the study.
- **Audience**: the demographic filters. Prolific shows how many active
  participants match them.
- **Concurrent participants**: leave the limit on simultaneous
  participants unset; recruitment has been very slow when it is set.
- **Cost**: set the places temporarily to the total you plan to recruit
  (plus a few if you pre-screen) to see the total cost, including
  Prolific's fee, in the "Study cost" section, and check that the
  workspace balance covers it.

.. image:: /_static/images/running_studies/recruiters/prolific/check-adapt-study-details.png
   :width: 8.5in
   :alt: A PsyNet study in the Prolific drafts list

.. image:: /_static/images/running_studies/recruiters/prolific/study-cost-and-balance.png
   :width: 8.5in
   :alt: Prolific study cost and workspace balance

Preview the study as a participant from the draft. Anything you do in the
preview is saved as a real participant, so stop before the end or filter
yourself out of the data. When everything is right, click **Publish
study**.

``publish_experiment = true`` publishes the study immediately instead of
leaving a draft. This saves time when deploying many similar studies, but
removes the chance to check the study on Prolific first.

.. lab-note::

   In a shared Prolific account, set the study's internal name to
   "<your name> - <short experiment name>" so lab members can tell whose
   study a participant message belongs to. Deploy into a project named
   after you (see :doc:`/deploy/recruiters/prolific`).

Recruit
-------

Start with a small batch of 5–10 participants. When they have finished,
check before recruiting more:

- the dashboard and logs for errors (see `Monitor`_);
- the real completion time against the estimate; update ``time_estimate``
  values and redeploy if it is more than about 30% off;
- an export of the data (see `Export`_).

Then increase the places in batches. On Prolific, open the study, choose
**Action > Increase places**, and enter the number of *additional*
participants. PsyNet typically copes with about 50 simultaneous
participants, depending on how efficient the experiment code is. Keep the
median hourly wage on the Prolific study page above Prolific's minimum.

.. image:: /_static/images/running_studies/recruiters/prolific/recruitment-strategy.png
   :width: 8.5in
   :alt: Increasing places on a Prolific study

Auto-recruit
^^^^^^^^^^^^

With ``auto_recruit`` on, PsyNet adds a place each time a participant
finishes, so the number of active participants stays constant. The
recommended setting at launch is ``auto_recruit = false``. You can switch
it on and off from the dashboard's home page while the experiment runs.

.. image:: /_static/images/running_studies/recruiters/prolific/auto-recruit-dashboard.png
   :width: 8.5in
   :alt: Auto-recruit switch on the experiment dashboard

- Only switch it on after the first batch has finished without errors
  or complaints and the data looks right.
- Switch it off at about 90% of the target and recruit the rest by hand.
  In some designs, late participants have little left to do but are still
  paid in full.
- Stopping the study on Prolific does not switch auto-recruit off.

Payment limits
^^^^^^^^^^^^^^

Recruitment stops when the amount spent reaches
``soft_max_experiment_payment``, and PsyNet emails the experimenter. This
is an experiment variable, not a configuration key: set its initial value
in the experiment class's ``variables`` dictionary, or change it on the
dashboard's Timeline tab while the experiment runs. See
:doc:`/code/participants/payment_limits`.

.. _lab-deployment-dashboard:

Monitor
-------

Check the experiment regularly while participants are taking part.

**Dashboard.** The dashboard link printed at launch opens the same
dashboard for every recruiter. It shows progress through the timeline,
spending, errors, server resources and individual participants; see
:ref:`experiment_dashboard` for each tab. When you run several studies,
the Deployments tab (the deployment monitor) shows all of them at once.

**Logs.** Dozzle shows the live logs of every container on the server.
Its URL is printed at launch (``https://logs.your-server.example.org``
for servers that use subdomains); log in as ``dallinger`` with the
printed password. You can also read the logs over SSH:

.. code:: bash

   ssh <user>@your-server.example.org
   cd ~/dallinger/my-study
   docker compose logs web

The experiment's services are ``web``, ``worker_1`` to ``worker_N``,
``clock``, ``redis`` and ``pgbouncer``; ``docker compose logs`` without a
service name shows all of them.

**Errors.** The dashboard's Errors tab lists every recorded error with its
stack trace, and the Logger shows the live log stream; see
:doc:`/deploy/reference/errors`. Fix critical errors immediately, which
may mean pausing recruitment and redeploying.

**Participant messages.** On Prolific, participants message you through
Prolific's messaging system; reply promptly. Look the participant up by
their Prolific ID in the Worker ID field of the dashboard's Participants
tab. The participant page has a **Link for resuming session** you can
send them if they can continue.

Participants who hit an error, fail a pre-screening task or leave early
are paid automatically: they click **Submit to Prolific**, PsyNet
completes the submission with a screen-out payment and tops it up to the
reward they had earned. Do not ask them to return the submission or pay
them by hand unless they never submitted (for example they closed the
error page) or ``prolific_pay_unsuccessful`` is false. The payment rules
are in :doc:`/deploy/recruiters/prolific`.

**Slack notifications.** Slack notifications report launches, errors and
recruitment changes, and forward new Prolific messages for the study. They
are worth setting up for long or high-risk studies; see
:doc:`/deploy/reference/setting_up_slack`.

.. lab-note::

   Ask your lab administrator which Slack channel and bot token to use. If
   your lab maintains scripts for deploying or destroying many
   experiments at once, check each generated configuration before launch,
   keep app and server names traceable, and export and check data before
   scaling up recruitment.

.. _lab-deployment-export-data:

Export
------

Export the data after the first batch, regularly during data collection,
and once more after the last participant has finished:

.. code:: bash

   psynet export ssh --app my-study --server your-server.example.org

Run the command in the experiment directory the deployment came from. The
export lands in ``exports/latest/``. The dashboard's Export tab downloads
the same data as ``export.zip``. Export options, the export layout and
checking data during collection are covered in
:ref:`data_export_deployed`.

Destroying the app or the server deletes any data you have not exported.

Tear down
---------

When the target number of participants is reached:

1. Stop the study on the recruiter. PsyNet never closes a Prolific study
   itself; stop it from the study page on Prolific, and switch off
   auto-recruit on the dashboard.
2. Wait until no participants are still taking part.
3. Review payments. On the dashboard's Participants tab, handle anyone
   listed under **Needs payment review**: PsyNet meant to pay them a bonus
   but could not confirm it, and you can pay or dismiss it there. On
   Prolific, check the **Awaiting review** list. Successful and
   screened-out submissions do not appear there; the rest are typically
   people who stopped without submitting, submissions PsyNet could not
   complete (check the experiment's notifications), or codes set to manual
   review. Talk to the participant before rejecting a submission.

   .. image:: /_static/images/prolific/awaiting_review_2.png
      :width: 800
      :alt: Prolific submissions awaiting review

4. Export the data one final time.
5. Remove the experiment from the server:

   .. code:: bash

      psynet destroy ssh --app my-study --server your-server.example.org

   This stops the experiment's containers and deletes its files on the
   server.

.. warning::

   Stop the Prolific study before you destroy the app. Otherwise
   participants can still start a study whose server no longer exists.
   Each deployment creates a new Prolific study, so this applies to every
   redeploy; you can exclude participants of earlier deployments with
   Prolific's filters.

If the server was provisioned only for this study, tear it down as well;
see :doc:`/deploy/setting_up_a_server`. For an EC2 server created with
``dallinger ec2 provision``, pass the same ``--dns-host`` so that the DNS
records and the server registration are removed:

.. code:: bash

   dallinger ec2 teardown --name my-server --region us-east-1 \
       --dns-host my-server.your-domain.org

Once an EC2 server is terminated, anything on it that was not exported is
lost.

For CINT and Lab Recruiter, the recruiter's ending steps are in
:doc:`/deploy/recruiters/cint` and :doc:`/deploy/recruiters/lab_recruiter`.

.. lab-note::

   Move the finished study into your folder on the lab's Prolific account,
   and deposit the final export in the lab's data repository.

Getting help
------------

Read the whole stack trace. The last line names the error, but it is
often a symptom of an earlier one further up. Search for the specific
part of the message first (for example a missing key such as
``show_bonus``), then for the error type together with the failing
function, in the
`PsyNet issue tracker <https://gitlab.com/PsyNetDev/PsyNet/-/issues>`__,
the `Dallinger issue tracker <https://github.com/Dallinger/Dallinger/issues>`__,
or a web search. Many problems come from a mismatch between your local
PsyNet version and the one in ``requirements.txt``. Common deployment
problems are listed in :doc:`/deploy/reference/troubleshooting`.

If you have been stuck for about an hour, ask in a shared place, such as
a PsyNet issue, so others can find the answer. Include what you were
trying to do, the full stack trace, the PsyNet and Dallinger versions
used locally and in ``requirements.txt``, whether you run in a virtual
environment or Docker, and if possible a minimal example. When the
problem is solved, post what fixed it in the same thread.

.. lab-note::

   Search your lab's chat history first, and ask in the lab's public
   support channel rather than in direct messages.
