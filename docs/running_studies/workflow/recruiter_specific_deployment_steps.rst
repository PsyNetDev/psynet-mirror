Recruiter-specific steps
========================

.. _lab-deployment-prolific:

Prolific
--------

Setting up the experiment
~~~~~~~~~~~~~~~~~~~~~~~~~

Experiment costs
^^^^^^^^^^^^^^^^

1. To calculate the base payment for your experiment, set the
   “\ **wage_per_hour**\ ” parameter in the config to 9 Pounds
   (Prolific recommendation).

   .. code:: python

      config = {
          "wage_per_hour": 9,
      }

2. Run psynet estimate in the terminal and note your estimated
   experiment duration and cost. You should include the cost and the
   duration in your experiment’s title. Also, say people need Chrome and
   optionally headphones and microphones if needed.

3. In the ``get_prolific_settings()`` function, specify the duration
   using the ``prolific_estimated_completion_minutes`` parameter and
   the cost using the ``base_payment`` parameter.

   - For example, when you run ``psynet estimate``, you will get a
     result like this:

     .. code:: text

        Estimated maximum reward for participant: EUR4.95.
        Estimated time to complete experiment: 33 min.

   - In this case, the prolific parameters must be as follows:

     .. code:: python

        config = {
            "base_payment": 4.95,
            "prolific_estimated_completion_minutes": 33,
        }

4. Make sure all ``time_estimate`` values are set appropriately so
   that the overall duration from ``psynet estimate`` matches your
   expectation.

5. Check that the experiment costs are right:

   -  Use your own data (and, optionally, pilot data from colleagues) to
      estimate how long it takes for each trial, pre-screeners, and the
      entire experiment

   -  Start running (if possible) a small number of participants
      (e.g., 10) and try to see if your time estimate is wrong by more
      than 30% - redeploy.

   -  If you had run the experiment, update the run time based on
      real data.




Experiment script
^^^^^^^^^^^^^^^^^

In case of assets, make sure you are not using DebugStorage, but
S3Storage or a LocalStorage.

Add config params under class Exp(psynet.experiment.Experiment):

.. code:: python

   config = {
       **get_prolific_settings(),
       "initial_recruitment_size": 5,
       "title": "Put your experiment title here (Chrome browser, ~XX mins)",
       "description": (
           "This is a speaking experiment that needs to be done in a quiet "
           "place WITHOUT headphones. You will be asked to imitate rhythms. "
           "The task will take about 15 minutes."
       ),
       "contact_email_on_error": "<your-lab-contact-email>",
       "organization_name": "<your-institution>",
       "show_reward": False,
   }

An example for title:

“Check recorded texts (Chrome browser, Headphone required, Native
english speakers only; ~10-15 mins)”

Example for description:

“In this experiment you will hear spoken sentences and need to judge the
quality of their transcript. The experiment requires Chrome browser and
Headphones and is intended for Native English speakers. It lasts 10-12
min.”

You may also want to add other config parameters that are optional,
e.g.,

.. code:: python

   "force_incognito_mode": True

Note that we actually recommend force_incognito_mode=True for most
experiments as it makes sure participants actually use incognito. Not
having incognito can generate differences in display if participants are
using browser add-ons. If you don’t care about this display issue you
can set this to False.

This forces people to use an incognito browser, which helps against the
red screen error. For an overview of all options, see the
:doc:`configuration reference </reference/configuration>`.

Then, you will need to add the function get_prolific_settings() to set
up config parameters specifically pertaining to Prolific. Add this
function at the top of your project. Your lab administrator should
provide the Prolific qualification JSON file:

.. code:: python

   import json


   def get_prolific_settings():
       with open("qualification_prolific_en.json", "r") as f:
           qualification = json.dumps(json.load(f))

       return {
           "recruiter": "prolific",
           "base_payment": 4.95,  # based on survey minutes
           "prolific_estimated_completion_minutes": 33,
           "prolific_recruitment_config": qualification,
           "auto_recruit": False,
           "currency": "£",
       }


