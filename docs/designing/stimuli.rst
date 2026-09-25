.. _concept_stimuli:

Stimuli and media
=================

Many experiments play sounds, show images, or record participants. How you
handle these files depends on where they come from.

Ready-made files
----------------

Most stimulus sets are a folder of existing files: sounds, images, or videos.
Put them in the experiment's ``static/`` folder. Everything in ``static/`` is
deployed with the experiment and served to participants' browsers, so each
node's definition only needs to record which file it uses.

The deployment has a size limit, currently 1024 MB by default. For larger
sets, host the files elsewhere and link to them; see
:doc:`/guides/trials/large_stimulus_sets`.

Files generated from code
-------------------------

Some stimuli are made by code rather than stored as files, for example tones
synthesized at particular frequencies, or rhythms prepared for a tapping
task. PsyNet runs your generation function on your machine each time the
experiment launches, and serves the results. Files identical to ones already
in storage are not uploaded again, so relaunching is quick when the stimuli
have not changed.

Keep any source material the generation needs, such as original recordings,
in the experiment's ``data/`` folder. It stays on your machine; only the
generated stimuli are deployed.

Participant recordings
----------------------

Pages can record audio or video from the participant, for example singing or
tapping along to music. PsyNet stores each recording with its trial, can
analyze it on the server as it arrives, and includes it when you export the
data. You do not need to manage these files yourself.

Recordings can identify participants. Treat exported recordings as personal
data.

Where the files end up
----------------------

- Ready-made stimuli are in your experiment folder, so they are already part
  of your project.
- Stimuli generated before launch are not included in data exports. Your
  generation code is the record of how they were made; keep it with the
  experiment.
- Files created while the experiment runs, such as participant recordings or
  stimuli generated from participants' responses, are included in data exports
  by default.

What to check when reviewing stimuli
------------------------------------

- Are all ready-made stimuli inside ``static/``, not referenced from
  elsewhere on your computer?
- Does each node's definition record which file or which generation
  parameters it uses, so the analysis can tell stimuli apart?
- Is the stimulus set within the deployment size limit?
- For generated stimuli, does the generation code produce the same files
  each time, for example by fixing any random seed?
- For recordings, is the recording duration right, and does the consent form
  cover recording?

.. seealso::

   :doc:`in_code/stimuli` shows how each of these ideas appears in
   ``experiment.py``.
