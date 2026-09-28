Using stimuli and media
=======================

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

The deployment package has a size limit, currently 1024 MB by default (see
:doc:`/code/project/experiment_directory`). Larger sets of pregenerated files
can be hosted elsewhere and linked by URL, as described in
:doc:`/code/stimuli_on_s3`.

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

PsyNet stores the recording as an asset of the trial, under the page label:
here, ``self.assets["sing"]``. A ``VideoRecordControl`` with
``recording_source="both"`` stores two assets, with ``_camera`` and
``_screen`` appended to the label. To analyze a recording on the server, see
:ref:`trial_after_the_response`.

Where the files end up
----------------------

``psynet export`` downloads assets created during the experiment by default,
such as recordings and stimuli generated while the experiment runs. Assets
prepared before launch are left out. To generate cheap files that are never
stored or exported, use ``asset(function, on_demand=True)``. Pass
``--assets none`` to skip asset files entirely. See
:ref:`export_assets`.

.. seealso::

   :doc:`/code/trials/assets` and :doc:`/reference/api/asset` in the API
   reference.
