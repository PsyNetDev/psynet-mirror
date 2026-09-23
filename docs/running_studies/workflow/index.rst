Lab research workflow
=====================

Use this section when your experiment already runs locally and you are
getting ready to collect real data. The :doc:`Getting started
</getting_started/index>` tutorial teaches the basics of building and
running PsyNet experiments, while the :doc:`deployment reference
</running_studies/reference/index>` explains server types, SSH deployment, data export,
and monitoring tools.

This guide is different: it is a runbook for the practical work around a
lab study. It helps you check the lab setup, prepare the server, choose a
recruiter, run a pilot, launch the experiment, monitor participants,
export the data, and clean up afterwards.

Use the deployment reference for more detail about server options,
deployment commands, data export, and monitoring tools. Use this
workflow when you want the steps in the order you are likely to need
them before and during data collection.

How to use this guide
---------------------

If you are launching an experiment for the first time, read the core
pages in order:

1. :doc:`Prerequisites <prerequisites>`: one-time software, account,
   credential, Git, and server-access setup.
2. :doc:`General research process <general_deployment_process>`: the
   order of work from design and testing through live deployment.
3. :doc:`Provisioning <provisioning>`: choosing or preparing the server
   that will host the experiment.
4. :doc:`Pre-launch setup overview <setting_up_the_experiments>`:
   final checks for configuration, recruiter, storage, and testing.
5. :doc:`Launch the experiment <deploying>`: the live deployment command
   and the final checks before real participants arrive.

Then read the sections that apply to your study:

- :doc:`Recruiter-specific steps
  <recruiter_specific_deployment_steps>` for :ref:`Prolific
  <lab-deployment-prolific>`, :ref:`CINT <lab-deployment-cint>`, or
  :ref:`Lab Recruiter <lab-deployment-lab-recruiter>`.
- :doc:`Monitoring and managing <monitoring_and_managing>` while the
  study is recruiting.
- :doc:`Exporting and terminating <exporting_and_terminating>` and
  :doc:`Teardown <teardown>` before you consider the deployment finished.
- :doc:`Deployment reference troubleshooting </running_studies/reference/troubleshooting>`
  and :doc:`Getting help <group_skills>` when something does not behave
  as expected.

The examples here assume the standard PsyNet installation locally and a
deployment to either an internal lab server or an EC2 server. Some
deployment routes still require Docker registry access; the
:doc:`Prerequisites <prerequisites>` page explains where that matters.

Glossary
--------

.. image:: /_static/images/lab_deployments/image29.png
   :width: 8.5in
   :class: glossary-hero

**PsyNet**
   The package we use to create online experiments. It builds upon
   Dallinger.

**Experiment hosting**
   The *server* that hosts your experiment. PsyNet supports
   **internal servers** and **EC2 servers**. The best choice depends on
   participant location.

**Docker**
   Container software used to run an experiment in a fixed environment
   to avoid unexpected behavior. Some deployment routes and experiment
   templates require Docker registry access.

**Recruiter**
   A *service* that invites and pays participants with optional
   demographic requirements. Examples include Prolific, CINT
   (previously Lucid), and Lab Recruiter.

**Remote debug (SSH)**
   Running ``psynet debug ssh`` against a server. This is not the same
   as deployment or hotair.

**Launch**
   Running ``psynet deploy ssh`` and activating a recruiter.

**Hotair**
   A participant-view test mode that is visible only to you and not to
   real participants. Use this before live deployment, and share the
   hotair link with team members for feedback.

**Archive (redeploy from archive)**
   Continuing data collection with an existing experiment. The archived
   experiment database file is called an archive.

**Provisioning**
   Setting up a server (here, typically via EC2).

**Teardown**
   Quitting a server (here, typically via EC2).

**initial_recruitment_size**
   The variable in your ``Experiment`` class that controls how many
   participants are invited initially. Avoid inviting more participants
   than your deployment can handle.

**Increase experiment size**
   Recruit more participants manually once current participants finish.
   Repeat until your target sample size is reached.

**Auto-recruit**
   Maintains a constant number of active participants. In this mode,
   ``initial_recruitment_size`` effectively becomes the desired steady
   concurrent count.

Best practices
--------------

We recommend a shared workflow because it makes problems easier to
diagnose and support:

- Use macOS where possible.
- Complete the :doc:`Prerequisites <prerequisites>` checklist, including
  Docker setup if your deployment route uses Docker. Cursor is most
  strongly recommended; VSCode and PyCharm are supported alternatives.
- Use one of the currently supported recruiters: Prolific, CINT, or Lab
  Recruiter.
- Check that your experiment satisfies the requirements of the recruiter
  you choose before you launch.

Workflow at a glance
--------------------

1. **Prerequisites**

   - Set up PsyNet and complete the required installations.
   - Ensure Docker Desktop is installed and running if your deployment
     route uses Docker.
   - Log in to the shared Docker registry via GitLab if your lab uses
     Docker images for deployment.

2. **Experiment setup**

   - Verify all experiment parameters.
   - Confirm locale, recruiter, and PsyNet estimates (time and payment).
   - Verify recruiter-specific settings, such as payment parameters,
     participant qualifications, demographic requirements, and any
     recruiter-specific configuration. See
     :doc:`Recruiter-specific steps <recruiter_specific_deployment_steps>`.

   - Use an appropriate storage backend (S3 or LocalStorage, not
     DebugStorage).

3. **Provisioning (server setup)**

   - Choose the correct server type (internal or EC2).
   - If using EC2, provision in the region closest to participants.
   - Confirm the EC2 instance type and local storage are sufficient if
     you use LocalStorage.

4. **Launch**

   - Test your experiment end-to-end locally and on the remote server,
     including edge cases.
   - Open Docker Desktop before launch if your deployment route uses
     Docker.
   - Ensure ``requirements.txt`` is correct and constraints are generated.
   - If using Prolific, ensure account balance is sufficient.
   - Deploy to your server and publish the experiment in Prolific/CINT.
     Double-check demographics and technical qualifications in the
     marketplace.

5. **Monitoring and management**

   - Start with 5-10 participants, then gradually scale once data and
     completions look good.
   - Monitor the dashboard to track participant progress and identify errors early.
   - Check Dozzle logs and inspect the error database table.
   - Monitor participant messages/free-text feedback and debug as needed.
   - Check data quality regularly (e.g., with an export script).

6. **Export and termination**

   - Export all collected data for analysis.
   - If using an internal server, delete the app.
   - If using EC2, teardown (terminate) the server to avoid unnecessary costs.
   - Deposit your export to your lab's designated data repository.

**Important:** Check the recruiter-specific sections for additional
setup and monitoring details.

.. toctree::
   :maxdepth: 1
   :hidden:

   Lab research workflow <self>
   Prerequisites (one-time setup) <prerequisites>
   General research process <general_deployment_process>
   Provisioning <provisioning>
   Pre-launch setup overview <setting_up_the_experiments>
   Launch the experiment <deploying>
   Monitoring and managing <monitoring_and_managing>
   Exporting and terminating <exporting_and_terminating>
   Teardown <teardown>
   Recruiter-specific steps <recruiter_specific_deployment_steps>
   Getting help <group_skills>
