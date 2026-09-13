.. _errors:
.. highlight:: shell

=============
Error logging
=============

PsyNet includes a built-in error logging system that automatically captures runtime errors and exceptions during your experiment.

Live log viewer
=================

To view logs in real time, navigate to your experiment’s dashboard and open **Monitor > Logger** (endpoint: ``/dashboard/logger``).
This interface provides a live stream of log output, which you can:

- Search using keywords such as ``"error"`` or ``"exception"``
- Filter by severity level (e.g., ``"error"``, ``"warning"``)

Clicking on a specific log line reveals the full stack trace, helping you diagnose the source and cause of the error.

Error Database
=================
In addition to the live logger, PsyNet stores all errors in a structured database.
You can access this via **Monitor > Errors** (endpoint: ``/dashboard/errors``), where you’ll find a detailed list of all recorded errors.
Each error entry includes:
- The error message
- Full stack trace
- Timestamp of the error
- Associated participant, trial, network, or response ID (when applicable)

This persistent error log is especially helpful for debugging issues after the experiment has concluded.

Slack notifications
--------------------
We strongly recommended setting up the :doc:`Slack integration </tutorials/setting_up_slack>` to receive error notifications in your Slack channel.
This way, you will be notified immediately when an error occurs, and you can take action to fix it.

.. note::

    While PsyNet detects most errors, it's not guaranteed that all errors will be captured. So it's always wise to regularly check the logs and error reports to ensure that your experiment is running smoothly.
