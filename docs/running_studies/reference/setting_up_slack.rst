==============================
Setting up Slack notifications
==============================

To set up Slack notifications you will need to create a Slack app and install it.
After installation, each launched experiment will create a thread in a provided public channel and notifications will occur in this thread.

Creating a Slack app
--------------------
1. Go to https://api.slack.com/apps and click on "Create New App".
2. Select "From a manifest", select the workspace you want to use,
   then select "YAML", then paste in the below, then press "Next".

.. code-block:: yaml

    display_information:
      name: PsyNet Bot
      description: Experiment notifications
      background_color: "#000000"
    features:
      bot_user:
        display_name: PsyNet Bot
        always_online: true
    oauth_config:
      scopes:
        bot:
          - chat:write
          - chat:write.public
          - chat:write.customize
          - users:read
          - users:read.email
    settings:
      org_deploy_enabled: false
      socket_mode_enabled: false
      token_rotation_enabled: false

3. Click "Create" to create the app.
4. Scroll down to "Display Information", set a bot icon if you like, then click "Save Changes".
5. Go to the Settings menu item "Install app" and install it into the workspace.
6. Copy the "Bot User OAuth Token" and put it into your ``.dallingerconfig``:

::

    slack_bot_token = xxxxxxxx-xxxxxxxx-xxxxxxxx-xxxxxxxxx

7. Using the Slack app, create a Slack channel for your bot to report to.
   Note that this channel must be public.
   Enter the name of this Slack channel in your ``.dallingerconfig``,
   for example (here the channel is called ``#psynet-experiments``):

::

    slack_channel_name = psynet-experiments

8. Make sure your ``experimenter_name`` matches your name on Slack in order to receive @-mentions and receive notifications when messages arrive.

::

    experimenter_name = Max Mustermann


9. Add the following line to your config to use Slack as the notification service:

::

    notifier = slack


Usage
-----

By default PsyNet reports on the following events:
- Experiment started (and credentials for dashboard)
- Experiment finished
- Error occurred
- Recruitment updates

However, you can also add custom messages to the Slack channel by code like this:

.. code-block:: python

    bold = experiment.notifier.bold
    notify = experiment.notifier.notify
    notify("My custom message supporting " + bold("basic formatting"))

By default such notifications will only occur when an experiment is deployed (i.e. ``psynet deploy``),
not when it is run locally in debug mode (i.e. ``psynet debug``). However, to trial the Slack notification service
locally you can run ``psynet deploy local``.
