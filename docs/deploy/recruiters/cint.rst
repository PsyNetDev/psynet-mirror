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

CINT provides a standard qualification library and also supports custom qualifications.
Custom qualifications are specific to each CINT account.

.. lab-note::

   Check your lab's internal deployment documentation for custom
   qualifications available on the lab's CINT account.

Standard CINT qualifications
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These qualifications are available for all accounts. Example:

- **HAS_AUDIO**
  Checks whether participants are able to play audio during the experiment.


Working with languages and countries
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are a variety of languages and countries available on CINT with
specific tags. You can get a list of all the available language (3
capital letters) and country (2 capital letters) tags by running the
following code in your terminal:

.. code:: bash

   psynet lucid locale

Creating qualification configs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

After getting the desired locales, you can generate qualifications
specific to each country by using a custom code.

This step will create a JSON file, which is necessary during deployment
for setting up CINT qualifications for your experiment.

Please find an example code below that you can adjust and create a qualifications JSON file:

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
otherwise ``create_lucid_recruitment_config`` raises ``Unknown question``. It also adds some qualifications itself:
``TIMEOUT v1`` with the answer ``Agree``; mobile and tablet exclusions unless
``allow_mobile_devices`` is set; and a Chrome requirement when
``force_google_chrome`` is set.

You need to specify the language, country, and the path
to the generated JSON configuration. This path is then used in
``experiment.py`` to load the correct qualification setup during runtime.

Please find an example below that should be added to your
``experiment.py``:

.. code:: python

   LANGUAGE = "DUT"
   COUNTRY = "NL"
   LUCID_CONFIG_PATH = f"qualifications/lucid/lucid-{LANGUAGE}-{COUNTRY}.json"

Front-end confirmation of qualifications
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is recommended to confirm key qualifications in the experiment frontend.

Reasons:
-  Reduces early participant drop-off due to qualification issues
-  Ensures participants meet required criteria
-  Improves data quality and reduces invalid completions

Example implementation:

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

You can optionally restrict which qualifications are shown:

.. code:: python

   verify_lucid_qualifications(
       LUCID_CONFIG_PATH,
       question_names=["HAS_AUDIO"],
   )

Summary of CINT qualification steps
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. Use ``psynet lucid locale`` to retrieve available language/country
   tags.
2. Create a JSON qualification file that, for example, includes the
   ``HAS_AUDIO`` qualification.
3. Be sure that you have added the following parameters to your
   experiment.py:

   .. code:: python

      LANGUAGE = "DUT"  # lucid language code, not ISO language code
      COUNTRY = "NL"  # lucid country code, not always ISO country code
      LOCALE = "nl"  # ISO-2 code for experiment language
      LUCID_CONFIG_PATH = f"qualifications/lucid/lucid-{LANGUAGE}-{COUNTRY}.json"

4. Implement front-end verification for participant validation if
   necessary.


After deploying
---------------

After you deploy, log in to the CINT marketplace. Then open the dashboard
link printed in the terminal and open **Recruiter > Lucid**, which links to
the marketplace pages for the survey and shows its reports.

.. image:: /_static/images/running_studies/recruiters/cint/dashboard-lucid-tab.png
   :width: 8.5in

1. **Checking qualifications:** Here, click the “Qualifications” tab to
   check if the qualifications are set correctly. This will direct you
   to the official marketplace site.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-qualifications-button.png
      :width: 8.5in

   .. image:: /_static/images/running_studies/recruiters/cint/survey-qualifications.png
      :width: 8.5in

2. **Adjusting quota:** To manage the quota settings, go to the ‘Quota’
   tab. This will direct you to the official marketplace site.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-quota-button.png
      :width: 8.5in

   There are two types of calculations in CINT: completed and
   prescreens. Completes are when a survey fills based on respondents
   that complete the survey. Prescreens are when a survey fills based on
   respondents that complete the Marketplace prescreener. By default,
   deployments are set to 'Completes.' However, it's advisable to
   consider switching to 'Prescreens' and setting a quota at the outset
   of your experiment. This proactive measure helps prevent server
   overload, especially during periods of high participant influx, which
   could otherwise lead to experiment crashes. To implement this,
   navigate to the 'CALCULATION TYPE' and switch to 'Prescreens.' Begin
   by setting a modest quota, such as 10, then gradually adjust it based
   on experiment progression and participant traffic. You can change it
   back to ‘Completes’ if the experiment pace slows down.

   .. image:: /_static/images/running_studies/recruiters/cint/quota-calculation-type.png
      :width: 8.5in

.. _lab-deployment-cint-monitoring:

Monitoring
----------

The dashboard's **Recruiter > Lucid** page offers a variety of ways to
monitor the experiment. Participants cannot contact you through CINT, so
check these reports and the dashboard's errors regularly.

1. Check how many participants are working, terminated, and completed.
   It is important to inspect ‘Termination reasons’ as it might reveal
   if something is wrong with the experiment.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-status.png
      :width: 8.5in

2. Check the vital metrics of the experiment. Note that they are usually
   not optimized at the beginning of the experiment so you need to wait
   a little to see the realistic results:

   -  **Conversion rate** gives the percentage of respondents who
      complete the study after exiting the Marketplace prescreener. To
      increase the conversion rate you can build quotas into the
      Marketplace to avoid client side over quotas. It should be higher
      than 10%.

   -  **Dropoff rate** gives the percentage of respondents who passed
      the qualifications but did not return to the Marketplace. This
      should be less than 20%. If this is high you should look for
      possible setup errors i.e. routing, images/videos are displayed
      correctly

   -  **Incidence rate** gives the percentage of respondents that will
      qualify for the study after qualification targeting. It is set to
      66% by default on psynet lucid setting. You should aim for as high
      a number as possible. However, you can change it to a lower value
      if necessary. Use the bid_incidence parameter in the
      get_lucid_settings() to change it.

   -  **EPC (Earnings Per Click)** measures the gross dollar amount a
      supplier can expect for each respondent they send into a survey,
      indicating whether the survey is appropriately priced. EPCs of
      $0.20 - $0.30 are considered healthy, whereas EPCs below $0.15
      will struggle to attract supplier traffic.

   .. image:: /_static/images/running_studies/recruiters/cint/dashboard-metrics.png
      :width: 8.5in

3. Check how many participants enter the survey overtime on the
   ‘Respondents’ graph. If it is dying out, you may need to adjust the
   quota.

   .. image:: /_static/images/running_studies/recruiters/cint/respondents-over-time.png
      :width: 8.5in

4. Monitor participant status across survey pages by clicking on bars to
   access participant IDs and termination reasons. It is typical to have
   a high termination rate at the early stage of the experiment.

   .. image:: /_static/images/running_studies/recruiters/cint/responses-per-participant.png
      :width: 8.5in

5. Check completion LOI and termination LOI. The completion LOI should
   match your time estimate. Termination LOI should be low as much as
   possible. If it is higher than expected you should inspect for
   possible errors in your experiment.

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

If people are terminated for the wrong reasons or errors occurred in the
experiment, you need to reconcile your survey. Your survey must have the
status completed.

You can compensate with the following command:

.. code:: bash

   psynet lucid compensate SURVEY_NUMBER RID_1 RID_2 […] RID_N

You need to add all completed RIDs, **so also those that are already
marked as completed! Otherwise, already completed participants are
marked as terminated!**
