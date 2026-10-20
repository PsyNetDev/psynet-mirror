.. _ssh_server:
.. highlight:: shell

===========
SSH servers
===========

``psynet debug ssh`` and ``psynet deploy ssh`` deploy to a Linux server that
you have :doc:`set up and registered </deploy/setting_up_a_server>`. This page
describes their addressing options, what they do on the server, and how to
work with a deployed app over SSH.

.. _ssh_server_addresses:

Server names and experiment addresses
-------------------------------------

``--server`` is a name registered with ``dallinger docker-ssh servers add`` or
``dallinger ec2 provision``, as listed by ``dallinger docker-ssh servers
list``. With one registered server it can be left out; with several, PsyNet
asks you to choose, or fails if the command is not run in an interactive
terminal.

``--dns-host`` sets the domain the experiment is served under. It defaults to
the server's own DNS name: the ``--dns-host`` saved with ``dallinger
docker-ssh servers add``, or else the ``--server`` name. The experiment is then
served at ``https://<app>.<server DNS name>``. Pass it:

- if the server is registered by IP address without a saved DNS name.
  ``--server`` is then the IP address and ``--dns-host`` the public name, and
  leaving ``--dns-host`` out is an error. Saving the name once with
  ``servers add --host <ip> --dns-host <name>`` avoids this:

  .. code:: bash

      psynet deploy ssh --app my-study --server 121.101.152.23 --dns-host my-server.example.org

- to use `nip.io <https://nip.io>`_ instead of a domain of your own.
  ``--dns-host nip.io`` serves the experiment at
  ``https://my-study.121.101.152.23.nip.io``. Some browsers warn participants
  about such names, and HTTPS certificates for nip.io names are sometimes
  unavailable because of rate limits.

Before deploying, Dallinger checks that the experiment's address
(``<app>.<dns-host>``, or ``<dns-host>`` without ``--app``) resolves to the
server's IP address and stops with a ``DNS resolution error`` otherwise. A
wildcard record (``*.my-server.example.org``) covers every app name; with a
fixed list of records, ``--app`` must be one of them.

``--app`` may contain only lowercase letters, digits and hyphens, and must not
already be in use on the server. Without ``--app``, the experiment is served at
the ``--dns-host`` name itself rather than a subdomain. If that is the
server's own DNS name, the deployment needs a server with no other apps:
Dallinger offers to destroy any it finds first.

A deployment's ``--dns-host`` names only that experiment's address. The
server's own sites, including the log viewer at ``https://logs.<server DNS
name>``, use the server's own DNS name. The exception is a server registered
by IP address without a saved DNS name, where the deployment's ``--dns-host``
also serves as the server's own; ``servers upgrade`` needs the saved name.

.. _ssh_server_cloudflare:

Cloudflare tunnels (optional)
-----------------------------

Classic docker-ssh deployments go through the host Caddy reverse proxy on
ports 80/443. You can instead deploy with a per-app Cloudflare tunnel so the
experiment is reachable at a first-level hostname such as
``https://consonance.science-of-music.org`` without opening those ports::

    psynet deploy ssh --app consonance --ingress cloudflare

Use a Cloudflare tunnel for a server on a private network, such as a lab
computer: Let's Encrypt cannot issue certificates for a private address, so
classic ingress cannot serve participants there. To make it the server's
default, register it with ``dallinger docker-ssh servers add --host <host>
--default-ingress cloudflare``. Cloudflare ingress needs a Dallinger version
newer than 12.4.

Classic ``--dns-host`` is only for host Caddy. Cloudflare hostnames use
``cloudflare_dns_zone`` from Dallinger config (for example
``science-of-music.org``).

