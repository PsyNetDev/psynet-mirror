======================
Upgrading to PsyNet 10
======================

Introduction
============

PsyNet 10 brings a host of new features. We are excited about what these new features bring,
but they do necessitate a few changes to experiments implemented with earlier PsyNet versions.
This guide is intended to help you with that upgrade process.

Accumulating answers
====================

PsyNet supports Trials containing multiple Pages. If ``accumulate_answers`` is set to ``True``,
PsyNet used to accumulate the answers from these Pages into a single list, for example
``["yes", "no", "no"]``. Subsequently we realized that this behavior is quite dangerous for
data analysis, because it's easy to forget which page generated which response.
In PsyNet 10, answers are instead accumulated into dictionaries, for example
``{"color": "green", "hours": 23.5}``. The keys for the dictionaries come from the
Page labels.

When exporting data from such Experiments, PsyNet now automatically unpacks
these answers into separate columns. This means you don't have to worry about
unpacking the dictionary representation yourself.

Action needed
_____________

Action is only needed if your experiment uses answer accumulation
(i.e. you have ``accumulate_answers = True`` in one of your Trial classes).
If so:

- Check any code that refers to Trial answers
  (e.g. ``participant.answer`` or ``trial.answer``),
  and make any necessary updates for the new dictionary representation.
- Update your analysis code to account for the new export format;
  instead of unpacking the list, each element of the answer should already
  be present as different columns in your CSV file.


S3 and asset management
=======================

Previous PsyNet versions required experimenters to rely on Amazon S3 storage for managing media files.
They were expected to use various functions to interact with S3 manually,
doing things like managing S3 access permissions, creating buckets, uploading to S3, and so on.
This made it difficult to generalize a particular experiment implementation to other storage
back-ends, or to run such experiments without Internet access (e.g. in the context of field research).

PsyNet 10 incorporates a much more sophisticated approach to media management. There is a new
database-backed object hierarchy based on the :class:`~psynet.asset.Asset` class, where each
media file is represented as an Asset object that is linked to the database.
Different storage backends are then represented by different subclasses of the
:class:`~psynet.asset.AssetStorage` class.
Now when the experimenter manipulates media files, they do not have to worry about things like S3 permissions,
file naming, anonymization, linking response data to uploaded media files, and so on.
They can simply write things like ``asset.deposit()`` and everything will be managed for them.
Switching between different storage back-ends (e.g. from S3 to local storage) can be achieved
just by changing a single line of code in the Experiment class.

Action needed
_____________

If your experiments have any explicit interaction with S3 (which normally means calling PsyNet
functions with ``s3`` in the name), then this code will probably throw an error because those
PsyNet functions no longer exist. If you really want to keep this code the same for now,
you can get the source code for these old functions by going to the latest v9.x.x version of PsyNet,
and copy this into your Experiment file. However, it is recommend that you instead embrace the new
Asset management system when you upgrade your experiment.

The best way to move forward here is to first read the new Asset documentation chapter.
Once you have read this, look for the PsyNet demo that matches closest to your current situation.
This is likely to be the ``static_audio`` paradigm, which covers both pre-generated assets and
assets recorded during the experiment.

Note: Audio Imitation Chain experiments should not need any upgrading, as far as I can tell.

Static versus Chain experiments
===============================

PsyNet 10 consolidates the underlying implementation for Static experiments and Chain experiments
into a common code-base. As a result, Chain experiments can now access various features that
were originally only available in Static experiments, such as blocked designs and stimulus pre-generation.

The former implementation of Static experiments was rather complicated. One had to implement so-called
StimulusSpecs and StimulusVersionSpecs, which PsyNet compiled under the hood into Stimulus
and Stimulus Version objects which were stored in the database.
PsyNet 10 massively streamlines this procedure.
There is now no longer such thing as a Stimulus or a Stimulus Version; one just uses Nodes instead.
Moreover, the way for predefining experiment structure is now homogenized between Static and Chain experiments.
Rather than defining Stimulus Sets (for Static experiments)
or defining ``balance_across_networks`` constructs (for Chain experiments),
one now just provides a simple list of Nodes to the trial maker,
with these Nodes defining e.g. the initial set of stimuli or the starting states of the chain networks.