-  **Make sure your payment is in line with the estimated completion
   time**; Prolific requires a *minimum of £6 per hour*, based on the
   median completion time across participants in your study. You can
   verify your experiment duration by :ref:`having multiple group
   members test out your experiment <testing-within-the-group>` before
   you deploy and checking their median completion time. Keep an eye on
   this while running the experiment with participants!


Prolific qualifications
^^^^^^^^^^^^^^^^^^^^^^^

Add the qualification_prolific_en.json file to your experiment folder
Your lab administrator should provide this file. It currently specifies
qualifications for collecting data from **English speaking participants
in the UK**. This file will also specify important parameters for
Prolific, such as country of recruitment, participant demographics, etc.

-  You can manually modify the exact demographic requirements in
   Prolific (after you deploy, before you publish). Their GUI will also
   tell you the number of active participants who fulfill these
   criteria.

Deployment
~~~~~~~~~~

**IMPORTANT NOTE:** In **PsyNet 11.9.0** or higher you should add
following settings to .dallingerconfig:

[Prolific]

prolific_workspace = <WORKSPACE_YOU_WANT_TO_USE>

prolific_project = <YOUR_PROJECT_FOLDER>

-  Choose workspace that you want to deploy (check account balance)

.. image:: /_static/images/lab_deployments/image16.png
   :width: 8.5in

-  You should create a project folder for your experiments. Please use
   your own name. For example: ``Your Name Experiments``.

.. image:: /_static/images/lab_deployments/image13.png
   :width: 8.5in

Deploy the experiment. Please see
:ref:`Launch the experiment <lab-deployment-actual-deployment>`.

Prolific: check & adapt study details
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Before participants can take part in your experiment, you will have to
confirm some settings on Prolific first. Go to
`prolific.com <https://www.prolific.com/>`__ and log in to your lab's
Prolific account. Your lab administrator should provide you with login
credentials.

In the “Draft” tab of the “Projects” folder you will find your
experiment:

.. image:: /_static/images/lab_deployments/image14.png
   :width: 8.5in

Your deployed experiment will be found as a draft in the prolific_project you specified.

Then click on the name of your experiment. This will lead you to a page
where you can check and adjust some of your experiment parameters. Make
sure that everything is set up the way you intended; especially the
payment parameters! Also check whether the formatting of the description
is as intended.

Here, you should set the internal name to “<your name> -
<keyword/phrase>” (e.g. “your-name - short-experiment-name”). This is not visible to
participants. This will help us identify who each study belongs to,
especially when sorting through messages from participants.

Additionally, on this page, you will need to set the approvement process
to “Approve and pay”, otherwise you have to approve all your
participants manually:|image4|

Prolific: estimate & claim experiment cost
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can get an estimate of the total cost of your experiment by setting
the recruitment size to the total number of participants you are looking
to recruit (plus a few more to be safe, if you have a prescreener) and
scrolling down to the “Study Cost” section and finding the total. This
includes the Prolific service fee. **Check whether there is enough
unclaimed money in the Prolific account. If not, contact the responsible person about
this.**

.. image:: /_static/images/lab_deployments/image52.png
   :width: 8.5in

.. image:: /_static/images/lab_deployments/image58.png
   :width: 8.5in

Prolific: preview
^^^^^^^^^^^^^^^^^

If you want a final test of your experiment through Prolific, you can do
that if you change the participant_id in the url.

Please note that the data is saved in the database. Typically you want
to run the first trials, but not completing the experiment because your
data is saved as a real participant. In some experiments (like a static
experiment) you can then able to filter the data for participants that
did not finish the experiment.

Prolific: publish experiment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When you are happy with all the settings, click on “publish” to put your
experiment online.

Monitoring
~~~~~~~~~~

Recruitment strategy
^^^^^^^^^^^^^^^^^^^^

It is recommended to start with an initial recruitment size of 5-10
people. After all these initial participants have finished the
experiment, you should check that you do not get any errors and that
your initial time estimate for the experiment is accurate. Only then you
can increase the experiment size manually. To do so click on “Action” on
the upper right side of the prolific dashboard and then on “increase
places”.

.. image:: /_static/images/lab_deployments/image35.png
   :width: 8.5in

