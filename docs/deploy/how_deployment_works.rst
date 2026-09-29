How deployment works
====================

A deployed experiment runs on a web server so that participants can take part
over the internet. You run every deployment command on your own computer, from
the experiment directory; PsyNet and Dallinger connect to the server over SSH.

What gets deployed
------------------

PsyNet packages the experiment directory, leaving out the files that
``deploy.toml`` excludes (see :ref:`deployment_build_context`). Docker on the
server builds this package into an image that contains the experiment code and
its Python dependencies. The image is built on the server itself, so no Docker
registry is involved.

The same list of files, the **deployment plan**, is used for local debug
staging and for every deployment. Only ``deploy.toml`` decides what is in it;
``.gitignore`` doesn't, so Git-ignored files under ``static/`` are still
deployed. To see the plan, run:

.. code-block:: bash

   dallinger deployment-files list

``deploy.toml`` has an ``[exclude]`` table with three lists: ``paths`` are
prefixes relative to the experiment directory, ``names`` are file or
directory names excluded wherever they appear, and ``suffixes`` are literal
filename endings such as ``.db``. The stock file excludes, among others,
``data``, ``audit``, ``exports``, ``.cursor/skills/psynet``, ``.venv`` and
``.env``. Dallinger's
`deploy.toml guide <https://github.com/Dallinger/Dallinger/blob/master/docs/source/deploy_toml.rst>`_
describes the full format. PsyNet creates the file when it is missing and
never overwrites it. When a debug or deploy command creates it, the command
stops and lists the Git-ignored files the new file would include, so that you
can review them before rerunning. Experiments that still have a
``.dockerignore`` or ``docker/`` helper scripts need migrating first; see
:doc:`/whats_new/upgrading_deployment_file_selection`.

By default, the plan may be at most 1024 MB. Before raising the limit with the
``EXP_MAX_SIZE_MB`` environment variable, check the plan for exports, virtual
environments and private data.

Remote deployments need a Git repository with at least one commit. PsyNet
records the deployed commit and whether any file in the deployment plan had
uncommitted changes, including untracked or Git-ignored files. Changes to
files outside the plan, or elsewhere in a parent repository, don't count.
``psynet export`` compares this record with your local checkout and warns if
they differ. Commit your changes before a live deployment so that the
recorded commit matches what was deployed.

The server
----------

The server is a Linux machine that you can reach over SSH, such as an AWS EC2
instance that Dallinger provisions for you, a virtual machine from another
cloud provider, or a machine run by you or your institution. You register it
with Dallinger once; after that, deployment, export and destroy commands
select it with ``--server``. Registration installs Docker if needed. The first
deployment starts services that all experiments on the server share: a
PostgreSQL database server, a Caddy web server that routes each experiment's
address to it and obtains HTTPS certificates, and a Dozzle log viewer. One
server can host several experiments at once.

To collect data on a single computer, for example in the lab or in the field,
``psynet deploy local`` runs the experiment on your own computer instead. It
supports only the generic recruiter.

Apps
----

Each deployed experiment is an **app**, named with ``--app``. An app has its
own Docker containers, its own database on the server's PostgreSQL instance,
and its own address, ``https://<app>.<domain>``, where ``<domain>`` is the
server's DNS name. Participants see the app name in the address. PsyNet
refuses to deploy an app whose name is already in use on the server, so a
redeployment needs a new name or the old app destroyed first.

Recruiters
----------

The **recruiter**, set with ``recruiter`` in the experiment's configuration,
decides how participants reach the experiment and how they are paid:

- ``generic`` prints a single recruitment link when the deployment finishes.
  Anyone with the link can take part. It suits pilots with colleagues and
  studies that recruit through your own channels.
- :ref:`Prolific <lab-deployment-prolific>` creates a study on Prolific and
  pays participants there.
- :ref:`CINT <lab-deployment-cint>` creates a survey on CINT (formerly
  Lucid).
- :ref:`Lab Recruiter <lab-deployment-lab-recruiter>` recruits from
  participant groups that you manage on the Lab Recruiter platform.

The dashboard
-------------

Each app has a **dashboard** at ``https://<app>.<domain>/dashboard`` for
following participants' progress, reading logs, browsing the database and
exporting data (see :ref:`experiment_dashboard`). It uses the
``dashboard_user`` and ``dashboard_password`` from your configuration; if no
password is set, a random one is generated for each deployment. The deployment
command prints the dashboard address and credentials and saves them under
``~/psynet-data/launch-data``.

Debug and live deployments
--------------------------

``psynet debug ssh`` makes a pilot deployment and ``psynet deploy ssh`` makes
a live one for real data collection. Both build and serve the experiment in
the same way, at the same kind of address, with the same dashboard. PsyNet
records the mode, ``sandbox`` or ``live``, in the deployment ID, and in live
mode:

- Slack notifications are sent, if they are configured.
- A missing translation shows the English text and reports an error, instead
  of failing the page.
- A CINT survey can be published as soon as it is created.

Both modes use the recruiter set in the configuration. A pilot with
``recruiter = prolific`` therefore creates a real Prolific study, so pilot with
``recruiter = generic`` unless you are testing the recruiter itself.

What happens to the data
------------------------

Participants' responses are stored in the app's database on the server, and
any files they create are stored in the experiment's asset storage.
``psynet export ssh`` downloads the data to your computer (see
:doc:`/data/exporting_data`); export regularly while the study runs. ``psynet destroy
ssh`` stops the app and removes its folder from the server, after which
``psynet export`` no longer works, and tearing down an EC2 server deletes the
machine with every database on it. Export before either step, and treat data
you haven't exported as lost.