Action needed
_____________

Stimulus sets
~~~~~~~~~~~~~

Instead of passing a list of Stimulus Specs to the ``stimulus_set`` argument of the Trial Maker,
you should now pass a list of Nodes to the ``nodes`` argument of the Trial Maker.
See the ``static`` demo for an example.

Stimulus versions
~~~~~~~~~~~~~~~~~

Experiments using Stimulus Versions need to be reorganized.
The standard solution is to turn each Stimulus Version into a Node.
This has subtle implications for the balancing; previously balancing only
controlled the accumulation of Trials across Stimuli, not across Stimulus Versions.
This shouldn't matter much for most people.

Accessing stimuli within trials
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some people's experiments access the ``stimulus`` object within trial methods, for example:

.. code-block:: python

    def show_trial(self, experiment, participant):
        the_rule = self.stimulus.definition["rule"]
        ...

In such cases you should replace ``stimulus`` with ``node``:

.. code-block:: python

    def show_trial(self, experiment, participant):
        the_rule = self.node.definition["rule"]
        ...


More generally, it's a good idea to do a full-text search for ``stimulus`` throughout your code base
to find cases where it ought to be replaced with ``node``.


Assets
~~~~~~

Old PsyNet experiments that use Stimuli with media (e.g. audio files) need to be updated
to use the new PsyNet asset management system. The best way to do this is to read the new
``Asset`` documentation, and then explore the ``static_audio`` demo to see how assets are managed there.
It should be rather straightforward to update your code to follow this model.

Trial Makers
~~~~~~~~~~~~

The built-in arguments for Trial Makers have been updated slightly and pre-existing code is likely to
throw an error. Don't worry, the fixes are very minor.

- Some changes involve renaming ``stimulus`` to ``node``.
- Others involve replacing ``num_`` with ``n_``.
- There is a new argument called
  ``expected_trials_per_participant``, which is different from ``max_trials_per_participant``;
  the former is used for estimating experiment duration, whereas the latter is used as a rule
  for determining when the participant stops receiving trials from the Trial Maker.
- The old way of assigning participants to participant groups was to override the
  ``choose_participant_group`` method of the Trial Maker.
  The new way is to provide a function to the Trial Maker's ``choose_participant_group argument``,
  a function which takes one argument (``participant``) and returns the chosen participant group.

To find the up-to-date list of Trial Maker arguments, use the autocomplete function of your IDE,
or visit the documentation for :class:`~psynet.trial.chain.ChainTrialMaker`
or :class:`~psynet.trial.static.StaticTrialMaker` depending on what's appropriate.

Initializing chain experiments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Previously Chain experiments would initialize their chains using code like the following:

.. code-block:: python

    class CustomNetwork(AudioGibbsNetwork):
        ...

        def make_definition(self):
            return {"target": self.balance_across_networks(TARGETS)}


In PsyNet 10, networks are instead initialized by passing an optional list of Nodes
to the ``start_nodes`` argument of the Trial Maker. For example:

.. code-block:: python

    start_nodes=lambda: [CustomNode(context={"target": target}) for target in TARGETS],

This new approach is much more flexible, and moreover allows the experimenter to provide assets
for initializing those chains.

Custom network classes
======================

Implementing Chain experiments used to involve implementing custom Network classes, for example:

.. code-block:: python

    class CustomNetwork(AudioGibbsNetwork):
        synth_function_location = {
            "module_name": "custom_synth",
            "function_name": "synth_stimulus",
        }

        s3_bucket = "audio-gibbs-demo"
        vector_length = DIMENSIONS
        vector_ranges = [RANGE for _ in range(DIMENSIONS)]
        granularity = GRANULARITY

        n_jobs = 8  # <--- Parallelizes stimulus synthesis into 8 parallel processes at each worker node

        def make_definition(self):
            return {"target": self.balance_across_networks(TARGETS)}


