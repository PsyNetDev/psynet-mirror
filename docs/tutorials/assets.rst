======
Assets
======

Overview
--------

In PsyNet terminology, an :class:`~psynet.asset.Asset` is some kind of file (or collection of files) that
is referenced during an experiment. These might for example be video files that we play
to the participant, or perhaps audio recordings that we collect from the participant.

Working within PsyNet's :class:`~psynet.asset.Asset` framework brings various advantages. It abstracts away
the notion of file storage, meaning that you can switch between storage backends
(e.g. Amazon S3 versus your private web server) with just a single line of code.
It deals with the tedious book-keeping of keeping track of the different assets
associated with a given experiment, and it implements clever caching routines that
save time when redeploying different versions of the same experiment, as well as
asynchronous functionality that minimizes the performance impact of incorporating
large assets in your experiment. Moreover, it provides a handy export functionality
that allows you to compile all your generated assets in an organized fashion
suitable for your research paper's Supplementary Materials.

By default PsyNet stores assets on the same web server that is running your Python code.
We recommend most users go for this option as it offers the best performance.
However, other backends are possible, for example to store assets on Amazon S3.
See the :class:`~psynet.asset.S3Storage` class for more details.

Managed assets are stored by SHA-256 content identity under paths of the form
``objects/sha256/<digest>``. Local and on-demand browser access uses a stable,
random access token:

.. code-block:: text

    /asset/<access_token>

The token is an unguessable capability associated with the Asset row; it is not
derived from the content hash. S3-backed managed assets use a direct public
object URL instead (bytes are not proxied through PsyNet). External assets keep
their raw URL and are not proxied through PsyNet. On-demand assets are also
served via ``/asset/<access_token>`` and are generated when requested rather
than deposited into object storage by default.

Deposited managed assets receive a long-lived immutable cache policy. Local
asset responses are marked private so shared proxies do not retain participant
media. If a local asset is deposited again with different contents, PsyNet
rotates its access token and the old URL stops working. S3-backed assets instead
change their direct, content-addressed object URL when their contents change.
On-demand assets continue to revalidate because their bytes are generated at
request time.

.. warning::
    PsyNet's asset management system currently has some performance overhead that can make it slow
    to deploy large experiments (e.g. 1000s of files). For an alternative manual approach, see
    :ref:`large_stimulus_sets`.

Creating an asset
-----------------

The easiest way to create an asset is to use the ``asset`` function.
For example, within your experiment.py file you can create an asset as follows:

::

    from psynet.asset import asset

    logo_asset = asset("logo.svg")

In this case we are imagining that we have this `logo.svg` file already in our experiment directory,
but we could also have it located elsewhere:

::

    logo_asset = asset("/Users/sherlock/desktop/logo.svg")

.. note::
    If you do want to keep large (collections of) assets in your experiment directory,
    we recommend adding them to your ``.gitignore`` file. If you don't add them to ``.gitignore``,
    PsyNet will include them as part of the source code package that is sent to the server,
    which can lead to long upload times.


The idea is that, when we deploy the experiment, PsyNet will automatically upload the asset's file to
the storage back-end. However, to get PsyNet to recognize the asset, we first need to link it explicitly to the experiment.
We can do this either by linking the asset to a particular Module or to a particular Trial Node.

Linking assets to Modules
^^^^^^^^^^^^^^^^^^^^^^^^^

Linking to a Module makes sense for assets such as volume calibration files which are not linked to particular trials.
For example:

You can create an asset within a module by passing it to the module constructor's
``assets`` argument. This argument expects a dictionary. For example:

::

    import psynet.experiment
    from psynet.asset import CachedAsset

    class Exp(psynet.experiment.Experiment):
        timeline = join(
            Module(
                "my_module",
                my_pages(),
                assets={
                    "logo": asset("logo.svg"),
                }
            )
        )

You can then access this asset within your module as follows:

::

    from psynet.timeline import PageMaker

    def my_pages():
        return PageMaker(
            lambda assets: ModularPage(
                "audio_player",
                ImagePrompt(assets["logo"], "Look at this image."),
                time_estimate=5,
            )
        )

Note how the asset must be accessed within a ``PageMaker``,
and is pulled from the optional ``assets`` argument that we included
in the lambda function. This ``assets`` argument is populated with a dictionary
of assets from the current module.

Linking assets to Trial Nodes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Linking to a Trial Node makes sense for assets that correspond to particular trials.
We follow the standard procedure for creating a trial maker with a list of Trial Nodes,
but additionall pass dictionaries of assets to each node. For example:

