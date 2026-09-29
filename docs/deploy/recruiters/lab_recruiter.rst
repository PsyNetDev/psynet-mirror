.. _lab-deployment-lab-recruiter:

Lab Recruiter
=============

.. warning::

   Lab Recruiter is currently available only to Nori Jacoby and
   collaborators. If you would like to set it up for your own lab, contact
   `Nori Jacoby <https://norijacoby.com/>`_.

Lab Recruiter is a web application in which a lab manages its own
participant pool: participants register, take experiments, and have their
payments tracked, without a third-party marketplace. You need access to a
Lab Recruiter instance run by your institution. The experimenter usually
acts as Group Manager, who sets up participant groups and adds
experiments to them.

Connecting PsyNet to your instance
----------------------------------

PsyNet reports each participant's outcome to the Lab Recruiter instance.
The ``lab-recruiter`` recruiter posts to
``https://recruiter.cococo-lab.cornell.edu/tasks`` by default, and
``staging-lab-recruiter`` to that lab's staging instance; these are
example lab URLs. Point PsyNet at your own instance and add its API token
to ``~/.dallingerconfig``:

.. code-block:: ini

   lab_recruiter_external_submission_url = https://recruiter.your-lab.edu/tasks
   lab_recruiter_auth_token = xxxxxxx

Deployment fails without ``lab_recruiter_auth_token``. For local testing,
set ``debug_recruiter = dev-lab-recruiter``, which posts to
``http://localhost:8000/tasks`` unless the URL is overridden.

Setting up Lab Recruiter
------------------------

Admin account
^^^^^^^^^^^^^

Ask your Lab Recruiter administrator to create an admin account for you.

Participant group
^^^^^^^^^^^^^^^^^

As Group Manager, open the **Group** tab and click **New Group**.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/create-a-group.png
   :width: 8.5in

Initial test
^^^^^^^^^^^^

In the group settings you can enable an **Initial Test Experiment** that
checks participants' devices, including headphones and audio quality.
Participants must pass it before they can take any other experiment. For
other requirements, contact your Lab Recruiter administrator.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/set-an-initial-test.png
   :width: 8.5in

Consent
^^^^^^^

You choose the consent form when you create the group. Contact your Lab
Recruiter administrator to create or use a custom consent form.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/consent.png
   :width: 8.5in

Experiment configuration
------------------------

Set the recruiter to ``lab-recruiter`` and ``wage_per_hour`` according to
your lab's payment policy:

.. code:: python

   config = {
       "recruiter": "lab-recruiter",
       "wage_per_hour": 15,
       "initial_recruitment_size": 5,
       "title": "Put your experiment title here (Chrome browser, ~XX mins)",
       "description": (
           "This is a speaking experiment that needs to be done in a quiet "
           "place WITHOUT headphones. You will be asked to imitate rhythms. "
           "The task will take about 15 minutes."
       ),
       "contact_email_on_error": "you@example.org",
       "organization_name": "Your institution",
       "show_reward": False,
   }

Adding the experiment to Lab Recruiter
--------------------------------------

Deploy the experiment (see :doc:`/deploy/running_a_study`). Then open the
**Experiments** tab and click **New Experiment**.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/new-experiment.png
   :width: 8.5in

Set:

-  **Estimated Duration**: the expected duration of the experiment.
-  **Maximum Duration**: how long participants may stay in the experiment
   before they are timed out.
-  **Batches**: how many times each participant can take part.
-  **URL**: the experiment URL printed after deployment, for example
   ``https://<app-name>.<your-server-hostname>``.

At the bottom of the page, move your group from **Available groups** to
**Groups** to make the experiment available to everyone in the group.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/assign-groups.png
   :width: 8.5in

To change these settings later, click **Edit** on the experiment.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/edit-experiment.png
   :width: 8.5in

Inviting participants
---------------------

On the **Groups** tab, click **Copy Invitation Link** for your group and
email the link to participants. Participants who register through it are
added to your group.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/invite-participants.png
   :width: 8.5in

The messages option sends an email from the Lab Recruiter account to all
participants in a group or to selected participants, for example to
announce a new study.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/send-messages.png
   :width: 8.5in

Tracking participants
---------------------

Monitor the experiment itself on the PsyNet dashboard (see
:doc:`/deploy/running_a_study`). In Lab Recruiter, the **Participants**
tab shows each participant's experiments and payment status. Participants
who have problems contact you by email, at the address set in your lab's
Lab Recruiter setup.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/participant-tracking.png
   :width: 8.5in

To let a participant retry a failed experiment, open **Tasks** and click
**Reset**.

.. image:: /_static/images/running_studies/recruiters/lab_recruiter/managing-experiment-tasks.png
   :width: 8.5in

Ending the study
----------------

When a participant completes or fails the experiment, Lab Recruiter
updates its status, time, and payment record. When you reach the target
number of participants, export the data again, set the experiment to
**Archive** in Lab Recruiter, and remove it from the server (see
:doc:`/deploy/running_a_study`).

.. lab-note::

   If your lab processes payments outside Lab Recruiter, do not press
   **Payment Done** for completed participants; follow your lab's payment
   procedure instead.

What participants see
---------------------

1. Participants sign up with the invitation link and verify their email
   address.
2. In Lab Recruiter they see the available experiments, their details and
   links, and their payment status.

   .. image:: /_static/images/running_studies/recruiters/lab_recruiter/lab-recruiter-for-participants.png
      :width: 8.5in

3. If the group has an initial test, they take it first. Those who pass
   can take the real experiments; those who fail can retry if you reset
   their attempt.
4. They then take the available experiments. Their status updates
   automatically, and payment follows the lab's payment schedule.