Set the non-secret ``cloudflare_account_id``, ``cloudflare_zone_id``, and
``cloudflare_dns_zone`` in ``~/.dallingerconfig``. The API token is read from
``CLOUDFLARE_API_TOKEN``, then ``~/.dallingerconfig``, then the macOS
Keychain item ``dallinger-cloudflare-api-token``. It is never stored in host
records. With a Dallinger version that includes `Dallinger PR #10118
<https://github.com/Dallinger/Dallinger/pull/10118>`_, ``psynet deploy ssh``,
``psynet debug ssh`` and ``psynet performance-test ssh`` check that the token
can be read before they start local services, contact the server, reset local
data or run ``prepare``. Until a server default is changed, omitting
``--ingress`` keeps classic Caddy. ``psynet export ssh`` reaches a Cloudflare
app at its public name rather than ``https://<app>.<ssh-host>``.

Cloudflare ingress has no Dozzle log viewer: ``https://logs.<server DNS
name>`` exists only on servers with classic ingress. Read a Cloudflare app's logs with the
``ssh … docker compose … logs -f`` command printed at the end of the
deployment, or over SSH as described in :ref:`ssh_server_working_over_ssh`.
The dashboard's **Monitor > Logger** page shows the experiment's own log
output with either ingress.

.. _ssh_server_launch_info:

Launch information
------------------

``psynet deploy ssh`` and ``psynet debug ssh`` end with a summary of what
you need next:

.. code:: text

    Ready: my-study on my-server.example.org
      Participant link: https://my-study.my-server.example.org/ad?recruiter=generic&generate_tokens=1&mode=live
      Dashboard:        https://my-study.my-server.example.org/dashboard (user: admin)
      Password:         saved in ~/psynet-data/launch-data/<deployment-id>/launch-info.json
      Logs:             ssh -i ~/.ssh/my-key.pem ubuntu@my-server.example.org "docker compose -f ~/dallinger/my-study/docker-compose.yml logs -f"
      Log viewer:       https://logs.my-server.example.org (user: dallinger; password saved as logs_password in launch-info.json)
      Image:            ghcr.io/my-lab/my-study:3f2a9c1e

The image row names the deployed Docker image, with Dallinger versions that
report it. The participant link appears for recruiters that print a single recruitment
link, such as ``generic``; for other recruiters the summary ends with the
recruiter's message instead (for Prolific, a link to the new draft study).
The log viewer row appears for apps with classic ingress.
Passwords are not printed; they are saved in ``launch-info.json`` together
with the other details. With older Dallinger versions, Dallinger's own
summary, including the dashboard password, still appears above this one.
The deployment ID has the form
``<label>__mode=<mode>__launch=<timestamp>``.

What a deployment does
----------------------

1. PsyNet runs its pre-deployment checks and prepares the experiment files
   from ``deploy.toml``.
2. With classic ingress, Dallinger checks that the experiment's address
   resolves to the server and that the server's shared services are set up
   (see :ref:`ssh_server_shared_services`). If not, it stops and names the
   command to run.
3. Dallinger adds ``server_pem`` to your SSH agent and builds the Docker image
   with the server's Docker daemon, over SSH. The image stays on the server.
4. It creates the app's database and database user, writes
   ``~/dallinger/<app>/docker-compose.yml``, starts the app's containers and
   initializes the database.
5. It writes the app's Caddy route, ``~/dallinger/caddy.d/<app>``, and
   reloads Caddy. An app served at the server's own DNS name gets
   ``~/dallinger/root.d/<app>`` instead. It then calls the experiment's
   ``/launch`` route, which opens recruitment.

A deployment doesn't change the server's shared files or restart its shared
services, so the other experiments on the server keep running.

Experiment containers run as the SSH user rather than root. Deploy chowns
``~/psynet-data/assets`` (and other writable ``docker_volumes`` bind mounts
under the home directory) so files left as root by older deploys stay
writable, retrying with a root Alpine container if needed.
``psynet export ssh`` reaches a deployment at the public origin recorded in
its deployment manifest.