::

    nodes = [
        StaticNode(
            definition={"id": i},
            assets={
                "stimulus": asset(f"stimulus_{i}.wav")
            },
        )
        for i in range(100)
    ]

    StaticTrialMaker(
        id_="static_audio",
        trial_class=CustomTrial,
        nodes=nodes,
        expected_trials_per_participant=len(nodes),
        target_n_participants=3,
        recruit_mode="n_participants",
    )

See how, similar to the Module use case, we pass the Node constructor a dictionary
for its `assets` argument, which we can then access during the trial as follows:

::

    class CustomTrial(StaticTrial):
        def show_trial(self, experiment, participant):
            return ModularPage(
                "imitation",
                AudioPrompt(
                    self.assets["stimulus"],
                    "Please imitate the spoken word as closely as possible.",
                ),
                AudioRecordControl(duration=3.0, bot_response_media="example-bier.wav"),
                time_estimate=5,
            )

Creating an asset from the participant's response
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are several built-in PsyNet components that will automatically create
an asset from the participant's response. For example,
if we use an :class:`~psynet.modular_page.AudioRecordControl` in our experiment,
PsyNet will automatically create an asset corresponding to our audio recording
which we can then access afterwards. See the following example code from
the static audio demo:

::

    class CustomTrial(StaticTrial):
        def show_trial(self, experiment, participant):
            return ModularPage(
                "imitation",
                AudioPrompt(
                    self.assets["stimulus"],
                    "Please imitate the spoken word as closely as possible.",
                ),
                AudioRecordControl(duration=3.0, bot_response_media="example-bier.wav"),
                time_estimate=self._time_trial,
            )

        def show_feedback(self, experiment, participant):
            return ModularPage(
                "feedback_page",
                AudioPrompt(
                    self.assets["imitation"],
                    "Listen back to your recording. Did you do a good job?",
                ),
                time_estimate=self._time_feedback,
            )

See how the ``AudioRecordTrial`` has created an asset with the label ``"imitation"``,
and a link to this asset is saved in the Trial object, accessed using the code
``self.assets["imitation"]``.

.. note::
    Most users should just be able to use these pre-existing utilities such as AudioRecordControl
    and VideoRecordControl. If you need to create a custom Control that implements such functionality,
    it's a good idea to look at the source code for these utilities.
    Their asset management code comes in the ``Control.format_answer`` method.
    They create their assets by instantiating the ``Recording`` class, but they could just as well
    have used the ``asset()`` helper function. To register the asset with PsyNet, they then call
    ``asset.deposit(...)``, passing various arguments to the ``deposit`` method, including ``parent``
    which links the asset to the current trial or participant.


Creating an asset when we create a Trial Node
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are certain chain-based experiments (e.g. imitation chains) where we might want to create
a new asset whenever we create a new Trial Node.
This is done by overriding the ``Node.async_on_deploy`` method, which is called whenever a new Node is 'deployed',
i.e., instantiated on the web server. The main thing to remember is that we need to call ``asset.deposit()``
to register the asset with PsyNet:

::

    class MyChainNode(ImitationChainNode):
        def async_on_deploy(self):
            with tempfile.NamedTemporaryFile() as temp_file:
                self.make_stimulus(temp_file.name)
                asset = asset(
                    local_key="stimulus",
                    input_path=temp_file.name,
                    extension=".wav",
                    parent=self,
                )
                asset.deposit()

For a more detailed example, see the source code for
:class:`~psynet.trial.record.MediaImitationChainNode`.


Creating an asset when we create a Trial
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default, PsyNet Trials inherit their definitions from the Trial Nodes that
created them. However, sometimes we add some additional manipulations to this definition,
for example adding a randomization component. We typically do this by overriding the
:meth:`~psynet.trial.main.Trial.finalize_definition` method.
At this point, we may then want to generate a new asset that reflects this updated
definition. This can be done as follows (source code from the third 'static audio'
demo):

::

    class CustomTrial(StaticTrial):
        def finalize_definition(self, definition, experiment, participant):
            definition["parameter"] = random.uniform(-100, 100)
            self.add_assets(
                {
                    "stimulus": OnDemandAsset(
                        function=synth_stimulus,
                        extension=".wav",
                    )
                }
            )
            return definition

For a more detailed example, see the source code for the third 'static audio' demo.


Accessing assets
----------------

Assets are often associated with particular database assets.
The following statements are all legitimate ways to access assets:

