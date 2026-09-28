.. _lab-deployment-prolific:

Prolific
========

`Prolific <https://www.prolific.com/>`__ is a paid service that sources
online participants for research studies. PsyNet creates a study on
Prolific when you deploy, pays participants through it, and completes
their submissions automatically. Prolific has no sandbox mode; pilot with
the ``generic`` recruiter instead (see :doc:`/deploy/running_a_study`).

Account and credentials
-----------------------

Create an account on the `Prolific website <https://www.prolific.com/>`__
and add funds. Then create an API token: in Prolific, open
**Settings**, and under **Developer tools** click **Go to API token
page**. Add the token, the workspace, and the project to
``~/.dallingerconfig``:

.. code-block:: ini

   [Prolific]
   prolific_api_token = xxxxxxx
   prolific_workspace = your-workspace
   prolific_project = your-project

The workspace must exist already. Create the project in the Prolific
interface if it does not exist.

.. lab-note::

   A lab usually shares one Prolific workspace. Ask the administrator which
   workspace to use and check its balance. Create a project named after
   you, for example ``Your Name Experiments``, so lab members can tell whose
   studies are whose.

   .. image:: /_static/images/running_studies/recruiters/prolific/choose-workspace.png
      :width: 8.5in
      :alt: Choosing a Prolific workspace

   .. image:: /_static/images/running_studies/recruiters/prolific/new-project.png
      :width: 8.5in
      :alt: Creating a Prolific project

Experiment configuration
------------------------

Set these keys in ``config.txt`` (or on the ``Experiment`` class; see
:doc:`/reference/configuration`):

.. code-block:: ini

   [Prolific]
   recruiter = prolific
   currency = £
   wage_per_hour = 9
   base_payment = 4.95
   prolific_estimated_completion_minutes = 33
   prolific_screen_out_slots = 100
   auto_recruit = false

- ``currency``: Prolific normally pays in British pounds. Contact Prolific
  support for other currencies.
- ``wage_per_hour``: in the same currency. At the time of writing (August
  2025), Prolific's minimum is £6.00/hour and its recommendation is at
  least £9.00/hour. Prolific checks the wage against the median completion
  time of your participants while the study runs.
- ``base_payment`` and ``prolific_estimated_completion_minutes``: copy
  them from ``psynet estimate`` (see
  :doc:`/deploy/running_a_study`). Prolific checks that they combine to an
  acceptable hourly wage.
- ``prolific_screen_out_slots``: required while
  ``prolific_pay_unsuccessful`` is true (the default); deployment fails
  without it. It caps automatic screen-out spending; a common choice is
  10 times ``initial_recruitment_size``.
- ``auto_recruit``: ``false`` means you add places on Prolific yourself.

Put the duration and the hourly wage in the study title, for example
"Organ chords experiment (headphones required, Chrome browser, 30
minutes, £10/hour payment)". General title guidance is in
:doc:`/deploy/running_a_study`.

Configuring from ``experiment.py``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some labs keep the Prolific settings in a helper function at the top of
``experiment.py``. ``get_prolific_settings()`` is not part of PsyNet; you
write it yourself:

.. code:: python

   import json

   import psynet.experiment


   def get_prolific_settings():
       with open("qualification_prolific_en.json", "r") as f:
           qualification = json.dumps(json.load(f))

       return {
           "recruiter": "prolific",
           "currency": "£",
           "wage_per_hour": 9,
           "base_payment": 4.95,
           "prolific_estimated_completion_minutes": 33,
           "prolific_recruitment_config": qualification,
           # Required while prolific_pay_unsuccessful is true (the default).
           "prolific_screen_out_slots": 50,
           "auto_recruit": False,
       }


   class Exp(psynet.experiment.Experiment):
       config = {
           **get_prolific_settings(),
           "initial_recruitment_size": 5,
           "title": "Imitate rhythms (Chrome browser, ~15 mins, £9/hour)",
           "description": (
               "This is a speaking experiment that needs to be done in a quiet "
               "place WITHOUT headphones. You will be asked to imitate rhythms. "
               "The task will take about 15 minutes."
           ),
           "contact_email_on_error": "you@example.org",
           "organization_name": "Your institution",
           "show_reward": False,
           "force_incognito_mode": True,
       }

``force_incognito_mode = True`` reduces display differences caused by
browser add-ons and helps against the red-screen error; it suits most
experiments.

How PsyNet pays participants
----------------------------

**Successful participants.** When a participant reaches a
:class:`~psynet.page.SuccessfulEndPage` and clicks **Submit to
Prolific**, PsyNet completes the submission on Prolific with an
auto-approve completion code, so Prolific approves it and pays
``base_payment``. Participants see a confirmation page and do not enter a
completion code. PsyNet then compares the reward the participant earned
(from page time estimates and any performance bonuses) with
``base_payment``:

- If the earned reward is at most ``base_payment``, no bonus is paid; the
  participant still receives the full ``base_payment``.
- If it is higher, PsyNet pays the difference as a Prolific bonus.

Set ``base_payment`` close to the reward expected for a successful
completion.

**Unsuccessful participants.** Participants who reach an
:class:`~psynet.page.UnsuccessfulEndPage` (for example after failing a
pre-screening task), confirm **Leave** from the timeline footer or error
page (with ``show_early_exit_button``), or hit an error page, are marked
as failed. By default (``prolific_pay_unsuccessful = true``) PsyNet
registers an extra completion code with a fixed screen-out payment
(``prolific_unsuccessful_base_payment``). When the participant clicks
**Submit to Prolific**, PsyNet completes the submission with that code,
Prolific pays the fixed amount, and PsyNet tops the participant up to the
reward they had earned with a bonus. Prolific discourages giving many
participants partial payments, so keep this path for genuine screen-outs
and errors.

Screen-out payments rely on a Prolific feature that Prolific enables only
for selected workspaces. Without it, study creation fails and PsyNet logs
a hint to set ``prolific_pay_unsuccessful = false``.

With ``prolific_pay_unsuccessful = false``, PsyNet uses the older flow.
If ``prolific_enable_return_for_bonus`` is true (the default), PsyNet asks
the participant to return the submission on Prolific, checks through the
Prolific API that they have done so, and then pays the earned reward as a
bonus. If it is false, PsyNet asks them to return the submission and
contact you, and you pay them by hand.

**Payment review.** If PsyNet cannot confirm a bonus payment, it lists the
participant under **Needs payment review** on the dashboard's Participants
tab, where you can pay or dismiss the bonus.

To customize these behaviors, subclass
:class:`~psynet.end.SuccessfulEndLogic` or
:class:`~psynet.end.UnsuccessfulEndLogic`. For custom completion-code
routing, override
:meth:`~psynet.experiment.Experiment.recruiter_exit_info` and register
extra codes with the ``prolific_completion_config`` configuration key.

Qualifications
--------------

Qualifications (Prolific's filters) decide which participants can see the
study: country, language and other demographics. You can edit them in the
draft study after deploying, or supply them as a JSON file:

.. code-block:: ini

   [Prolific]
   prolific_recruitment_config = file:prolific_config.json

To reuse the filters of an existing study, set them in the Prolific
interface (a draft study is enough), then list your studies:

.. code:: bash

   dallinger hits --recruiter prolific

.. code-block:: text

   ❯❯ Found 23 hit[s]:
   Hit ID                    Title                                        Annotation (experiment ID)   Status           ...
   ------------------------  -------------------------------------------  ---------------------------  ---------------  ...
   63cd3c0de6a9e2d84d694454  Testen Sie Ihre Sprachkenntnisse! (Chrom...  ...                          AWAITING REVIEW  ...

Copy the ``Hit ID`` and export its filters:

.. code:: bash

   dallinger copy-qualifications --hit_id <HIT_ID> --recruiter prolific

This writes ``prolific_config.json``. Use ``--path`` to choose another
file, for example ``--path qualification_prolific_de.json`` for German
participants.

.. lab-note::

   Your lab administrator may provide a standard qualification file to
   start from.

The draft study
---------------

``psynet deploy ssh`` creates the study as a draft in your project,
filling in the title, description, reward, completion time, completion
codes, and qualifications. With ``publish_experiment = true`` it publishes
the study straight away. What to check in the draft is in
:doc:`/deploy/running_a_study`.

Messages
--------

The chat box on the study page shows messages about that study. The
**Messages** page at the top of Prolific shows messages for all studies
and is the only view where you can archive them.

.. image:: /_static/images/running_studies/recruiters/prolific/messages-inbox.png
   :width: 8.5in
   :alt: Prolific messages inbox

With Slack notifications set up, PsyNet forwards new messages about the
study to Slack. How to handle participants who report problems is in
:doc:`/deploy/running_a_study`.

.. lab-note::

   In a shared inbox, archive each message once you have dealt with it:
   tick its checkbox on the Messages page and click **Archive**.

   .. image:: /_static/images/running_studies/recruiters/prolific/messages-in-prolific.png
      :width: 8.5in
      :alt: Archiving a Prolific message

Ending the study
----------------

PsyNet never closes a Prolific study; stop it from the study page on
Prolific. Each deployment creates a
new Prolific study, so use Prolific's filters to exclude participants of
earlier deployments when you redeploy.