The number you set here is the additional number of participants you wish to add to your experiment.
For example, if you already have 5 participants and want to recruit 5 more, you should enter 5.
Make sure that you do not have too many participants
taking your experiment at once, because this could overload the server
and cause errors and slow-downs.

At any time, you should check for errors (you get an error report on
each export) and make sure that the median wage per hour (indicated on
the prolific dashboard) does not go under the minimum of £6 per hour.

**Auto-recruit**

Auto-recruit is a functionality in psynet that automatically increases
places in your experiment. You can change this parameter from the
experiment dashboard:

|image5|

The logic is as follows: Whenever someone completes the study, another
spot will be automatically added. I.e., if you have currently 3 people
taking the experiment and turn it on, then there will always be 3 active
participants.

**You have to be really careful when using this.** In case you use it,
make sure to consider following points:

-  Only use it after you collected the first 10 participants, if you did
   not get any complaints from participants, and if you have checked
   whether the exported data looks ok

-  Stop Auto recruit when you get to 90% of the experiment. After which
   you manually recruit the rest. This is a good idea since in some
   experiments participants are still continuously recruited and have
   very little to do. This way they will be fully compensated but
   contribute very little. To avoid this problem toward the end of the
   experiment stopping auto recruit earlier is a good idea.

-  **Really make sure that auto-recruit is off, when stopping the
   experiment. Clicking on “stop” in the prolific dashboard is not
   enough.**

Messages in Prolific
^^^^^^^^^^^^^^^^^^^^

Messages that are specific to your experiment can be seen in the chat
box on the lower right.

It is suggested though, to click on “Messages” on the upper side of the
screen, to see all messages (also messages related to other
experiments).\ |image6|

The reason is that we want to keep our inbox clean and only in this view
can you archive messages. To do so (after you have handled the
participants issue) click on the checkbox of the message and then click
on “archive”.

.. image:: /_static/images/lab_deployments/image32.png
   :width: 8.5in

Answering messages
^^^^^^^^^^^^^^^^^^

Since there can be various reasons why a participant is messaging you,
there is no standard way to answer. Most of the time though, a
participant is messaging you because they have encountered an error in
your experiment. If so, you can look for that participant in the
“participant” tab of your psynet dashboard by pasting their ID from
prolific to the “worker id” field. There you will find a “Link for
resuming session”, which you can send to the participant.

If that does not work or the participant cannot continue the experiment
because of some issue on our side, you should approve them manually. You
can do so by searching for their ID in the prolific dashboard and
clicking on the checkmark. By doing do they will be payed the base
payment you have set in the beginning.

.. image:: /_static/images/lab_deployments/image36.png
   :width: 8.5in

Termination
~~~~~~~~~~~

-  Make sure that there are no participants actively taking the
   experiment

-  Approve/reject people in awaiting review

-  The status of the experiment should be “\ **COMPLETED”**

-  Turn off auto-recruit! Otherwise it will keep recruiting
   participants, even if you stopped the experiment

-  Put experiment in your folder on Prolific.

.. _lab-deployment-cint:

CINT (Lucid)
------------

.. _setting-up-the-experiment-1:

Setting up the experiment
~~~~~~~~~~~~~~~~~~~~~~~~~

.. _experiment-costs-1:

Experiment costs
^^^^^^^^^^^^^^^^

1. Adjust the “\ **wage_per_hour**\ ” parameter in the config according
   to the minimum wage in the targeted country. A list of minimum wages
   per country can be found at this
   `link <https://docs.google.com/spreadsheets/d/1Yl-eEsLTxFAVyZECZfRQnDlYM8ykY9xlJpnsTpi5oKQ/edit#gid=0>`__.

   .. code:: python

      "wage_per_hour": 6.5

2. Make sure all time_estimates are set appropriately such that the
   overall duration of your experiment (you get from psynet estimate)
   matches your expectation.

3. Run psynet estimate in the terminal and note your estimated
   experiment duration and cost. **DO NOT indicate the cost in your
   experiment’s title, only the duration. Also, say people need Chrome
   and optionally headphones and microphones if needed**.

