Exporting and terminating
=========================

.. _lab-deployment-export-data:

Export data
-----------

You can export the data from the command line. For the complete export
reference, including dashboard export, anonymization, assets, and basic
data files, see :doc:`Data </running_studies/reference/data>`.

In the lab workflow, run an export like this:

.. code:: bash

   psynet export ssh --app <APP_NAME> --server <SERVER> --path <PATH_TO_STORE_YOUR_DATA>

For example:

.. code:: bash

   psynet export ssh --app color-exp --server <your-subdomain>.<your-domain> --path ~/Experiments/color

Export script
-------------

It is good practice to have an ``export.py`` file in your experiment directory that contains:

-  Sanity checks

-  Export of demographic information

-  Export of the raw results to some preprocessed format, and

-  Preliminary plots of the main results

Sanity checks
^^^^^^^^^^^^^

These checks are very important because it allows us to determine
problems from early on and in case of error allows to abort the
experiment without receiving many complaints and paying many
participants.

Checks you must implement are:

-  Are time estimates set properly? -> e.g. make a histogram over the
   time it took to do trials

-  Do people progress fully through the experiment?

-  Do people do the required number of people do your trials? If people
   should do 60 trials, you should get 60 trials per participants

Try to use assertions for those sanity checks.

Export demographic information
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Read the required demographic information from the data, e.g. age and
gender from Participant.

Export of the raw results
^^^^^^^^^^^^^^^^^^^^^^^^^

Export your data to an output format you can use for plotting. E.g. save
a CSV you can import in Matlab or R.

Preliminary plot
^^^^^^^^^^^^^^^^

Make some preliminary plots to make sure you see the trend in the data.
If the results are very unexpected try to identify what can cause the
effect.

.. _best-practices-1:

Best practices
^^^^^^^^^^^^^^

Export regularly and run your export.py script. This way you can detect
problems from early on.

Export once more
----------------

After you made sure that the experiment is completed export the data one
last time.

In a new version of PsyNet, your logs will be downloaded automatically
upon exporting. You will also see an automatic analysis of the log file.

Additional manual export (large assets)
---------------------------------------

| In case you are experiencing trouble exporting large assets using
  psynet export, you can also try to zip and export the assets manually
  from the ssh server. Take note that the assets will not have the same
  nice cleaned names as when exported via psynet export ssh!
| To do this manual export of the assets:

-  ssh to the server as explained in :ref:`SSH into the instance
   <aws_automatic_ssh_into_instance>`

-  then you create a tar.gz of the assets folder on the server, by
   running in the terminal:

.. code:: bash

   tar -czvf $HOME/namefile.tar.gz $HOME/psynet-data/assets

-  leave the server, and on your local pc download this tar.gz by
   running in the terminal:

.. code:: bash

   scp -P 22 ubuntu@<SERVER_URL>:/home/ubuntu/namefile.tar.gz ~/Downloads

This downloads the ``.tar.gz`` file to your local ``Downloads`` folder.
Replace ``<SERVER_URL>`` with your server's URL. If your server uses
the default SSH port, you can omit ``-P 22``.
