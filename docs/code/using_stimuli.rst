Using stimuli and media
=======================

This page shows how the ideas in :doc:`/design/stimuli` appear in
``experiment.py``.

Ready-made files
----------------

Store each file's URL in the node definition. A file at
``static/instrument_sounds/clarinet.mp3`` has the URL
``/static/instrument_sounds/clarinet.mp3``.
:func:`~psynet.media.static_url_for` converts a path under ``static/`` to its
URL and raises an error for paths outside ``static/``. The
``demos/pipelines/similarity`` demo lists its sounds like this:

.. literalinclude:: ../../demos/pipelines/similarity/experiment.py
   :pyobject: list_stimuli

If the files are organized into participant-group and block folders,
``psynet.trial.compile_nodes_from_directory`` creates one node per file.

Pass the URL to the page, for example:

.. code-block:: python

    AudioPrompt(self.definition["audio_url"], "How pleasant is this sound?")
    ImagePrompt(self.definition["image_url"], "How happy is this face?", width="400px", height="400px")

:class:`~psynet.timeline.MediaSpec` accepts URLs in the same way, for pages
that play several files, such as the similarity demo's pair of sounds.

.. _large_stimulus_sets:

Large stimulus sets
~~~~~~~~~~~~~~~~~~~

The deployment package has a size limit, currently 1024 MB by default (see
:doc:`/code/project/experiment_directory`). Larger sets of pregenerated
images, audio, or video can be hosted in an Amazon Web Services S3 bucket and
linked into the experiment by URL.

1. Install the `AWS CLI
   <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>`_
   and check the installation with ``aws --version``.

2. Upload the files from their folder to a bucket and key (subdirectory),
   here ``my-bucket`` and ``my-key``, and list them to check the upload:

   .. code-block:: bash

       cd ~/my-audio-files/
       aws s3 cp . s3://my-bucket/my-key/
       aws s3 ls s3://my-bucket/my-key/

   .. warning::
       Spaces and special characters in file names can break the URLs. Use
       only lowercase Latin letters (``a-z``), digits, underscores (``_``) and
       hyphens (``-``).

3. Allow public read access with a bucket policy. Save the following as
   ``my-policy.json``:

   .. code-block:: json

       {
           "Version": "2012-10-17",
           "Statement": [
               {
                   "Sid": "PublicReadGetObject",
                   "Effect": "Allow",
                   "Principal": "*",
                   "Action": "s3:GetObject",
                   "Resource": "arn:aws:s3:::my-bucket/my-key/*"
               }
           ]
       }

   and apply it:

   .. code-block:: bash

       aws s3api put-bucket-policy --bucket my-bucket --policy file://my-policy.json

   The files are then available at URLs such as
   ``https://my-bucket.s3.amazonaws.com/my-key/my-file.wav``.

4. Allow cross-origin requests with a CORS policy. Save the following as
   ``my-cors.json``:

   .. code-block:: json

       [
           {
               "AllowedHeaders": ["*"],
               "AllowedMethods": ["GET"],
               "AllowedOrigins": ["*"],
               "ExposeHeaders": [],
               "MaxAgeSeconds": 3000
           }
       ]

   and apply it:

   .. code-block:: bash

       aws s3api put-bucket-cors --bucket my-bucket --cors-configuration file://my-cors.json

5. List the file names in a text file. Filtering by extension leaves out
   other files, such as the ``.DS_Store`` files created by macOS:

   .. code-block:: bash

       ls *.wav > stimuli.txt

6. Create one node per file in ``experiment.py``:

   .. code-block:: python

       from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
       from psynet.trial.static import StaticNode, StaticTrial

       S3_BUCKET = "my-bucket"
       S3_KEY = "my-key"


       def get_s3_url(stimulus):
           return f"https://{S3_BUCKET}.s3.amazonaws.com/{S3_KEY}/{stimulus}"


       with open("stimuli.txt", "r") as f:
           stimuli = f.read().splitlines()

       nodes = [
           StaticNode(definition={"url": get_s3_url(stimulus)})
           for stimulus in stimuli
       ]


       class AudioRatingTrial(StaticTrial):
           time_estimate = 5

           def show_trial(self, experiment, participant):
               return ModularPage(
                   "audio_rating",
                   AudioPrompt(self.definition["url"], "How much do you like this song?"),
                   PushButtonControl(["Not at all", "A little", "Very much"]),
               )

Files generated from code
-------------------------

Pass a function to :func:`~psynet.asset.asset`, and attach the result to the
node. The function receives the output ``path`` to write
to, plus any node definition fields named in its signature. The
``demos/pipelines/tapping`` demo builds each metronome stimulus this way:

.. literalinclude:: ../../demos/pipelines/tapping/repp_iso.py
   :pyobject: get_isochronous_stimulus

.. literalinclude:: ../../demos/pipelines/tapping/repp_iso.py
   :pyobject: generate_basic_stimulus

PsyNet runs ``generate_basic_stimulus`` at each launch, with ``stim_name`` and
``list_iois`` taken from the node definition. Output identical to a file
already in storage is not uploaded again. Trials read the generated folder's
URL from ``self.assets["stimulus"].url`` and append the file name, here
``/audio.wav``.

``is_folder=True`` lets the function write several files into one folder, here
the audio and an ``info.json`` file used when analyzing the recording.

Participant recordings
----------------------

Add an :class:`~psynet.modular_page.AudioRecordControl` or
:class:`~psynet.modular_page.VideoRecordControl` to the trial's page:

.. code-block:: python

    ModularPage(
        "sing",
        AudioPrompt(self.definition["audio_url"], "Sing back the melody."),
        AudioRecordControl(duration=5.0),
        time_estimate=10,
    )

PsyNet stores the recording with the trial. To analyze it on the server, see
"After the response" in :doc:`/code/writing_a_trial_maker`.

Where the files end up
----------------------

``psynet export`` downloads assets created during the experiment by default,
such as recordings and stimuli generated while the experiment runs. Assets
prepared before launch are left out. To generate cheap files that are never
stored or exported, use ``asset(function, on_demand=True)``. Pass
``--assets none`` to skip asset files entirely. See
:ref:`export_assets`.

.. seealso::

   :doc:`/code/trials/assets` for the asset system in detail, and
   :doc:`/reference/api/asset` in the API reference.