4. Check that the experiment costs are right:

   -  Use your own data (and, optionally, pilot data from colleagues) to
      estimate how long it takes for each trial, pre-screeners, and the
      entire experiment

   -  Start running (if possible) a small number of participants
      (e.g., 10) and try to see if your time estimate is wrong by more
      than 30% - redeploy.

   -  If you had run the experiment, update the run time based on real
      data.

.. _experiment-script-1:

Experiment script
^^^^^^^^^^^^^^^^^

In the case of assets, make sure you are not using DebugStorage, but
S3Storage or a LocalStorage.

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

CINT Recruiter Settings 
^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^

Please ensure that you use the correct consent for the CINT platform. Please advise if you are unsure.

.. _lab-deployment-cint-qualifications:

CINT qualifications
^^^^^^^^^^^^^^^^^^^

Setting qualifications automatically
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


CINT provides a standard qualification library and also supports custom qualifications.
However, custom qualifications are specific to each CINT account and may not be available across deployments.
Check your lab's internal deployment documentation for any account-specific custom qualifications.

Standard CINT qualifications
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These qualifications are available for all accounts. Example:

- **HAS_AUDIO**
  Checks whether participants are able to play audio during the experiment.


-----------------------------------

Working with languages and countries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are a variety of languages and countries available on CINT with
specific tags. You can get a list of all the available language (3
capital letters) and country (2 capital letters) tags by running the
following code in your terminal:

.. code:: bash

   psynet lucid locale

-----------------------------------

Creating qualification configs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

-----------------------------------

Front-end Confirmation of Qualifications
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

-----------------------------------

Summary Steps for Setting CINT Qualifications:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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


.. _deployment-1:

Deployment
~~~~~~~~~~

CINT: check & adjust quota
^^^^^^^^^^^^^^^^^^^^^^^^^^

After you deploy, go to the CINT marketplace sign-in page provided by
your lab administrator and log in to your lab's CINT account. Your lab
administrator should provide you with login credentials.

Also, save and open the link provided in the terminal after successful
deployment to :ref:`monitor <lab-deployment-cint-monitoring>` the
experiment. When you open the link, you will see the dashboard. Here,
click on the ‘Lucid’ tab to access many features from the marketplace as
well as the reports of the experiment.

.. image:: /_static/images/lab_deployments/image34.png
   :width: 8.5in

1. **Checking qualifications:** Here, click the “Qualifications” tab to
   check if the qualifications are set correctly. This will direct you
   to the official marketplace site.

   .. image:: /_static/images/lab_deployments/image30.png
      :width: 8.5in

   .. image:: /_static/images/lab_deployments/image53.png
      :width: 8.5in

2. **Adjusting quota:** To manage the quota settings, go to the ‘Quota’
   tab. This will direct you to the official marketplace site.

   .. image:: /_static/images/lab_deployments/image10.png
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

   .. image:: /_static/images/lab_deployments/image6.png
      :width: 8.5in

.. _lab-deployment-cint-monitoring:

Monitoring 
~~~~~~~~~~~

The new interface under the ‘Lucid’ tab in the dashboard offers a
variety of ways to monitor the experiment.

1. Check how many participants are working, terminated, and completed.
   It is important to inspect ‘Termination reasons’ as it might reveal
   if something is wrong with the experiment.

   .. image:: /_static/images/lab_deployments/image46.png
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

   .. image:: /_static/images/lab_deployments/image49.png
      :width: 8.5in

3. Check how many participants enter the survey overtime on the
   ‘Respondents’ graph. If it is dying out, you may need to adjust the
   quota.

   .. image:: /_static/images/lab_deployments/image11.png
      :width: 8.5in

4. Monitor participant status across survey pages by clicking on bars to
   access participant IDs and termination reasons. It is typical to have
   a high termination rate at the early stage of the experiment.

   .. image:: /_static/images/lab_deployments/image4.png
      :width: 8.5in

5. Check completion LOI and termination LOI. The completion LOI should
   match your time estimate. Termination LOI should be low as much as
   possible. If it is higher than expected you should inspect for
   possible errors in your experiment.

   .. image:: /_static/images/lab_deployments/image56.png
      :width: 8.5in

.. _termination-1:

Termination
~~~~~~~~~~~