``psynet deploy ssh`` always installs the PsyNet and Dallinger versions pinned
in ``constraints.txt`` (``requirements.txt`` if there is no
``constraints.txt``). Before deploying, ``psynet deploy ssh``,
``psynet debug ssh`` and ``psynet performance-test ssh`` compare these pins
with the installed PsyNet and Dallinger, including the commit of an editable
checkout, and stop if they differ, so that you don't test one version locally
while the server runs another. Install the pinned versions with
``psynet setup``. To try unreleased PsyNet or Dallinger checkouts on a
server, bake them into a debug deployment's image::

    psynet debug ssh --app your-app-name --use-local-psynet --use-local-dallinger

Each option builds a wheel from the editable checkout (for Dallinger, or
``DALLINGER_SOURCE``), and the image build installs it after ``COPY .``, over
the pinned version. Before the build, PsyNet copies ``constraints.txt`` to
``local-image-pins.txt`` without that package's lines, and the image installs
the copy instead. Bundled demos and experiments without ``constraints.txt``
use ``requirements.txt``. This way, an editable pin that points at a path on
your machine does not break the build. Each option
also skips the sandbox checks on that package's pin, so bundled demos, whose
``requirements.txt`` lists plain ``psynet``, can be deployed with
``--use-local-psynet``. The options need the experiment's ``Dockerfile`` from
this PsyNet version; run ``psynet scripts update`` if PsyNet says it is out of
date.

Services
^^^^^^^^

Each app runs these Docker Compose services:

- ``web``, which serves HTTP requests;
- ``worker_1`` to ``worker_N``, which process background tasks, one for each
  of ``worker_processes`` (see :ref:`performance_testing_async_workers`);
- ``clock``, which runs scheduled tasks;
- ``redis``, which holds the app's cache and task queue;
- ``pgbouncer``, which pools the app's database connections.

All classic apps share these services, defined in ``~/dallinger/docker-compose.yml``:

- ``postgresql``, which holds one database for each app;
- ``httpserver``, a `Caddy <https://caddyserver.com/>`_ server that routes
  each address to its app and obtains HTTPS certificates;
- ``dozzle``, the log viewer at ``https://logs.<server DNS name>``.

Cloudflare-ingress apps instead run their own Postgres in the Compose project
and reach the internet through ``cloudflared``. They do not publish ports
80/443. Every app also has an unprivileged front-door Caddy and a private
hibernation controller.

Every service has the restart policy ``unless-stopped``, so Docker restarts
the apps when the server reboots.

.. _ssh_server_files:

Files on the server
^^^^^^^^^^^^^^^^^^^

``~/dallinger/``
   The shared ``docker-compose.yml``, ``Caddyfile``, Dozzle login
   (``dozzle-users.yml``) and ``.env.json``, which holds the log viewer's
   password as ``DOZZLE_PASSWORD``. They are read-only (see
   :ref:`ssh_server_shared_services`); ``.bak`` files are copies kept by
   ``servers upgrade``.
``~/dallinger/caddy.d/<app>``
   The app's Caddy configuration.
``~/dallinger/root.d/<app>``
   The Caddy route of an app served at the server's own DNS name, in place of
   ``caddy.d/<app>``.
``~/dallinger/<app>/docker-compose.yml``
   The app's services and configuration.
``~/dallinger-data/<app>/``
   Files the app stores on the server, mounted in its containers at
   ``/var/lib/dallinger``.

``psynet destroy ssh`` stops the app's containers and removes
``~/dallinger/<app>/``, its Caddy configuration, and its image if no other app
uses it. Give it one or more app names, as
arguments or with ``--app`` (the two are equivalent and can be combined):

.. code-block:: bash

    psynet destroy ssh my-app my-other-app --server my-server.example.org

It first checks that the apps are on the server; if one isn't, it stops and
lists the apps that are, suggesting the closest name (except with
``--remove-data``; see below). It then asks you to
confirm, once for all the apps (pressing Enter answers no); add ``--yes`` to
skip the confirmation in scripts, where it is required because there is no
terminal to ask in. If one of several apps fails to be destroyed, it carries
on with the rest and then exits with status 1. It also wakes each app if it is
asleep and asks it for pending async jobs, and does not destroy an app that
has some unless you pass ``--discard-pending-jobs`` or, when destroying a
single app, confirm; ``--yes`` does not skip this check. If the check cannot
run, for example because the app's web container is down, it does not destroy
the app without ``--discard-pending-jobs``, except for apps deployed with
``psynet debug ssh`` or ``psynet performance-test ssh``, which it destroys
anyway.
See :doc:`/reference/api/async_job`.

