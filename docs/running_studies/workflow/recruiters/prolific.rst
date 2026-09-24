.. _lab-deployment-prolific:

Prolific
========

Setting up the experiment
-------------------------

Complete the shared checks on
:doc:`../setting_up_the_experiments` first. For Prolific, set
``wage_per_hour`` to Prolific's current recommended rate (commonly
£9), and put both the duration and the wage in the study title.

Copy the ``psynet estimate`` figures into ``get_prolific_settings()``.
If estimate reports ``£4.95`` and ``33 min``, use:

.. code:: python

   config = {
       "wage_per_hour": 9,
       "base_payment": 4.95,
       "prolific_estimated_completion_minutes": 33,
   }

How PsyNet turns those values into Prolific approvals, bonuses, and
screen-out payments is explained in
:doc:`/getting_started/collecting_data`.

Experiment script
~~~~~~~~~~~~~~~~~

Add config params under ``class Exp(psynet.experiment.Experiment)``:

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
       "force_incognito_mode": True,
   }

``force_incognito_mode=True`` is recommended for most experiments: it
reduces display differences from browser add-ons and helps against the
red-screen error. Set it to ``False`` if you do not need that. For all
options, see the :doc:`configuration reference </reference/configuration>`.

Add ``get_prolific_settings()`` at the top of the experiment module.
Your lab administrator should provide the Prolific qualification JSON
file:

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
   time**; Prolific enforces a minimum hourly rate (check Prolific's
   current researcher guidance), based on the median completion time
   across participants in your study. You can
   verify your experiment duration by :ref:`having colleagues test your
   experiment <testing-within-the-group>` before
   you deploy and checking their median completion time. Keep an eye on
   this while running the experiment with participants!


Prolific qualifications
~~~~~~~~~~~~~~~~~~~~~~~

Add a Prolific qualification JSON file (``qualification_prolific_en.json``
in the example above) to your experiment folder. It specifies which
participants Prolific should recruit, such as country of recruitment,
language, and other demographics. Your lab administrator may provide a
standard file to start from.

-  You can manually modify the exact demographic requirements in
   Prolific (after you deploy, before you publish). Their GUI will also
   tell you the number of active participants who fulfill these
   criteria.

Deployment
----------

Add the Prolific workspace and project to your ``~/.dallingerconfig``:

.. code:: ini

   [Prolific]
   prolific_workspace = <WORKSPACE_YOU_WANT_TO_USE>
   prolific_project = <YOUR_PROJECT_FOLDER>

-  Choose the workspace that you want to deploy to (check its account
   balance).

.. image:: /_static/images/running_studies/recruiters/prolific/choose-workspace.png
   :width: 8.5in

-  Create a project folder for your experiments. In a shared workspace,
   include your name, for example ``Your Name Experiments``.

.. image:: /_static/images/running_studies/recruiters/prolific/new-project.png
   :width: 8.5in

Deploy the experiment. Please see
:ref:`Launch the experiment <lab-deployment-actual-deployment>`.

Prolific: check & adapt study details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before participants can take part in your experiment, you will have to
confirm some settings on Prolific first. Go to
`prolific.com <https://www.prolific.com/>`__ and log in to your lab's
Prolific account. Your lab administrator should provide you with login
credentials.

In the “Draft” tab of the “Projects” folder you will find your
experiment:

.. image:: /_static/images/running_studies/recruiters/prolific/check-adapt-study-details.png
   :width: 8.5in

Your deployed experiment will be found as a draft in the prolific_project you specified.

Then click on the name of your experiment. This will lead you to a page
where you can check and adjust some of your experiment parameters. Make
sure that everything is set up the way you intended; especially the
payment parameters! Also check whether the formatting of the description
is as intended.

If your lab shares a Prolific account, set the internal name to
“<your name> - <keyword/phrase>” (e.g. “your-name - short-experiment-name”).
This is not visible to participants, but it helps lab members see who
each study belongs to, especially when sorting through messages from
participants.

Additionally, on this page, you will need to set the approvement process
to “Approve and pay”, otherwise you have to approve all your
participants manually:

.. image:: /_static/images/running_studies/recruiters/prolific/approve-and-pay.png
   :width: 8.5in

Prolific: estimate & claim experiment cost
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can get an estimate of the total cost of your experiment by setting
the recruitment size to the total number of participants you are looking
to recruit (plus a few more to be safe, if you have a prescreener) and
scrolling down to the “Study Cost” section and finding the total. This
includes the Prolific service fee. **Check whether there is enough
unclaimed money in the Prolific account. If not, contact your lab
administrator about this.**

.. image:: /_static/images/running_studies/recruiters/prolific/recruit-participants.png
   :width: 8.5in

.. image:: /_static/images/running_studies/recruiters/prolific/study-cost-and-balance.png
   :width: 8.5in

Prolific: preview
~~~~~~~~~~~~~~~~~

If you want a final test of your experiment through Prolific, you can do
that if you change the participant_id in the url.

Please note that the data is saved in the database. Typically you want
to run the first trials, but not completing the experiment because your
data is saved as a real participant. In some experiments (like a static
experiment) you can then able to filter the data for participants that
did not finish the experiment.

Prolific: publish experiment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you are happy with all the settings, click on “publish” to put your
experiment online.

Monitoring
----------

Recruitment strategy
~~~~~~~~~~~~~~~~~~~~

It is recommended to start with an initial recruitment size of 5-10
people. After all these initial participants have finished the
experiment, you should check that you do not get any errors and that
your initial time estimate for the experiment is accurate. Only then you
can increase the experiment size manually. To do so click on “Action” on
the upper right side of the prolific dashboard and then on “increase
places”.

.. image:: /_static/images/running_studies/recruiters/prolific/recruitment-strategy.png
   :width: 8.5in

The number you set here is the additional number of participants you wish to add to your experiment.
For example, if you already have 5 participants and want to recruit 5 more, you should enter 5.
Make sure that you do not have too many participants
taking your experiment at once, because this could overload the server
and cause errors and slow-downs.

At any time, you should check for errors (you get an error report on
each export) and make sure that the median wage per hour (indicated on
the Prolific dashboard) does not fall below Prolific's minimum hourly rate.

**Auto-recruit**

Auto-recruit is a functionality in psynet that automatically increases
places in your experiment. You can change this parameter from the
experiment dashboard:

.. image:: /_static/images/running_studies/recruiters/prolific/auto-recruit-dashboard.png
   :width: 8.5in

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
~~~~~~~~~~~~~~~~~~~~

Messages that are specific to your experiment can be seen in the chat
box on the lower right.

It is suggested though, to click on “Messages” on the upper side of the
screen, to see all messages (also messages related to other
experiments).

.. image:: /_static/images/running_studies/recruiters/prolific/messages-inbox.png
   :width: 8.5in

Only this view lets you archive messages, which keeps a shared inbox
manageable. To do so (after you have handled the
participants issue) click on the checkbox of the message and then click
on “archive”.

.. image:: /_static/images/running_studies/recruiters/prolific/messages-in-prolific.png
   :width: 8.5in

Answering messages
~~~~~~~~~~~~~~~~~~

Since there can be various reasons why a participant is messaging you,
there is no standard way to answer. Most of the time though, a
participant is messaging you because they have encountered an error in
your experiment. If so, you can look for that participant in the
“participant” tab of your psynet dashboard by pasting their ID from
prolific to the “worker id” field. There you will find a “Link for
resuming session”, which you can send to the participant.

If that does not work or the participant cannot continue the experiment
because of a problem with the experiment, you should approve them manually. You
can do so by searching for their ID in the prolific dashboard and
clicking on the checkmark. By doing do they will be payed the base
payment you have set in the beginning.

.. image:: /_static/images/running_studies/recruiters/prolific/answering-messages.png
   :width: 8.5in

Termination
-----------

-  Make sure that there are no participants actively taking the
   experiment

-  Approve/reject people in awaiting review

-  The status of the experiment should be “\ **COMPLETED”**

-  Turn off auto-recruit! Otherwise it will keep recruiting
   participants, even if you stopped the experiment

-  Put experiment in your folder on Prolific.
