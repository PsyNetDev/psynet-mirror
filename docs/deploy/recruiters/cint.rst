.. _lab-deployment-cint:

CINT (Lucid)
============

`CINT <https://www.cint.com/>`__ (formerly Lucid) is a survey marketplace
with participants in many countries and languages. PsyNet still calls it
Lucid in code, commands and configuration keys. The CINT account
credentials, ``lucid_api_key`` and ``lucid_sha1_hashing_key``, go in
``~/.dallingerconfig``.

.. lab-note::

   CINT accounts are usually held by the lab. Ask your lab administrator
   for the API credentials and the marketplace login.

Experiment configuration
------------------------

Set ``wage_per_hour`` to the minimum wage in the target country (one
source is
`this spreadsheet <https://docs.google.com/spreadsheets/d/1Yl-eEsLTxFAVyZECZfRQnDlYM8ykY9xlJpnsTpi5oKQ/edit>`__).
Put the duration in the title, plus Chrome, headphones or a microphone if
needed, but not the payment.

.. code:: python

   class Exp(psynet.experiment.Experiment):
       config = {
           **recruiter_settings,
           "initial_recruitment_size": 10,
           "locale": LOCALE,  # ISO 639-1 code of the experiment language, e.g. "tr"
           "auto_recruit": False,
           "wage_per_hour": 6.5,  # minimum wage of the target country
           "publish_experiment": True,
           "title": "Put your experiment title here (Chrome browser, ~XX mins)",
           "contact_email_on_error": "you@example.org",
           "organization_name": "Your institution",
       }

``recruiter_settings`` comes from
:func:`~psynet.recruiters.get_lucid_settings`, which sets the recruiter
and loads the qualification file. It also sets ``currency`` to ``"EUR"``
and ``show_reward`` to ``False``; CINT recruitment fails with
``show_reward = True``. Its parameters:

-  ``lucid_recruitment_config_path``: path to the qualification JSON
   file (see :ref:`lab-deployment-cint-qualifications`).
-  ``termination_time_in_s``: the maximum time a participant can spend
   on the experiment.
-  ``initial_response_within_s``: participants who do not reach the
   consent page within this time are terminated (default 180).
-  ``bid_incidence``: the expected percentage of participants who pass
   the qualifications (default 66). Set it to a realistic value, but as
   high as possible, and adjust it from the CINT reports.
-  ``inactivity_timeout_in_s``: participants who do not click, type, or
   move the mouse for this long are terminated (default 120).
-  ``no_focus_timeout_in_s``: participants who move the mouse outside the
   window or open another tab for this long are terminated (default 60).
   **This applies on all pages**, so choose a realistic value.
-  ``aggressive_no_focus_timeout_in_s``: the same, but used on the
   qualification verification pages (default 3). Verify the
   qualifications on the first page to remove careless participants
   early.
-  ``collects_pii``: whether the survey collects personally identifiable
   information (default ``False``).
-  ``debug_recruiter``: set to ``True`` only for local testing.

.. code:: python

   from psynet.recruiters import get_lucid_settings

   recruiter_settings = get_lucid_settings(
       lucid_recruitment_config_path=LUCID_CONFIG_PATH,
       termination_time_in_s=120 * 60,
       debug_recruiter=False,
       initial_response_within_s=180,
       bid_incidence=66,
       inactivity_timeout_in_s=120,
       no_focus_timeout_in_s=60,
       aggressive_no_focus_timeout_in_s=3,
   )

``get_lucid_settings`` reads the qualification file when ``experiment.py``
is imported, so the file must exist before any local run or test.

Set ``publish_experiment`` in the config as well, because CINT deployment
stops with an error when it is missing. With ``True``, a live deployment sets
the survey live immediately. With ``False``, the survey is created without
going live, so you can check it in the marketplace first.

Consent
^^^^^^^

CINT recruitment requires ``LucidConsent`` as the first consent page,
optionally followed by ``AudiovisualConsent`` or ``OpenScienceConsent``.
Deployment fails with any other combination.

.. _lab-deployment-cint-qualifications:

Qualifications
--------------

Qualifications decide which panel members can take the survey. CINT has a
standard qualification library, and each CINT account can add its own
custom qualifications.

.. lab-note::

   Check your lab's internal deployment documentation for custom
   qualifications available on the lab's CINT account.

Standard CINT qualifications
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Every account has the standard qualifications, for example **HAS_AUDIO**,
which checks that the participant can play audio.

Languages and countries
^^^^^^^^^^^^^^^^^^^^^^^

CINT identifies languages with three capital letters and countries with two.
These are CINT's own codes, not always ISO codes. To list them, run:

.. code:: bash

   psynet lucid locale

Creating qualification files
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each language and country needs a qualification JSON file, which PsyNet
uses at deployment to set up the survey's qualifications. Generate the files
with :func:`~psynet.lucid.qualifications.create_lucid_recruitment_config`,
for example in a script that you adapt:

.. code:: python

   from tqdm import tqdm
   from psynet.lucid.qualifications import create_lucid_recruitment_config

   country_language_tags = (("DUT", "NL"),)

   for language_tag, country_tag in tqdm(country_language_tags):
       config_path = f"qualifications/lucid/lucid-{language_tag}-{country_tag}.json"

       create_lucid_recruitment_config(
           language_tag=language_tag,
           country_tag=country_tag,
           question_answer_dict={
               "HAS_AUDIO": ["Yes"],
           },
           config_path=config_path,
           debug=True,
       )

Generating the file needs the CINT API credentials. The keys of
``question_answer_dict`` must be qualification names on your CINT account;
otherwise ``create_lucid_recruitment_config`` raises ``Unknown question``.
The function also adds some qualifications itself: ``TIMEOUT v1`` with the
answer ``Agree``; mobile and tablet exclusions unless
``allow_mobile_devices`` is set; and a Chrome requirement when
``force_google_chrome`` is set. ``debug=True`` prints the English and
translated text of each qualification.

In ``experiment.py``, point ``get_lucid_settings`` at the file for the
language and country you are recruiting:

.. code:: python

   LANGUAGE = "DUT"  # CINT language code, not the ISO code
   COUNTRY = "NL"  # CINT country code, not always the ISO code
   LOCALE = "nl"  # ISO 639-1 code of the experiment language
   LUCID_CONFIG_PATH = f"qualifications/lucid/lucid-{LANGUAGE}-{COUNTRY}.json"

Confirming qualifications in the experiment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Ask the key qualification questions again at the start of the experiment.
Participants who meet the criteria continue, and those who don't are
terminated before they spend time on the study, which improves data quality.
:func:`~psynet.lucid.qualifications.verify_lucid_qualifications` asks the
qualification questions from the file and ends the experiment for answers the
qualification doesn't allow:

.. code:: python

   import psynet.experiment
   from psynet.consent import LucidConsent
   from psynet.timeline import Timeline
   from psynet.page import SuccessfulEndPage
   from psynet.lucid.qualifications import verify_lucid_qualifications

   LANGUAGE = "DUT"
   COUNTRY = "NL"
   LUCID_CONFIG_PATH = f"qualifications/lucid/lucid-{LANGUAGE}-{COUNTRY}.json"

   class Exp(psynet.experiment.Experiment):
       timeline = Timeline(
           verify_lucid_qualifications(LUCID_CONFIG_PATH),
           LucidConsent(),
           SuccessfulEndPage(),
       )

To ask only some of the questions, pass ``question_names``:

.. code:: python

   verify_lucid_qualifications(
       LUCID_CONFIG_PATH,
       question_names=["HAS_AUDIO"],
   )

After deploying
---------------

After you deploy, log in to the CINT marketplace. Then open the dashboard
link printed in the terminal and open **Recruiter > Lucid**, which links to
the marketplace pages for the survey and shows its reports.

.. image:: /_static/images/running_studies/recruiters/cint/dashboard-lucid-tab.png
   :width: 8.5in