It also asks whether to delete the apps' data: the database and Postgres user
in the shared PostgreSQL, the app's Redis and Postgres volumes, and
``~/dallinger-data/<app>``. For a single app, Dallinger lists the app's data
with its sizes and asks, just before tearing the app down, and skips the
question if there is no data. For several apps, PsyNet asks once for all of
them, before checking any. Answer no, or pass ``--keep-data``, to keep the
data; each app's kept data is then listed with the command that deletes it
later. Pass ``--remove-data`` to delete it without a separate question; the
confirmation then says that the data is deleted too. ``--yes`` does not answer
the data question, so scripts and other non-interactive runs must pass one of
the two flags:

.. code-block:: bash

    psynet destroy ssh my-app --server my-server.example.org --yes --keep-data

Just before the question that decides whether the data is deleted (the data
question, or the confirmation with ``--remove-data``), PsyNet reminds you to
export any app it finds no export of in ``exports/`` of the current directory,
so you can still answer no. Nothing is asked about the data with
``--remove-data --yes`` or ``--keep-data``, so there is no reminder either.

To delete kept data after the app is gone, run the same command with
``--remove-data``. With ``--remove-data``, an app that is no longer on the
server is not rejected: PsyNet skips the pending-job check and the export
reminder for it, asks to delete its leftover data rather than to destroy it,
and Dallinger deletes whatever data it left behind. If nothing is left, it
says so and this does not count as a failure, so the command succeeds.

The data question and the two flags need a Dallinger version whose
``dallinger docker-ssh destroy`` has ``--remove-data`` and ``--keep-data``.
With older versions, ``psynet destroy ssh`` refuses the flags and destroys apps
as before: a classic app's database stays in PostgreSQL until an app with the
same name is deployed, which replaces it, while a Cloudflare app's volumes are
deleted.

.. _ssh_server_shared_services:

Setting up and upgrading the shared services
--------------------------------------------

Deployments never set up the shared classic-ingress services. These Dallinger
commands do:

- ``dallinger docker-ssh servers add`` sets them up on a server that has no
  ``~/dallinger/docker-compose.yml`` yet, unless it is registered with
  ``--default-ingress cloudflare``, and prints the new log viewer password
  once. It leaves a server that already has that file unchanged.
  ``dallinger ec2 provision`` does the same for the server it creates.
- ``dallinger docker-ssh servers upgrade --host <server>`` sets them up or
  rewrites them. Run it on a server set up by an older Dallinger version, and
  when a deployment asks for it:

  .. code-block:: bash

      dallinger docker-ssh servers upgrade --host my-server.example.org

  It lists the files it will replace and asks first (``--yes`` skips the
  question). It keeps a ``<file>.<timestamp>.bak`` copy of each replaced file
  and keeps the log viewer's password. A root-domain app deployed by an older
  Dallinger keeps its address. Shared services whose configuration changed are
  recreated, which briefly interrupts every classic app on the server, so
  upgrade when no classic experiment is live.

These commands write the server's ``Caddyfile`` for its own DNS name (see
:ref:`ssh_server_addresses`). Caddy gives Let's Encrypt the
``--contact-email`` saved with the server, or else ``contact_email_on_error``;
``servers add`` saves ``contact_email_on_error`` unless you pass
``--contact-email``. Caddy keeps its HTTPS certificates on the ``caddy_data``
Docker volume, so they survive recreating Caddy. On a server set up by an
older Dallinger, the first ``servers upgrade`` adds this volume, and Caddy may
obtain new certificates once. The log viewer moves to ``https://logs.<server
DNS name>`` if it was at ``https://<server>/logs``, so that name must also
resolve to the server.

