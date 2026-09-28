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

Error database
==============

In addition to the live logger, PsyNet stores all errors in a structured database.
You can access this via **Monitor > Errors** (endpoint: ``/dashboard/errors``), where you’ll find a detailed list of all recorded errors.
Each error entry includes:

- The error message
- Full stack trace
- Timestamp of the error
- Associated participant, trial, network, or response ID (when applicable)

This persistent error log is especially helpful for debugging issues after the experiment has concluded.

Server logs
===========

The dashboard logger shows the experiment's own log output. For the logs
of all containers on the server, use Dozzle or ``docker compose logs``;
see :ref:`lab-deployment-dashboard`.

Slack notifications
===================

Set up the :doc:`Slack integration </deploy/reference/setting_up_slack>`
to be notified in Slack as soon as an error occurs.

.. note::

    While PsyNet detects most errors, it's not guaranteed that all errors will be captured. So it's always wise to regularly check the logs and error reports to ensure that your experiment is running smoothly.