1. **Check the qualifications.** Click **Qualifications** to open the
   survey's qualifications on the marketplace and check that they are set
   correctly.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-qualifications-button.png
      :width: 8.5in

   .. image:: /_static/images/running_studies/recruiters/cint/survey-qualifications.png
      :width: 8.5in

2. **Set the quota.** Click **Quota** to open the survey's quota settings on
   the marketplace.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-quota-button.png
      :width: 8.5in

   CINT counts a quota in one of two ways. With **Completes** (the default),
   the survey fills as respondents complete it. With **Prescreens**, it
   fills as respondents complete the marketplace prescreener. Switching to
   **Prescreens** with a small quota at the start limits how many
   participants arrive at once, which protects the server from overload and
   the experiment from crashing. Under **CALCULATION TYPE**, choose
   **Prescreens** and start with a quota such as 10, then raise it as the
   experiment runs smoothly. Switch back to **Completes** if recruitment
   slows down.

   .. image:: /_static/images/running_studies/recruiters/cint/quota-calculation-type.png
      :width: 8.5in

.. _lab-deployment-cint-monitoring:

Monitoring
----------

The dashboard's **Recruiter > Lucid** page shows the survey's reports.
Participants can't contact you through CINT, so check these reports and the
dashboard's errors regularly.

1. Check how many participants are working, terminated and completed. Check
   the **Termination reasons** too, as they can reveal a problem with the
   experiment.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-status.png
      :width: 8.5in

2. Check the survey metrics. They settle only after the survey has run for
   a while, so early values can be misleading.

   -  **Conversion rate**: the percentage of respondents who complete the
      study after leaving the marketplace prescreener. Aim for more than
      10%. To raise it, build quotas into the marketplace so that
      respondents aren't turned away by quotas in the experiment itself.

   -  **Dropoff rate**: the percentage of respondents who passed the
      qualifications but didn't return to the marketplace. Aim for less
      than 20%. If it is higher, look for setup errors, for example in
      routing or in how images and videos are displayed.

   -  **Incidence rate**: the percentage of respondents expected to qualify
      after qualification targeting. It comes from the ``bid_incidence``
      argument of ``get_lucid_settings`` (default 66). Keep it as high as is
      realistic.

   -  **EPC (earnings per click)**: the gross amount in dollars a supplier
      can expect for each respondent they send to the survey, which shows
      whether the survey is priced well. $0.20 to $0.30 is healthy; below
      $0.15, the survey struggles to attract respondents.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-metrics.png
      :width: 8.5in

3. Check the **Respondents** graph for how many participants enter the
   survey over time. If the number is falling off, adjust the quota.

   .. image:: /_static/images/running_studies/recruiters/cint/respondents-over-time.png
      :width: 8.5in

4. Check participant status on each survey page. Click a bar to see the
   participant IDs and termination reasons. A high termination rate early
   in the survey is normal.

   .. image:: /_static/images/running_studies/recruiters/cint/responses-per-participant.png
      :width: 8.5in

5. Check the completion and termination **LOI** (length of interview). The
   completion LOI should match your time estimate, and the termination LOI
   should be as low as possible. If either is higher than expected, look for
   errors in the experiment.

   .. image:: /_static/images/running_studies/recruiters/cint/length-of-interview.png
      :width: 8.5in

Ending the study
----------------

When you reach the target number of participants, set the survey to
**Complete**, export the data again, and wait until no participants are
still working before destroying the app (see
:doc:`/deploy/running_a_study`).

.. image:: /_static/images/running_studies/recruiters/cint/termination.png
   :width: 8.5in

Reconciling participants
^^^^^^^^^^^^^^^^^^^^^^^^

If participants were terminated for the wrong reason, or the experiment
had errors, reconcile the survey once its status is **Complete**:

.. code:: bash

   psynet lucid compensate SURVEY_NUMBER RID_1 RID_2 […] RID_N

The command marks the listed RIDs as completed and every other participant
as terminated. List every RID that should count as completed, **including
those already marked as completed**.

.. seealso::

   The :doc:`/skills/prepare-for-cint` skill walks through preparing an
   experiment for CINT.
