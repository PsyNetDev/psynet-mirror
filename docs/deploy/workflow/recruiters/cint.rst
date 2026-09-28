.. _lab-deployment-cint:

CINT (Lucid)
============

Setting up the experiment
-------------------------

Complete the shared checks on
:doc:`../setting_up_the_experiments` first. For CINT, set
``wage_per_hour`` to the minimum wage in the target country. A list of
minimum wages per country is available in
`this spreadsheet <https://docs.google.com/spreadsheets/d/1Yl-eEsLTxFAVyZECZfRQnDlYM8ykY9xlJpnsTpi5oKQ/edit#gid=0>`__.

.. code:: python

   "wage_per_hour": 6.5

**Do not put the cost in the experiment title**, only the duration
(plus Chrome, headphones, or a microphone if needed).

Experiment script
~~~~~~~~~~~~~~~~~

.. code:: python

   class Exp(psynet.experiment.Experiment):
       config = {
           **recruiter_settings,
           "initial_recruitment_size": 10,  # set to required numbers
           "language": LOCALE,  # set to the ISO-2 language code (e.g. 'tr' or 'en')
           "auto_recruit": False,
           "wage_per_hour": 6.5,  # set to minimum wage of target country
           "title": "Put your experiment title here (Chrome browser, ~XX mins)",
           "contact_email_on_error": "<your-lab-contact-email>",
           "organization_name": "<your-institution>",
       }

CINT recruiter settings
~~~~~~~~~~~~~~~~~~~~~~~

You will need to define recruiter_settings and add the function
get_lucid_settings() to set up config parameters specifically on CINT.
Add this function at the top of your project.

Set the following parameters:

-  lucid_recruitment_config_path: path to qualifications JSON
   file. (see :ref:`CINT Qualifications
   <lab-deployment-cint-qualifications>` for details)

-  termination_time_in_s: adjust the maximal time a participant
   can spend on the experiment

-  debug_recruiter: Only set it to ‘True’ during local testing

-  initial_response_within_s: Termination of the participant if
   the first response is not reached within that time.

-  bid_incidence: You can adjust the incidence rate here
   according to your experiment’s reports on lucid. Set it to a
   realistic value, but as high as possible.

-  inactivity_timeout_in_s: The inactivity (i.e., no clicking,
   no typing, no scrolling or moving the mouse) timeout in seconds.
   Adjust it according to your experiment design.

-  no_focus_timeout_in_s: Termination of the participant in case
   of moving the mouse outside the window or opening another tab. **This
   is active on all pages! Set it to a realistic value.**

-  aggressive_no_focus_timeout_in_s: The same setting as
   \`no_focus_timeout_in_s\`, but only used on the qualification
   verification pages. **It is important to verify the qualifications on
   the very first page to kick out sloppy participants.**

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

CINT consent
~~~~~~~~~~~~

Use the consent page required for CINT (for example ``LucidConsent``).
Ask your lab administrator if you are unsure which consent to use.

.. _lab-deployment-cint-qualifications:

CINT qualifications
~~~~~~~~~~~~~~~~~~~

Setting qualifications automatically
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


CINT provides a standard qualification library and also supports custom qualifications.
However, custom qualifications are specific to each CINT account and may not be available across deployments.
Check your lab's internal deployment documentation for any account-specific custom qualifications.

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


Deployment
----------

CINT: check & adjust quota
~~~~~~~~~~~~~~~~~~~~~~~~~~

After you deploy, go to the CINT marketplace sign-in page provided by
your lab administrator and log in to your lab's CINT account. Your lab
administrator should provide you with login credentials.

Also, save and open the link provided in the terminal after successful
deployment to :ref:`monitor <lab-deployment-cint-monitoring>` the
experiment. When you open the link, you will see the dashboard. Here,
click on the ‘Lucid’ tab to access many features from the marketplace as
well as the reports of the experiment.

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

The new interface under the ‘Lucid’ tab in the dashboard offers a
variety of ways to monitor the experiment.

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
      will struggle to attract supplier traffic. Find more information
      `here <https://support.lucidhq.com/s/article/EPC-FAQ>`__.

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

Termination
-----------

Once you reach the desired number of participants, set it to ‘Complete’
and :ref:`export <lab-deployment-export-data>` your data again. To
destroy the app, wait until there are no more working participants left
in the experiment.

.. image:: /_static/images/running_studies/recruiters/cint/termination.png
   :width: 8.5in

Reconciling participants
~~~~~~~~~~~~~~~~~~~~~~~~

If people are terminated for the wrong reasons or errors occurred in the
experiment, you need to reconcile your survey. Your survey must have the
status completed.

You can compensate with the following command:

.. code:: bash

   psynet lucid compensate SURVEY_NUMBER RID_1 RID_2 […] RID_N

You need to add all completed RIDs, **so also those that are already
marked as completed! Otherwise, already completed participants are
marked as terminated!**