``servers add`` and ``ec2 provision`` (when they set up a server) and
``servers upgrade`` leave the shared ``Caddyfile``, ``docker-compose.yml``,
``dozzle-users.yml`` and ``.env.json`` read-only. Older Dallinger versions rewrite these files on every
classic deployment, so on such a server their deployments fail with
``PermissionError: [Errno 13] Permission denied``, after building the image
but before changing anything shared. Everyone who deploys to the server must
therefore use a Dallinger version with ``servers upgrade``. If an older
version rewrote the files anyway (for example when it ran as ``root``, or
after the files were made writable), deployments stop before the build and ask you to run ``servers
upgrade`` again, which restores them.

Updating a running app
----------------------

To ship a fix to an app that is already running, add ``--update`` to the
command that created it: ``psynet deploy ssh --update`` for a live app, or
``psynet debug ssh --update`` for a debug app. Repeat the ``--ingress`` the app
was deployed with. If you leave out ``--update``, PsyNet refuses to deploy onto
the existing app and prints the update command for it. PsyNet asks you to
confirm, then rebuilds the image and restarts the app. The update keeps:

- the app's database and the participants in it;
- its deployment ID and secret, so exports and dashboard records stay together;
- participants' sessions.

An update rebuilds only the image. It doesn't deposit new assets, set up
networks, or run pre-deploy routines again, so a new stimulus set needs a fresh
deploy. Participants' progress is a position in the timeline: don't change the
page sequence, module IDs or trial makers while anyone is still taking part.

Hibernation
-----------

Each docker-ssh app has a front door that can stop its expensive containers
while the app stays reachable. To sleep or wake an app by hand::

    psynet hibernate ssh --app your-app-name
    psynet awaken ssh --app your-app-name

A visitor to a sleeping app sees "Getting ready, please wait..." while it
wakes. ``GET /health`` probes do not wake it.

To sleep apps automatically after a quiet period, set in ``config.txt``::

    docker_ssh_idle_hibernate = true
    docker_ssh_idle_hibernate_minutes = 60

Before sleeping, the app is asked whether it must stay awake: it stays awake
while participants are working, while ``auto_recruit`` is on, and while
async jobs are pending, so a backlog of low-priority jobs finishes first.

``/health`` probes do not reset the idle timer. While idle sleep is on,
PsyNet pages ping the server every few minutes while a participant is using
them: they interacted within the idle window, or an audible ``<audio>`` or
``<video>`` element is playing. Sound played through Web Audio, as
``AudioPrompt`` does, does not count, so a participant who listens for
longer than the idle window without interacting may wait for the app to
wake afterwards. The app therefore does not sleep under a participant, even on a
quiet or WebSocket-only page, while an abandoned tab stops pinging. Pages
that poll the server themselves, such as pages waiting for other
participants or pages that update progress live, keep the app awake for as
long as they stay open. If a participant submits while the app is asleep or
waking, PsyNet shows "Getting ready, please wait..." and retries the
submission for up to five minutes instead of showing the error page.

.. warning::

   Do not enable idle hibernation for experiments that replace failed
   participants or otherwise recruit reactively throughout their lifetime.
   This includes experiments that use ``auto_recruit`` to keep recruiting
   until they reach their target.

   While the app sleeps, the clock process and recruiter callbacks are
   suspended. For rolling-recruitment experiments, the quiet gaps *between*
   participants are when the system does critical work: detecting timeouts,
   triggering replacements, and preparing for the next arrival. Sleeping
   during those gaps means that work never happens.

   This restriction applies for the **entire lifetime** of a
   rolling-recruitment experiment, not only during active recruitment waves.

Idle sleep suits experiments with a clearly bounded recruitment window:
recruit N participants, run the session, recruitment ends. Once the session
is complete the app can safely sleep until you export the data. Leave it off
for first canary deploys too.