This process has now been streamlined to avoid the need to define a custom Network class.
Instead all relevant parameters have been migrated to the custom Node class.
For example:

.. code-block:: python

    class CustomNode(AudioGibbsNode):
        vector_length = DIMENSIONS
        vector_ranges = [RANGE for _ in range(DIMENSIONS)]
        granularity = GRANULARITY
        n_jobs = 8  # <--- Parallelizes stimulus synthesis into 8 parallel processes at each worker node

        def synth_function(self, vector, output_path):
            custom_synth.synth_stimulus(vector, output_path)



Note that in this particular case (Audio Gibbs) there are several other changes too that have
streamlined the definition of the Custom Node class. They're covered in other parts of this documentation.

Action needed
_____________

If you have a Chain experiment you will need to migrate most elements from your custom Network class
to your custom Node class. The precise migration required depends on which paradigm you are using.
Look at the corresponding PsyNet demo for guidance here.


Audio Gibbs experiments
=======================

In addition to the changes noted above, the Audio Gibbs pattern now has a simplified mechanism
for specifying the synthesis function. Instead of this Network attribute:

.. code-block:: python

    class CustomNetwork(AudioGibbsNetwork):
        synth_function_location = {
            "module_name": "custom_synth",
            "function_name": "synth_stimulus",
        }

We now have this Node attribute:

.. code-block:: python

    class CustomNode(AudioGibbsNode):
        def synth_function(self, vector, output_path):
            custom_synth.synth_stimulus(vector, output_path)

Action needed
_____________

If you have an Audio Gibbs experiment you need to update your synthesis function specfication
to match the pattern described above.

Sources
=======

Former PsyNet versions had the concept of Sources.
Sources were used as the starting point for chains in paradigms such as Serial Reproduction
and Gibbs Sampling with People.
We have now streamlined the syntax for such experiments and eliminated the need for Sources,
subsuming their function under the Node class.

Action needed
_____________

This change should not impact most people's Experiment code. It may impact your analysis code,
depending on how it is implemented, but quite possibly not.


``prepare_trial``
=================

There is a Trial Maker method called ``prepare_trial`` which is responsible for preparing the
next trial that the participant receives. Originally this method was expected to return
either a Trial object or ``None``, with the latter signifying that the Trial Maker should terminate.
The signature of this method has now changed; it's now expected to return a tuple where the first
element is the Trial object, as before, with ``None`` if no Trial is found, and the second element
being a string taking one of three values: "available", "wait", and "exit".

Most experiments do not touch the ``prepare_trial`` method. However, experiments that do override it
need to be updated for PsyNet 10. For example, one's original code might look like this:

.. code-block:: python

    def prepare_trial(self, experiment, participant):
        if participant.var.has("expire"):  # finish the game
            logger.info("Ending game")
            return None
        return super().prepare_trial(experiment, participant)

Such code should be updated to this:

.. code-block:: python

    def prepare_trial(self, experiment, participant):
        if participant.var.has("expire"):  # finish the game
            logger.info("Ending game")
            return None, "exit"
        return super().prepare_trial(experiment, participant)


Accessing trials
================

Previously it was possible to access an object's trials by writing
``network.trials``, ``node.trials``, or ``participant.trials``.
We have moved on from this nomenclature because (partly for historic reasons)
it was not always clear whether the returned list included failed trials or not.
These attributes have now been replaced with the following:

- ``.all_trials`` - returns all trials owned by the object;
- ``.alive_trials`` - returns all non-failed trials owned by the object;
- ``.failed_trials`` - returns all failed trials owned by the object.

Action needed
_____________

Replace all occurrences of ``.trials`` with one of the three attributes listed above.