Once you reach the desired number of participants, set it to ‘Complete’
and :ref:`export <lab-deployment-export-data>` your data again. To
destroy the app, wait until there are no more working participants left
in the experiment.

.. image:: /_static/images/lab_deployments/image9.png
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

.. _lab-deployment-lab-recruiter:

Lab Recruiter
-------------

The Group Manager (usually the experimenter) is responsible for setting
up and managing participant recruitment through Lab Recruiter. The
system provides full control over participant selection, experiment
access, and tracking.

Registering to the Lab Recruiter platform
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create an admin account
^^^^^^^^^^^^^^^^^^^^^^^

-  For now, please contact your Lab Recruiter administrator to have your admin
   account created in the Lab Recruiter app.

Create a group
^^^^^^^^^^^^^^

-  As the Group Manager, go to the Group tab and click **‘New**
   **Group’** to create a participant group.

.. image:: /_static/images/lab_deployments/image3.png
   :width: 8.5in

Set an initial test
~~~~~~~~~~~~~~~~~~~

-  In your group settings, you can enable an "Initial Test Experiment"
   designed to verify device compatibility—including headphone
   functionality and audio quality. Participants must complete this
   test before accessing any actual experiments, ensuring they meet
   the necessary technical standards. If your experiments have
   additional requirements, please contact us for further assistance.

.. image:: /_static/images/lab_deployments/image38.png
   :width: 8.5in

.. _setting-up-the-experiment-2:

Setting up the experiment
~~~~~~~~~~~~~~~~~~~~~~~~~

.. _experiment-costs-2:

Experiment costs
^^^^^^^^^^^^^^^^

1. We typically pay 15 Euros per hour. So adjust the
   “\ **wage_per_hour**\ ” parameter in the config accordingly.

   .. code:: python

      "wage_per_hour": 15

2. Make sure all time_estimates are set appropriately such that the
   overall duration of your experiment (you get from psynet estimate)
   matches your expectation.

3. Run psynet estimate in the terminal and note your estimated
   experiment duration and cost.

4. Check that the experiment costs are right:

   -  Use your own data (and, optionally, pilot data from colleagues) to
      estimate how long it takes for each trial, pre-screeners, and the
      entire experiment

   -  Start running (if possible) a small number of participants
      (e.g., 10) and try to see if your time estimate is wrong by more
      than 30% - redeploy.

   -  If you had run the experiment, update the run time based on real
      data.

.. _experiment-script-2:

Experiment script
^^^^^^^^^^^^^^^^^

In case of assets, make sure you are not using DebugStorage, but
S3Storage or a LocalStorage.

Add config params under class Exp(psynet.experiment.Experiment) and set
recruiter as 'lab-recruiter':

.. code:: python

   config = {
       "recruiter": "lab-recruiter",
       "initial_recruitment_size": 5,
       "title": "Put your experiment title here (Chrome browser, ~XX mins)",
       "description": (
           "This is a speaking experiment that needs to be done in a quiet "
           "place WITHOUT headphones. You will be asked to imitate rhythms. "
           "The task will take about 15 minutes."
       ),
       "contact_email_on_error": "<your-lab-contact-email>",
       "organization_name": "<your-institution>",
       "show_reward": False,
   }

An example for title:

“Check recorded texts (Chrome browser, Headphone required, ~10-15 mins)”

Example for description:

“In this experiment you will hear spoken sentences and need to judge the
quality of their transcript. The experiment requires Chrome browser and
Headphones and is intended for Native English speakers. It lasts 10-12
min.”

Consent
^^^^^^^

You can choose the consent while creating the group. Contact your lab
administrator if you want to create or use a custom consent form.

.. image:: /_static/images/lab_deployments/image1.png
   :width: 8.5in

.. _deployment-2:

Deployment
~~~~~~~~~~

Deploy the experiment. Please see
:ref:`Launch the experiment <lab-deployment-actual-deployment>`.

-  After deploying your experiment, navigate to the Experiments tab.

-  Click **‘New Experiment’** to add your experiment to the Lab Recruiter.

.. image:: /_static/images/lab_deployments/image28.png
   :width: 8.5in

