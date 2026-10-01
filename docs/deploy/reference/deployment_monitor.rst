Deployment monitor
==================

.. _experiment_dashboard:

The experiment dashboard
------------------------

Every deployed or debugged experiment has its own dashboard. This is
your main tool for tracking and managing a single study while it is
running. The URL, user name and password are printed in the terminal
after the deploy or debug command (see :doc:`/deploy/running_a_study`).

Key features:

- **Home page:** The experiment configuration, including the
  **auto_recruit** switch, which turns automatic recruitment on or off
  while the experiment runs.
- **Monitor > Networks:** View networks, nodes, parameters, and participant
  answers. Click shapes for details.
- **Monitor > Timeline:** Track participant counts, completions, and
  failures. See all the modules in your experiment and their completion
  percentages, the amount spent, and the spending limits, which you can
  change here (see :doc:`/code/participants/payment`).
- **Monitor > Participants:** Look up a participant by their recruiter ID in
  the Worker ID field. The participant page shows their status and
  payments and a **Link for resuming session**. Participants whose bonus
  PsyNet could not confirm are listed under **Needs payment review**, with
  options to pay or dismiss the bonus.
- **Monitor > Errors:** Every recorded error with its stack trace; see
  :doc:`Error logging </deploy/reference/errors>`.
- **Monitor > Logger:** A live stream of log output.
- **Monitor > Resources:** The server's CPU, memory and disk usage.
- **Database:** Browse the database tables.
- **Basic data:** A preview of the experiment's basic data, if
  ``get_basic_data`` is implemented.
- **Export:** Export the data. See
  :doc:`/data/exporting_data` for the full export reference.
- **Recruiter > Lucid:** CINT survey status and metrics, for CINT
  experiments; see :doc:`/deploy/recruiters/cint`.
- **Deployments:** The deployment monitor described below.

This single-experiment dashboard is different from the deployment
monitor described below, which shows *all* of your deployments at once.

The deployment monitor
----------------------

PsyNet allows you to monitor not only the progress of your own experiments, but also the status of other experiments.

To share the status of an experiment across multiple deployments, all relevant experiments must use the same ``artifact_storage``.
Artifacts can be backed up data exports of an experiment or files describing the current status of the experiment.
You can choose between two storage backends:

- ``LocalArtifactStorage``: Stores artifacts on the local filesystem (default).
  This is useful for local development or when multiple experiments run on the same server.
- ``S3ArtifactStorage``: Stores artifacts in an Amazon S3 bucket. This is ideal for sharing experiment status across different servers
  or for using cloud-based infrastructure.

Your experiment is registered with the deployment monitor when you deploy it with a
``psynet deploy`` subcommand, for example:


.. code:: bash

    psynet deploy ssh --app your-app-name --server your-server.example.org


.. warning::

    Running ``psynet debug`` will **not** register your experiment with the deployment monitor.


User interface
--------------

The deployment monitor displays experiments in a table grouped by recruiter. For each recruiter, the table shows specific metrics
such as the median time to complete a task and the real wage per hour (e.g., in Prolific).

Below each recruiter group, a cost summary is shown for all associated experiments.

You can filter the table by experiment name, experimenter name, recruiter name, or experiment status. This helps quickly identify issues
like budget overruns by recruiter or experimenter.

The table includes the following columns:

- **Study**: Shows the experiment’s label and current status (indicated by a traffic light icon). Click the experiment name to view more details such as repository URL, deployed Git commit, clean or dirty working-tree state, title, and description.
- **Recruitment**: Displays the recruitment status (e.g., "Published", "Draft", "Completed"). Click to view recruitment details, including the number of participants recruited and completed, and recruiter costs.
- **Experimenter**: The name of the experimenter who created the experiment. We recommend setting this in your ``.dallingerconfig`` file, see :doc:`Slack integration </deploy/reference/setting_up_slack>`.
- **Runtime**: Indicates how long the experiment has been running (relevant for the provisioning cost) and the start time. Click for more details.
- **Cost**: Displays the experiment’s cost, based on actual recruiter expenses. If PsyNet's internal cost estimate differs from the true cost, a warning icon is shown. Click for more information.
- **Duration**: The median experiment duration based on completion times. If this differs from PsyNet's internal estimate (via ``psynet estimate``), the real duration is shown in red.
- **Server**: Indicates where the experiment is hosted (``local`` or ``ssh``). Clicking shows the server's latest resource usage (CPU, memory, disk, etc.). Warnings and failures are flagged if resource limits are exceeded. Slack notifications are triggered if :doc:`configured </deploy/reference/setting_up_slack>`.
- **Errors**: Displays the number of errors that occurred. Click to view error types and counts. Slack alerts are sent if :doc:`Slack integration </deploy/reference/setting_up_slack>` is enabled, with direct links to error details and stack traces.
- **Participants**: Shows the number of completed participants. A checkmark means recruitment has ended. A warning appears if the completion counts differ between PsyNet and the recruiter. Click for details.
- **Actions**: Provides quick-access icons for managing the experiment (see below).

Actions
~~~~~~~

- **Comment**  Add a comment to the experiment. This is useful for logging deployment issues or observations during deployment.

If the experiment is **running**, you can:

- **Access the dashboard**: Click the icon to open the experiment dashboard in a new browser tab.
- **Access the data endpoint**: Click the icon to view the experiment’s :doc:`basic data endpoint </data/basic_data>` in a new tab.

If the experiment is **not running**, you can:

- **Archive the experiment**: Click to move the experiment to the archive. This is recommended for test runs or experiments that collected no data. Archived experiments can be accessed and restored via the "Show Archived Experiments" button in the top left corner.
- **Refresh recruiter metrics**: If participants are compensated after the experiment has ended (e.g., due to time estimation errors), recruiter metrics may become outdated. Use this action to refresh the metrics and update the experiment's total cost accordingly.