::

    participant.assets
    module.assets
    node.assets
    trial.assets

These `assets` attributes all take the form of dictionaries. This means that
you can access particular assets using keys that identify the relationship of that
asset to that object. For example, you might write ``trial.assets["stimulus"]``
to access the stimulus for a trial, and ``trial.assets["response"]`` to access
the response. Importantly, the same asset can have different keys for different items;
an asset might be the response for one trial and then the stimulus for another trial.
See the examples above for particular use cases.


Exporting assets
----------------

It is not strictly necessary to export your assets once you've run an experiment.
By default, PsyNet organizes your storage back-end in a sensible hierarchy
so that you can easily look up assets generated from a given historic experiment
deployment. However, there are some limitations of working with this format:

- Server-side managed assets use content-addressed ``objects/sha256/<digest>``
  paths. Exported archives instead use each asset's semantic ``export_path``.
- Cached files are omitted from the export. If you need a full set of stimuli
  for supplementary materials, copy them from the experiment directory or from
  storage.

PsyNet therefore provides an additional workflow for exporting assets.
This workflow is accessed via the standard ``psynet export`` command
that is responsible for exporting the database contents once an experiment is finished.
By default (``--assets collected``), PsyNet exports managed assets deposited
during the experiment — for example recordings. Cached stimuli, external URLs,
and on-demand assets are omitted. Use ``--assets none`` to skip asset files.
See :doc:`/deploy/data` for the export layout.

.. warning::
    Large experiments can still take a while to export when many collected
    assets are included. SSH command-line exports reuse a local object cache
    and copy missing files with ``rsync``. You can
    also export with ``--assets none`` and download selected files from storage.
    If you are using an SSH server, you can do this using the
    ``scp`` command, for example:

    ::

        scp -r \
            user@server.org:~/psynet-data/assets/experiments/my-experiment__mode=live__launch=2023-04-20--06-35-58 \
            ~/Downloads/my-experiment-assets

    If you are unfamiliar with the ``scp`` command, you can read more about it
    `here <https://man7.org/linux/man-pages/man1/scp.1.html>`_.

    If you are using S3 storage, you can download the assets using the ``aws s3 cp`` command.
    for example:

    ::

        aws s3 cp s3://bucket-name/path/to/assets . --recursive


Notes for advanced users
------------------------

Types of assets
^^^^^^^^^^^^^^^

Under the hood, PsyNet uses different classes to organize the functionality of different kinds of assets.

1. An :class:`~psynet.asset.ExperimentAsset` is an asset that is specific to the current experiment
deployment. This would typically mean assets that are generated *during the course*
of the experiment, for example recordings from a singer, or stimuli generated on the basis of
participant responses.

2. A :class:`~psynet.asset.CachedAsset` is an asset that is reused over multiple experiment
deployments. The classic use of a ``CachedAsset`` would be to represent some kind of stimulus
that is pre-defined in advance of experiment launch. In the standard case, the :class:`~psynet.asset.CachedAsset`
refers to a file on the local computer that is uploaded to a remote server on deployment.

3. An :class:`~psynet.asset.ExternalAsset` is an asset that is not managed by PsyNet. This would typically mean
some kind of file that is hosted on a remote web server and is accessible by a URL. We don't generally recommend
using these unless it's really necessary.

It's also worth knowing about a few special cases of these asset types.

- An :class:`~psynet.asset.ExternalS3Asset` is a special type of :class:`~psynet.asset.ExternalAsset`
  that is stored in an Amazon Web Services S3 bucket.

- A :class:`~psynet.asset.CachedFunctionAsset` is a special type of :class:`~psynet.asset.CachedAsset`
  where the source is not a file on the computer, but rather a function responsible for generating
  such a file. This means that you can write your stimulus generation code transparently as part
  of your experiment code.

- A :class:`~psynet.asset.OnDemandAsset` is like a :class:`~psynet.asset.CachedFunctionAsset`
  but has no caching at all; instead, the file is (re)generated on demand whenever it is requested
  from the front-end. This is suitable for files that can be generated very quickly.

Inheriting assets
^^^^^^^^^^^^^^^^^

Sometimes we run an experiment that produces some assets (e.g. audio recordings from
our participants), and we then want to follow up that experiment with another
experiment that uses those assets (e.g. to produce some kind of validation ratings).
PsyNet provides a helper class for these situations called
:class:`~psynet.asset.InheritedAssets`.
This class allows you to inherit assets from a previously exported experiment
and use them in your new experiment. See the class documentation for details.