-  Here please set the required parameters.

   -  **Estimated Duration:** This is the predicted duration of the
      experiment.

   -  **Maximum Duration:** This is the total time participants are
      allowed to remain in the experiment before being timed out.

   -  **Batches:** This specifies the number of times each participant
      can take part.

   -  **URL:** This is the link provided on the console after deployment
      (e.g., ``https://<app-name>.<your-server-hostname>``)

-  At the bottom of the page move your Group from “Available groups” up
   into the **‘Groups’** section to make the experiment accessible to
   all participants in that group.

.. image:: /_static/images/lab_deployments/image48.png
   :width: 8.5in

-  You can also later edit it by click **‘Edit’** on your experiment.

.. image:: /_static/images/lab_deployments/image27.png
   :width: 8.5in

Inviting participants
~~~~~~~~~~~~~~~~~~~~~

Invite participants
^^^^^^^^^^^^^^^^^^^

-  Once the setup is complete, go to the Groups tab.

-  Click ‘\ **Copy Invitation Link**\ ’ for your group.

-  Send this link to participants via email.

-  Participants registering with this link will automatically use the
   Group Manager code for your group.

.. image:: /_static/images/lab_deployments/image18.png
   :width: 8.5in

Send messages
^^^^^^^^^^^^^^

-  Using the messages option, you can send emails to participants in
   each group. Simply compose your message—such as informing them
   about a new study—and choose whether to send it to all
   participants or only specific individuals from the recipients
   list. The message is then sent from the Lab Recruiter official
   email account to the selected group.

.. image:: /_static/images/lab_deployments/image21.png
   :width: 8.5in

Monitor and manage participants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Dashboard
^^^^^^^^^

Use your experiment dashboard to monitor your experiment. See
:ref:`dashboard <lab-deployment-dashboard>`.

Participant tracking
^^^^^^^^^^^^^^^^^^^^

-  Track participant progress in the Participants tab (experiments
   taken, payment status, etc.).

.. image:: /_static/images/lab_deployments/image20.png
   :width: 8.5in

Managing experiment tasks
^^^^^^^^^^^^^^^^^^^^^^^^^

-  Reset failed experiments by navigating to ‘Tasks’ and clicking the
   **‘Reset’** button.

.. image:: /_static/images/lab_deployments/image39.png
   :width: 8.5in

.. _termination-2:

Termination
~~~~~~~~~~~

Experiment completion
^^^^^^^^^^^^^^^^^^^^^

-  Upon completion or failure, experiment status, time tracking, and
   payment records are updated. Payments are processed externally by
   the lab team so please **DO NOT** press the ‘\ **Payment Done**\ ’
   button for the completed participants.

Terminate the experiment
^^^^^^^^^^^^^^^^^^^^^^^^

-  Once you reach the desired number of participants, export your data
   again and set it to **‘Archive’** on the Lab Recruiter.

-  You also need to delete the experiment from the server. Please see
   :doc:`teardown <teardown>`.

Lab Recruiter for participants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Sign up and verification

   -  Sign up to Lab Recruiter using the unique Group Manager code
      received via email.

   -  Verify your email to activate your account.

2. Accessing experiments

   -  Through the Lab Recruiter interface, participants can:

      -  View available experiments.

      -  Access experiment details and links.

      -  Track their payment status.

.. image:: /_static/images/lab_deployments/image54.png
   :width: 8.5in

3. Initial Test Experiment

   -  Participants complete an initial test experiment to verify device
      compatibility:

      -  Successful participants gain access to real experiments.

      -  Unsuccessful participants can retry the test if the experiment
         resets their attempt.

4. Experiment Participation

   -  Once eligible, participants can take available experiments from
      the Lab Recruiter platform.

5. Completion & Payment

   -  Experiment status is updated automatically, and payment is
      processed externally by the lab team regularly every two weeks.

.. |image4| image:: /_static/images/lab_deployments/image33.png
   :width: 8.5in
.. |image5| image:: /_static/images/lab_deployments/image5.png
   :width: 8.5in
.. |image6| image:: /_static/images/lab_deployments/image45.png
   :width: 8.5in
