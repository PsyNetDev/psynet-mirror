.. _lab-deployment-lab-recruiter:

Lab Recruiter
=============

The Group Manager (usually the experimenter) is responsible for setting
up and managing participant recruitment through Lab Recruiter. The
system provides full control over participant selection, experiment
access, and tracking.

Registering to the Lab Recruiter platform
-----------------------------------------

Create an admin account
~~~~~~~~~~~~~~~~~~~~~~~

-  For now, please contact your Lab Recruiter administrator to have your admin
   account created in the Lab Recruiter app.

Create a group
~~~~~~~~~~~~~~

-  As the Group Manager, go to the Group tab and click **‘New**
   **Group’** to create a participant group.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/create-a-group.png
   :width: 8.5in

Set an initial test
-------------------

-  In your group settings, you can enable an "Initial Test Experiment"
   designed to verify device compatibility—including headphone
   functionality and audio quality. Participants must complete this
   test before accessing any actual experiments, ensuring they meet
   the necessary technical standards. If your experiments have
   additional requirements, contact your Lab Recruiter administrator.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/set-an-initial-test.png
   :width: 8.5in

Setting up the experiment
-------------------------

Experiment costs
~~~~~~~~~~~~~~~~

1. Set the “\ **wage_per_hour**\ ” parameter in the config according
   to your lab's payment policy.

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

Experiment script
~~~~~~~~~~~~~~~~~

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
~~~~~~~

You can choose the consent while creating the group. Contact your lab
administrator if you want to create or use a custom consent form.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/consent.png
   :width: 8.5in

Deployment
----------

Deploy the experiment. Please see
:ref:`Launch the experiment <lab-deployment-actual-deployment>`.

-  After deploying your experiment, navigate to the Experiments tab.

-  Click **‘New Experiment’** to add your experiment to the Lab Recruiter.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/new-experiment.png
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

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/assign-groups.png
   :width: 8.5in

-  You can also later edit it by click **‘Edit’** on your experiment.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/edit-experiment.png
   :width: 8.5in

Inviting participants
---------------------

Invite participants
~~~~~~~~~~~~~~~~~~~

-  Once the setup is complete, go to the Groups tab.

-  Click ‘\ **Copy Invitation Link**\ ’ for your group.

-  Send this link to participants via email.

-  Participants registering with this link will automatically use the
   Group Manager code for your group.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/invite-participants.png
   :width: 8.5in

Send messages
~~~~~~~~~~~~~

-  Using the messages option, you can send emails to participants in
   each group. Simply compose your message—such as informing them
   about a new study—and choose whether to send it to all
   participants or only specific individuals from the recipients
   list. The message is then sent from the Lab Recruiter official
   email account to the selected group.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/send-messages.png
   :width: 8.5in

Monitor and manage participants
-------------------------------

Dashboard
~~~~~~~~~

Use your experiment dashboard to monitor your experiment. See
:ref:`dashboard <lab-deployment-dashboard>`.

Participant tracking
~~~~~~~~~~~~~~~~~~~~

-  Track participant progress in the Participants tab (experiments
   taken, payment status, etc.).

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/participant-tracking.png
   :width: 8.5in

Managing experiment tasks
~~~~~~~~~~~~~~~~~~~~~~~~~

-  Reset failed experiments by navigating to ‘Tasks’ and clicking the
   **‘Reset’** button.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/managing-experiment-tasks.png
   :width: 8.5in

Termination
-----------

Experiment completion
~~~~~~~~~~~~~~~~~~~~~

-  Upon completion or failure, experiment status, time tracking, and
   payment records are updated. If your lab processes payments outside
   Lab Recruiter, do **not** press the ‘\ **Payment Done**\ ’ button for
   completed participants; follow your lab's payment procedure instead.

Terminate the experiment
~~~~~~~~~~~~~~~~~~~~~~~~

-  Once you reach the desired number of participants, export your data
   again and set it to **‘Archive’** on the Lab Recruiter.

-  You also need to delete the experiment from the server. Please see
   :doc:`teardown <../teardown>`.

Lab Recruiter for participants
------------------------------

1. Sign up and verification

   -  Sign up to Lab Recruiter using the unique Group Manager code
      received via email.

   -  Verify your email to activate your account.

2. Accessing experiments

   -  Through the Lab Recruiter interface, participants can:

      -  View available experiments.

      -  Access experiment details and links.

      -  Track their payment status.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/lab-recruiter-for-participants.png
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

   -  Experiment status is updated automatically; payment follows the
      lab's payment schedule.
