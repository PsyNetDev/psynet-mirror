.. _heroku_deployments:
.. highlight:: shell

==================
Heroku deployments
==================

Traditionally PsyNet and Dallinger experiments were deployed on Heroku.
Heroku provides a useful automated server provisioning service which
means you don't have to worry about purchasing and setting up
your own server. However, it is an expensive solution and one
that many PsyNet users are currently moving away from.

When deploying an experiment with Heroku you will see a ``Heroku``
tab in your experiment dashboard that provides links to useful
resources for monitoring your experiment. For example, you can see information
on the distribution of response times for your app's users:

.. figure:: ../../_static/images/deploy/heroku-response-time.png
  :align: center

See `Metrics <https://devcenter.heroku.com/articles/metrics>`_ for more details.

Sometimes when debugging an Heroku experiment it is useful to execute code on the remote
server. You can do this using the `Heroku Exec command <https://devcenter.heroku.com/articles/exec>`_.

Beware that leaving Heroku experiments running for a long time can rack up big bills.
Make sure that you always tear down your Heroku web servers
(``psynet destroy heroku``) when you're done (but don't forget to export your data first).
You can also tear down web servers via the Heroku interface.
