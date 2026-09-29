.. _software_stack:

PsyNet's software stack
=======================

PsyNet is a Python package built on established open-source tools. You rarely
use these tools directly, but knowing what each one does helps when you read
error messages, logs or other people's experiment code.

Dallinger
---------

PsyNet is built on `Dallinger <https://dallinger.readthedocs.io/>`_, a
framework for running networked experiments online. Dallinger provides the
experiment server, the database tables for participants, networks, nodes and
infos, integrations with recruitment services such as Prolific, the
experiment dashboard, and the commands that deploy an experiment to a server.
PsyNet adds the timeline, pages, trial makers, assets, bots and the
``psynet`` command line on top; ``psynet`` commands call Dallinger's where
needed.

The web server
--------------

- `Flask <https://flask.palletsprojects.com/>`_ is the web framework: each URL
  an experiment serves, from participant pages to custom routes, is a Flask
  route.
- `Gunicorn <https://gunicorn.org/>`_ runs the Flask app with
  `gevent <https://www.gevent.org/>`_ workers, so one server process can serve
  many participants at once, including over WebSockets
  (`Flask-Sock <https://flask-sock.readthedocs.io/>`_).
- `Jinja <https://jinja.palletsprojects.com/>`_ renders the page templates, and
  `dominate <https://github.com/Knio/dominate>`_ builds HTML from Python code,
  for example in prompts.

Data
----

- `PostgreSQL <https://www.postgresql.org/>`_ stores all experiment data.
  Each deployed experiment has its own database.
- `SQLAlchemy <https://www.sqlalchemy.org/>`_ maps Python classes such as
  participants, trials and nodes to database tables; see
  :doc:`/code/project/classes_and_sqlalchemy`.
- `Redis <https://redis.io/>`_ holds short-lived shared state and message
  queues. `RQ <https://python-rq.org/>`_ uses it to run background jobs, such
  as asynchronous code blocks, in worker processes, and
  `APScheduler <https://apscheduler.readthedocs.io/>`_ runs scheduled tasks in
  a separate clock process.
- `pandas <https://pandas.pydata.org/>`_ builds the CSV files in an export.

Participant pages
-----------------

- `Bootstrap <https://getbootstrap.com/>`_ provides the page layout and
  controls, with `jQuery <https://jquery.com/>`_ for older page scripts.
- `SurveyJS <https://surveyjs.io/>`_ renders questionnaires built with
  ``SurveyJSControl``.
- `Tone.js <https://tonejs.github.io/>`_ synthesizes sounds in the browser for
  ``JSSynth``.
- `jsPsych <https://www.jspsych.org/>`_ timelines can run inside PsyNet pages.
- `gettext <https://www.gnu.org/software/gettext/>`_ catalogs, managed with
  `Babel <https://babel.pocoo.org/>`_, hold translations; see
  :doc:`/code/participants/internationalization`.

Deployment
----------

- `Docker <https://docs.docker.com/>`_ packages the experiment and its
  dependencies into an image, and runs PostgreSQL and Redis on your computer
  during development.
- On a server, `Caddy <https://caddyserver.com/>`_ routes each experiment's
  web address to its containers and obtains HTTPS certificates, and
  `Dozzle <https://dozzle.dev/>`_ shows the containers' logs in the browser.
- `Amazon Web Services <https://aws.amazon.com/>`_ can host the server (EC2)
  and large stimulus files (S3); PsyNet talks to AWS with
  `boto3 <https://boto3.amazonaws.com/v1/documentation/api/latest/index.html>`_.

:doc:`/deploy/how_deployment_works` describes how these fit together.

Development tools
-----------------

- `uv <https://docs.astral.sh/uv/>`_ installs Python and the experiment's
  packages from ``constraints.txt``.
- `Click <https://click.palletsprojects.com/>`_ implements the ``psynet``
  command line.
- `pytest <https://docs.pytest.org/>`_ runs the bot tests behind
  ``psynet test local``, and `Playwright <https://playwright.dev/>`_ drives a
  real browser for layout and participant-flow tests.
- `Sphinx <https://www.sphinx-doc.org/>`_ builds this documentation.
