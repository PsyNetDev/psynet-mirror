Monitoring and managing
=======================

Once your experiment is deployed, continuous monitoring is essential to
ensure smooth data collection, handle participant issues, and optimize
recruitment.

This section provides general guidelines. Recruiter-specific details
(Prolific, CINT, Lab Recruiter) can be found in their
:doc:`respective sections <recruiters/index>`.
For the full deployment monitor reference, see
:doc:`Deployment monitor </running_studies/reference/deployment_monitor>`.

.. _lab-deployment-dashboard:

Using the dashboard
-------------------

Once your experiment is deployed, the URL printed in the terminal (see
:ref:`Launch the experiment <lab-deployment-actual-deployment>`) opens
the same dashboard for every recruiter. For what each tab shows, see
:ref:`The experiment dashboard <experiment_dashboard>` in the
deployment reference.

Monitoring Participants & Data Collection
-----------------------------------------

-  Track participant progress and look for dropouts or errors.

-  Use **Dozzle logs** for real-time debugging. Regularly check for
   error messages in logs and fix critical issues immediately. The
   Dozzle URL is available at ``logs.<your-subdomain>.<your-domain>``
   (see :doc:`Provisioning <provisioning>`).

-  Monitor Prolific/CINT marketplaces for recruiter-specific insights.

Participant issues
------------------

Participants may contact you directly when they encounter errors.

Where participants may contact you:

-  **Prolific:** Via the Prolific messaging system. Participants can
   contact you through Prolific messages, so check messages regularly
   and respond in a timely manner.

-  **CINT:** Currently not possible through the platform.

-  **Lab Recruiter:** Via email sent to the address configured in your
   lab's Lab Recruiter setup.

Recruitment and payment strategies
------------------------------------

-  Start with a small recruitment batch (5–10 participants) and review
   data quality before increasing participation. After these initial
   participants have finished, check that there are no errors and that
   your time estimate for the experiment is accurate.

-  Regularly increase recruitment size manually rather than relying on
   auto-recruit for the entire study.

-  Adjust wage per hour and completion time estimates based on actual
   participant behavior.

-  If you are using auto-recruit, stop it before reaching the final
   stages to prevent excess costs.

For the canonical payment and recruitment configuration keys, see the
:doc:`configuration reference </reference/configuration>`.

Advanced monitoring for large deployments
-----------------------------------------

Large or parallel deployments need the same basic workflow as a single
deployment, but with more discipline around monitoring, notes, and
exports.

- If you need lightweight live checks, implement ``get_basic_data`` in
  your experiment. This lets you inspect an analysis-friendly view of
  the data from the dashboard or via the ``/basic_data`` endpoint
  without running a full export each time. For details, see
  :doc:`Data </running_studies/reference/data>`.

- Use the deployment monitor when you are running multiple active or
  recent deployments and need one place to check recruitment status,
  cost, runtime, server health, errors, participant counts, and quick
  links to dashboards or exports. For details, see
  :doc:`Deployment monitor </running_studies/reference/deployment_monitor>`.

- For high-risk or multi-day deployments, configure Slack notifications
  so errors and recruitment status changes are visible without
  repeatedly checking every dashboard. Ask your lab administrator which
  channel and bot token to use, then follow the PsyNet Slack setup
  instructions: :doc:`Setting up Slack </running_studies/reference/setting_up_slack>`.

- If your lab maintains scripts for provisioning, deploying, or
  destroying many experiments at once, treat them as lab-specific
  helpers. Verify each generated configuration before launch, keep app
  names and server names traceable, and export/check data early before
  scaling up recruitment.