As a backstop, the app stays awake while ``auto_recruit`` is on, including
after you switch it on from the dashboard, and while any participant is
still working, until the clock times out abandoned participants. The app's
logs say why it stayed awake. An experiment that recruits in other ways can
add conditions by overriding ``reason_to_stay_awake`` on its ``Experiment``
class. Idle sleep needs the matching Dallinger release.

Hibernate by hand only apps that are not recruiting or serving participants.
``psynet export ssh`` awakens a
sleeping app before reading its database. If the app crashes while awake, it
returns HTTP 503 until Docker restarts it.

.. _ssh_server_working_over_ssh:

Working with an app over SSH
----------------------------

Log in to the server with the key from ``server_pem`` and go to the app's
folder:

.. code:: bash

    ssh -i ~/.ssh/my-server.pem ubuntu@my-server.example.org
    cd ~/dallinger/my-study

If the folder doesn't exist, the deployment failed before it reached the
server. In the folder:

.. code:: bash

    docker compose logs          # logs of all the app's services
    docker compose logs -f web   # follow the web service's log
    docker compose exec web /bin/bash   # open a shell in the web container
    docker compose restart web   # restart one service

``docker ps`` lists the running containers of every app on the server. The
deployment command prints a one-line version of the log command that you
can run on your computer.

Connecting to the database
--------------------------

The PostgreSQL server is one of the :ref:`shared services
<ssh_server_shared_services>`. To open ``psql`` on the server:

.. code:: bash

    docker compose -f ~/dallinger/docker-compose.yml exec postgresql psql -U dallinger

The database of each app has the app's name.

To connect a desktop client such as `Postico <https://eggerapps.at/postico2/>`_
through an SSH tunnel, first look up the database container's internal IP
address on the server:

.. code:: bash

    docker inspect \
        -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dallinger-postgresql-1

Then create a connection with these settings:

- Host: the IP address from ``docker inspect``
- Port: 5432
- User: ``dallinger``
- Password: ``dallinger``
- SSH tunnel: on, with the server's name or IP address as the SSH host, your
  username on the server, and the private key from ``server_pem``

Too many database connections
-----------------------------

Many apps on one server can use up PostgreSQL's connections, which are
limited to 100 by default. Apps then fail with:

.. code:: text

    psycopg2.OperationalError: FATAL:  remaining connection slots are reserved for non-replication superuser connections

To count the open connections, open ``psql`` as above and run:

.. code:: sql

    select datname as database_name, count(*)
    from pg_stat_activity
    group by datname;

Restarting an app's ``web``, ``worker_1`` and ``clock`` services with
``docker compose restart`` closes its connections. Restarts have occasionally
been followed by SQLAlchemy errors, so restart only when needed and check
that the app still works afterwards.

.. _docker_registry:

Docker registries
-----------------

``psynet debug ssh`` and ``psynet deploy ssh`` never push the image, so they
need no registry. A registry is needed only to deploy a prebuilt image named
by ``docker_image_name``, or to push images with Dallinger's ``dallinger
docker-ssh deploy --push-build`` or ``--local_build``. For pushing,
``docker_image_base_name`` must name a registry you can push to. The server
must be able to pull from the registry: run the same ``docker login`` on the
server as on your computer.

Docker Hub
   Create an account on `Docker Hub <https://hub.docker.com/>`_, sign in with
   ``docker login``, and set
   ``docker_image_base_name = docker.io/<username>/<image-name>``.

GitLab container registry
   Each GitLab project has a registry, which suits a team that shares
   images. Create a project such as ``experiment-images`` in the team's
   group, give everyone who deploys the Developer role or higher, and set
   ``docker_image_base_name =
   registry.gitlab.com/<group>/<project>/experiment-images`` (on a
   self-hosted GitLab, use its registry hostname). Sign in with:

   .. code:: bash

       docker login registry.gitlab.com -u your-username

   If you sign in to GitLab through another service, such as GitHub, Google
   or your institution, enter a
   `personal access token <https://gitlab.com/-/user_settings/personal_access_tokens>`_
   as the password.

Docker may warn that it stores the password unencrypted in
``~/.docker/config.json``; this works without a credential helper.
